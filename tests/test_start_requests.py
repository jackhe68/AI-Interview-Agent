"""Start retries are owner-scoped, durable and atomic. No external AI calls."""
import json,sys,threading,unittest,uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parent))
import test_accounts as account
import start_requests
env=account.env;app=env.server.app

class StartTests(unittest.TestCase):
 def setUp(self):
  with env.database.get_conn() as c:
   c.execute('DELETE FROM users');c.execute('DELETE FROM interviews');c.execute('DELETE FROM start_requests');c.execute('DELETE FROM auth_attempts')
  env.server.SESSIONS.clear();self.a=app.test_client();self.b=app.test_client();self.key=uuid.uuid4().hex
 def start(self,c=None,**extra):
  return account.send(c or self.a,'/api/interview/start',dict(job='Java 后端',level='校招标准',request_id=self.key,**extra))
 def test_lost_response_reuses_saved_result_after_memory_reset(self):
  with patch.object(env.server,'call_deepseek',return_value='虚构首题') as ai:
   first=self.start();env.server.SESSIONS.clear()
   with patch.object(start_requests,'RUNNER_ID','fictional-new-process'):second=self.start()
   self.assertEqual(first.status_code,200);self.assertEqual(second.json,first.json);self.assertEqual(ai.call_count,1)
  self.assertEqual(len(env.database.list_interviews()),1)
 def test_simultaneous_duplicate_does_not_dispatch_again(self):
  account.session(self.a)
  token=self.a.get_cookie(app.config['SESSION_COOKIE_NAME'],domain='accounts.test')
  self.b.set_cookie(app.config['SESSION_COOKIE_NAME'],token.value,domain='accounts.test')
  entered=threading.Event();release=threading.Event()
  def provider(*args,**kwargs):entered.set();self.assertTrue(release.wait(8));return '虚构首题'
  with patch.object(env.server,'call_deepseek',side_effect=provider) as ai:
   with ThreadPoolExecutor(max_workers=1) as pool:
    future=pool.submit(self.start,self.a)
    try:
     self.assertTrue(entered.wait(5));second=self.start(self.b)
     self.assertEqual(second.status_code,409);self.assertEqual(second.json['code'],'start_in_progress')
    finally:release.set()
    self.assertEqual(future.result(10).status_code,200)
   self.assertEqual(ai.call_count,1)
 def test_same_key_different_effective_input_is_rejected(self):
  with patch.object(env.server,'call_deepseek',return_value='虚构首题') as ai:
   self.assertEqual(self.start().status_code,200)
   changed=self.start(background={'skills':'虚构新技能'},background_consent=True)
   self.assertEqual(changed.status_code,409);self.assertEqual(ai.call_count,1)
 def test_other_identity_cannot_replay_a_saved_result(self):
  with patch.object(env.server,'call_deepseek',return_value='虚构首题') as ai:
   a=self.start();b=self.start(self.b)
   self.assertEqual(a.status_code,200);self.assertEqual(b.status_code,200)
   self.assertNotEqual(a.json['session_id'],b.json['session_id']);self.assertEqual(ai.call_count,2)
 def test_interrupted_dispatch_is_not_replayed_with_a_new_process(self):
  def interrupted(*args,**kwargs):raise KeyboardInterrupt()
  with patch.object(env.server,'call_deepseek',side_effect=interrupted):
   with self.assertRaises(KeyboardInterrupt):self.start()
  with patch.object(start_requests,'RUNNER_ID','fictional-restart'),patch.object(env.server,'call_deepseek') as ai:
   result=self.start();self.assertEqual(result.status_code,409);self.assertEqual(result.json['code'],'start_uncertain');ai.assert_not_called()
 def test_partial_save_rolls_back_and_retry_does_not_repeat_ai(self):
  with patch.object(env.server,'call_deepseek',return_value='虚构首题') as ai:
   with patch.object(env.database,'add_message',side_effect=OSError('fictional write failure')):
    failed=self.start();self.assertEqual(failed.status_code,500)
   self.assertEqual(env.database.list_interviews(),[])
   again=self.start();self.assertEqual(again.status_code,409);self.assertEqual(again.json['code'],'start_uncertain');self.assertEqual(ai.call_count,1)
 def test_deleted_record_cannot_be_restored_from_a_receipt(self):
  with patch.object(env.server,'call_deepseek',return_value='虚构私有首题') as ai:
   sid=self.start().json['session_id']
   self.assertEqual(account.send(self.a,'/api/interview/'+sid,method='DELETE').status_code,200)
   response=self.start();self.assertEqual(response.status_code,410);self.assertEqual(ai.call_count,1)
  with env.database.get_conn() as c:
   row=c.execute('SELECT state,response_json FROM start_requests').fetchone()
   self.assertEqual(row['state'],'deleted');self.assertIsNone(row['response_json'])
 def test_guest_claim_removes_guest_access_to_cached_start(self):
  account.session(self.a)
  original=self.a.get_cookie(app.config['SESSION_COOKIE_NAME'],domain='accounts.test')
  self.b.set_cookie(app.config['SESSION_COOKIE_NAME'],original.value,domain='accounts.test')
  with patch.object(env.server,'call_deepseek',return_value='虚构首题'):
   self.start()
  self.assertEqual(account.send(self.a,'/api/account/register',account.payload('claim_start')).status_code,200)
  self.assertEqual(account.send(self.a,'/api/account/claim-guests').status_code,200)
  with patch.object(env.server,'call_deepseek') as ai:
   result=self.start(self.b);self.assertEqual(result.status_code,404);ai.assert_not_called()
  self.assertEqual(account.send(self.a,'/api/account',dict(password='correct horse battery',confirmation='注销账户'),method='DELETE').status_code,200)
  with env.database.get_conn() as c:self.assertEqual(c.execute('SELECT count(*) FROM start_requests').fetchone()[0],0)
 def test_invalid_key_is_rejected_before_provider(self):
  self.key='invalid'
  with patch.object(env.server,'call_deepseek') as ai:
   self.assertEqual(self.start().status_code,400);ai.assert_not_called()
 def test_known_provider_failure_is_cached_until_an_explicit_new_attempt(self):
  with patch.object(env.server,'call_deepseek',side_effect=env.server.APIError(502,'虚构上游失败')) as ai:
   self.assertEqual(self.start().status_code,502);self.assertEqual(self.start().status_code,502);self.assertEqual(ai.call_count,1)
  self.key=uuid.uuid4().hex
  with patch.object(env.server,'call_deepseek',return_value='虚构首题'):
   self.assertEqual(self.start().status_code,200)
 def test_replay_does_not_consume_another_ai_budget(self):
  from api_guard import PublicAPIGuard,RELAXED_TRIAL_LIMITS
  guard=PublicAPIGuard(app,env.database,limits=dict(RELAXED_TRIAL_LIMITS,ai_day_browser=1))
  with patch.object(env.server,'call_deepseek',guard.wrap(lambda *args,**kwargs:'虚构首题',env.server.APIError)):
   first=self.start();second=self.start();self.assertEqual(first.status_code,200);self.assertEqual(first.json,second.json)
   self.key=uuid.uuid4().hex;self.assertEqual(self.start().status_code,429)
 def test_profile_change_does_not_rewrite_the_original_start_snapshot(self):
  registration=account.send(self.a,'/api/account/register',account.payload('start_profile'))
  self.assertEqual(registration.status_code,200)
  with patch.object(env.server,'call_deepseek',return_value='虚构首题') as ai:
   first=self.start(profile_consent=True)
   changed=account.send(self.a,'/api/account/profile',dict(nickname='虚构新称呼',major_id='other',other_major='虚构新专业',grade='graduated'),method='PATCH')
   self.assertEqual(changed.status_code,200)
   second=self.start(profile_consent=True);self.assertEqual(second.json,first.json);self.assertEqual(ai.call_count,1)
  self.assertNotEqual(env.database.get_profile_snapshot(first.json['session_id'])['major'],'虚构新专业')

if __name__=='__main__':
 try:unittest.main(verbosity=2)
 finally:env.tearDownModule()
