"""Account integration tests: real hashes, real sessions, isolated SQLite, mocked AI."""
import hashlib,io,json,sys,time,unittest,uuid
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parent))
import test_speech42 as env
from interview_catalog import MAJORS
app=env.server.app;app.config.update(SECURITY_TEST_BYPASS=False,APP_INSECURE=True,AUTH_RATE_LIMIT=1000)
BASE='https://accounts.test'
def payload(name='student_a'):
 return dict(username=name,password='correct horse battery',confirm_password='correct horse battery',nickname='虚构同学',major_id=next(iter(MAJORS)),other_major='',grade='master-1')
def session(client):return client.get('/api/account/session',base_url=BASE).json
def send(client,path,data=None,method='POST'):
 csrf=session(client)['csrf_token']
 return client.open(path,method=method,base_url=BASE,headers={'Origin':BASE,'X-CSRF-Token':csrf},json=data if data is not None else {})

class AccountTests(unittest.TestCase):
 def setUp(self):
  with env.database.get_conn() as c:
   c.execute('DELETE FROM users');c.execute('DELETE FROM interviews');c.execute('DELETE FROM auth_attempts')
  env.server.SESSIONS.clear();self.a=app.test_client();self.b=app.test_client();self.guest=app.test_client()
 def register(self,c,name='student_a'):
  r=send(c,'/api/account/register',payload(name));self.assertEqual(r.status_code,200,r.json);return r.json['user']
 def start(self,c,**extra):
  with patch.object(env.server,'call_deepseek',return_value='请介绍自己的学习项目'):
   r=send(c,'/api/interview/start',dict(job='Java 后端',level='校招标准',**extra))
  self.assertEqual(r.status_code,200,r.json);return r.json['session_id']
 def test_registration_validation_unique_and_hash(self):
  bad=payload();bad['password']='short';bad['major_id']=[]
  self.assertEqual(send(self.a,'/api/account/register',bad).status_code,400)
  bad=payload();bad['confirm_password']='different'
  self.assertIn('confirm_password',send(self.a,'/api/account/register',bad).json['fields'])
  user=self.register(self.a)
  self.assertEqual(send(self.b,'/api/account/register',payload('STUDENT_A')).status_code,409)
  with env.database.get_conn() as c:
   row=c.execute('SELECT password_hash FROM users WHERE id=?',(user['id'],)).fetchone()
  self.assertTrue(row[0].startswith('scrypt:'));self.assertNotIn('correct horse',row[0])
 def test_login_logout_expiry_and_rotation(self):
  self.register(self.a);old=self.a.get_cookie('iv_auth',domain='accounts.test').value
  self.assertEqual(send(self.b,'/api/account/login',dict(username='student_a',password='bad')).status_code,401)
  self.assertEqual(send(self.b,'/api/account/login',dict(username='student_a',password='correct horse battery')).status_code,200)
  self.assertNotEqual(old,self.b.get_cookie('iv_auth',domain='accounts.test').value)
  send(self.a,'/api/account/logout')
  self.a.set_cookie('iv_auth',old,domain='accounts.test')
  self.assertEqual(self.a.get('/api/account/profile',base_url=BASE).status_code,401)
  with env.database.get_conn() as c:c.execute('UPDATE auth_sessions SET expires_at=?',(time.time()-1,))
  self.assertIsNone(session(self.b)['user'])
 def test_profile_persistence_and_password_revokes_other_sessions(self):
  user=self.register(self.a)
  data={k:v for k,v in payload().items() if k in ('nickname','major_id','other_major','grade')};data.update(nickname='测试昵称',major_id='other',other_major='跨学科研究',grade='graduated')
  self.assertEqual(send(self.a,'/api/account/profile',data,'PATCH').status_code,200)
  send(self.b,'/api/account/login',dict(username='student_a',password='correct horse battery'))
  self.assertEqual(session(self.b)['user']['nickname'],'测试昵称')
  self.assertEqual(send(self.a,'/api/account/password',dict(current_password='wrong',password='a new password 123',confirm_password='a new password 123')).status_code,401)
  r=send(self.a,'/api/account/password',dict(current_password='correct horse battery',password='a new password 123',confirm_password='a new password 123',revoke_others=True))
  self.assertEqual(r.status_code,200);self.assertIsNone(session(self.b)['user']);self.assertEqual(session(self.a)['user']['id'],user['id'])
 def test_owner_checks_all_record_routes_and_csrf(self):
  self.register(self.a);self.register(self.b,'student_b');sid=self.start(self.b)
  for suffix in ['/api/interview/'+sid+'/state','/api/interview/'+sid+'/background','/api/report/'+sid,'/api/report/'+sid+'/export','/api/interview/'+sid+'/reanswers']:
   self.assertEqual(self.a.get(suffix,base_url=BASE).status_code,404,suffix)
  for path,method,data in [('/api/interview/'+sid,'DELETE',{}),('/api/interview/'+sid+'/background','DELETE',{}),('/api/report/'+sid+'/generate','POST',{}),('/api/report/'+sid+'/speech-review','POST',{}),('/api/interview/answer','POST',dict(session_id=sid,answer='test')),('/api/interview/end','POST',dict(session_id=sid))]:
   self.assertEqual(send(self.a,path,data,method).status_code,404,path)
  self.assertEqual(self.b.post('/api/interview/end',base_url=BASE,json={'session_id':sid}).status_code,403)
  self.assertEqual(self.b.get('/api/report/'+sid,base_url=BASE).status_code,403)
  self.assertEqual(self.b.post('/api/interview/end',base_url=BASE,headers={'Origin':'https://evil.test','X-CSRF-Token':session(self.b)['csrf_token']},json={'session_id':sid}).status_code,403)
  response=self.a.post('/api/speech/transcribe',base_url=BASE,headers={'Origin':BASE,'X-CSRF-Token':session(self.a)['csrf_token']},data={'session_id':sid,'audio':(io.BytesIO(b'x'),'test.wav')})
  self.assertEqual(response.status_code,404)
 def test_explicit_guest_claim_is_transactional_idempotent_and_not_reclaimable(self):
  sid=self.start(self.guest);self.assertEqual(session(self.guest)['guest_count'],1)
  self.register(self.guest,'guest_user');self.assertEqual(self.guest.get('/api/interview/'+sid+'/state',base_url=BASE).status_code,404)
  self.assertEqual(send(self.guest,'/api/account/claim-guests',{'ids':[sid]}).status_code,400)
  self.assertEqual(send(self.guest,'/api/account/claim-guests').json['migrated'],1)
  self.assertEqual(send(self.guest,'/api/account/claim-guests').json['migrated'],0)
  self.assertEqual(self.guest.get('/api/interview/'+sid+'/state',base_url=BASE).status_code,200)
  send(self.guest,'/api/account/logout');self.register(self.guest,'second_user')
  self.assertEqual(send(self.guest,'/api/account/claim-guests').json['migrated'],0)
  self.assertEqual(self.guest.get('/api/interview/'+sid+'/state',base_url=BASE).status_code,404)
 def test_profile_consent_never_sends_nickname(self):
  self.register(self.a);requests=[]
  def provider(messages,**kw):requests.append(json.dumps(messages,ensure_ascii=False));return '请介绍你的项目'
  with patch.object(env.server,'call_deepseek',side_effect=provider):
   send(self.a,'/api/interview/start',dict(job='Java 后端',level='校招标准'))
   send(self.a,'/api/interview/start',dict(job='Java 后端',level='校招标准',profile_consent=True))
  self.assertNotIn('虚构同学',''.join(requests));self.assertNotIn('硕士',requests[0]);self.assertIn('硕士',requests[1])
 def test_delete_cascades_sessions_records_and_cannot_claim(self):
  self.register(self.a);sid=self.start(self.a,profile_consent=True)
  from report_jobs import ReportJobs
  ReportJobs(env.database,app,lambda sid:None)
  env.database.add_message(sid,'user','仅用于级联删除的虚构回答','answer',2)
  with env.database.get_conn() as c:
   c.execute("INSERT INTO report_jobs(interview_id,state,subjects,updated_at) VALUES (?,'pending','[]',0)",(sid,))
   c.execute('INSERT INTO answer_receipts VALUES (?,?,?,?)',(sid,'fixture','hash','{}'))
   c.execute('INSERT INTO reanswers VALUES (?,?,?,?,?,?,?)',('fixture',sid,2,'虚构重答','fixture',env.database._now(),'fixture-v1'))
   c.execute('INSERT INTO speech_analyses(id,interview_id,question_sequence,result_json,created_at,expires_at) VALUES (?,?,1,?,?,?)',('fixture',sid,'{}',env.database._now(),9999999999))
  self.assertEqual(send(self.a,'/api/account',dict(password='wrong',confirmation='注销账户'),'DELETE').status_code,401)
  self.assertEqual(send(self.a,'/api/account',dict(password='correct horse battery',confirmation='注销账户'),'DELETE').status_code,200)
  self.assertIsNone(env.database.get_interview(sid));self.assertIsNone(session(self.a)['user'])
  with env.database.get_conn() as c:
   for table in ['users','user_profiles','auth_sessions','trial_owners','interview_profile_snapshots','interviews','messages','reports','interview_backgrounds','report_jobs','reanswers','speech_analyses','answer_receipts','interview_selections']:self.assertEqual(c.execute('SELECT count(*) FROM '+table).fetchone()[0],0,table)
 def test_rate_limit_and_request_timings(self):
  app.config['AUTH_RATE_LIMIT']=1
  try:
   self.register(self.a);self.assertEqual(send(self.a,'/api/account/register',payload('another')).status_code,429)
  finally:app.config['AUTH_RATE_LIMIT']=1000
  r=self.a.get('/',base_url=BASE)
  self.assertIn('db;dur=',r.headers['Server-Timing']);self.assertTrue(r.headers['X-Request-ID'])
 def test_saved_reanswer_has_no_ai_or_score_change(self):
  self.register(self.a);sid=self.start(self.a)
  env.database.add_message(sid,'user','原回答','answer',2)
  body=dict(answer_sequence=2,answer='新的练习回答',request_id=uuid.uuid4().hex)
  with patch.object(env.server,'call_deepseek',side_effect=AssertionError('must not call AI')):
   first=send(self.a,'/api/interview/'+sid+'/reanswers',body)
   second=send(self.a,'/api/interview/'+sid+'/reanswers',body)
  self.assertEqual(first.status_code,200);self.assertEqual(first.json,second.json);self.assertFalse(first.json['rescored'])
  self.assertEqual(len(env.database.get_messages(sid)),2)

 def test_concurrent_registration_conflict_is_atomic(self):
  from concurrent.futures import ThreadPoolExecutor
  clients=[app.test_client(),app.test_client()]
  for client in clients:session(client)
  with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda c:send(c,'/api/account/register',payload('same_user')).status_code,clients))
  self.assertEqual(sorted(results),[200,409])
  with env.database.get_conn() as c:
   self.assertEqual(c.execute('SELECT count(*) FROM users').fetchone()[0],1)
   self.assertEqual(c.execute('SELECT count(*) FROM user_profiles').fetchone()[0],1)
 def test_answer_boundaries_and_response_replay(self):
  self.register(self.a);sid=self.start(self.a)
  for answer in ['', '   ', '字'*4001, '\ud800', 'bad\x00value']:self.assertEqual(send(self.a,'/api/interview/answer',dict(session_id=sid,answer=answer)).status_code,400)
  body=dict(session_id=sid,answer='字'*4000,question_sequence=1,request_id=uuid.uuid4().hex)
  with patch.object(env.server,'call_deepseek',return_value=json.dumps(dict(comment='请补充具体内容',next_question='请说明方案'))) as ai:
   first=send(self.a,'/api/interview/answer',body);second=send(self.a,'/api/interview/answer',body)
  self.assertEqual(first.status_code,200);self.assertEqual(first.json,second.json);self.assertEqual(ai.call_count,1)
 def test_skip_is_unassessed_and_never_generates_invented_score(self):
  self.register(self.a);sid=self.start(self.a)
  env.database.add_message(sid,'user','（候选人选择跳过此题）','answer',2);env.database.finish_interview(sid)
  with patch.object(env.server,'call_deepseek',side_effect=AssertionError('skip-only must not call AI')):
   result=self.a.get('/api/report/'+sid,base_url=BASE,headers={'X-CSRF-Token':session(self.a)['csrf_token']})
  self.assertEqual(result.status_code,200)
  self.assertIsNone(result.json['scores']['overall']);self.assertTrue(all(d['score'] is None for d in result.json['radar_dimensions']))
  history=self.a.get('/api/interviews',base_url=BASE).json['items'];self.assertIsNone(history[0]['overall_score']);self.assertTrue(history[0]['has_report'])
 def test_owned_audio_csrf_validation_cleanup_and_restart_orphans(self):
  self.register(self.a);sid=self.start(self.a)
  headers={'Origin':BASE,'X-CSRF-Token':session(self.a)['csrf_token']}
  def upload(content=b'fixture',name='fixture.wav'):
   return self.a.post('/api/speech/transcribe',base_url=BASE,headers=headers,data={'session_id':sid,'audio':(io.BytesIO(content),name)})
  self.assertEqual(upload(name='bad.txt').status_code,400)
  self.assertEqual(upload(b'').status_code,400)
  paths=[]
  def transcribe(path):paths.append(Path(path));return '虚构的音频转写回答',1.2
  with patch.object(env.speech,'is_available',return_value=True),patch.object(env.speech,'transcribe',side_effect=transcribe):
   self.assertEqual(upload().status_code,200)
  self.assertTrue(paths and not paths[0].exists())
  from speech_temp import create,cleanup,root
  owned=Path(create(env.database,sid,'.wav'));owned.write_bytes(b'fictional audio')
  unrelated=root(env.database)/'unknown.txt';unrelated.write_text('preserve unknown file')
  from deletion_journal import path as journal_path
  with journal_path(env.database).open('a',encoding='utf-8') as stream:stream.write('{\"kind\":')
  self.assertEqual(send(self.a,'/api/account',dict(password='correct horse battery',confirmation='注销账户'),'DELETE').status_code,200)
  valid=[]
  for line in journal_path(env.database).read_text().splitlines():
   try:valid.append(json.loads(line))
   except ValueError:pass
  self.assertTrue(any(item.get('hash')==hashlib.sha256(sid.encode()).hexdigest() for item in valid))
  self.assertFalse(owned.exists());self.assertTrue(unrelated.exists())
  orphan=Path(create(env.database,'process-terminated','.wav'));orphan.write_bytes(b'fictional orphan')
  cleanup(env.database);self.assertFalse(orphan.exists());self.assertTrue(unrelated.exists())
 def test_logs_exclude_credentials_and_profile_text(self):
  import logging
  stream=io.StringIO();handler=logging.StreamHandler(stream);app.logger.addHandler(handler)
  try:
   self.register(self.a)
   with patch('accounts.profile_for',side_effect=RuntimeError('synthetic-private-answer')):
    response=self.a.get('/api/account/profile',base_url=BASE)
    self.assertEqual(response.status_code,500);self.assertIn('request_id',response.json)
  finally:app.logger.removeHandler(handler)
  text=stream.getvalue()
  for value in ['synthetic-private-answer','correct horse battery','虚构同学',self.a.get_cookie('iv_auth',domain='accounts.test').value]:self.assertNotIn(value,text)
  self.assertIn('request_timing',text)

if __name__=='__main__':unittest.main()
