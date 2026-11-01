"""Actual process restart and backup restore, with an isolated DB and provider doubles."""
import os,sys,tempfile,subprocess,socket,time,json,sqlite3,hashlib
from pathlib import Path
from contextlib import contextmanager
import requests
ROOT=Path(__file__).resolve().parents[1]
CHILD=r'''
import sys,os,json,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import database
database.DB_PATH=sys.argv[2]
import app
app.app.config.update(APP_INSECURE=True,AUTH_RATE_LIMIT=1000)
from report_jobs import ReportJobs
ReportJobs.LEASE=1
def provider(*args,**kw):
    if sys.argv[4]=='block':
        Path(sys.argv[2]+'.entered').write_text('entered')
        while True:time.sleep(.1)
    return json.dumps(dict(knowledge_score=80,completeness_score=70,expression_score=90,job_relevance_score=60,weaknesses=[],suggestions=['练习建议'],overall_comment='重启恢复测试'))
app.call_deepseek=provider
from werkzeug.serving import make_server
make_server('127.0.0.1',int(sys.argv[3]),app.app,threaded=True).serve_forever()
'''
@contextmanager
def connect(path):
 conn=sqlite3.connect(path)
 try:
  with conn:yield conn
 finally:conn.close()

def await_ready(url,process):
 end=time.monotonic()+12
 while time.monotonic()<end:
  if process.poll() is not None:raise AssertionError('child exited')
  try:
   if requests.get(url+'/api/health',timeout=.5).status_code==200:return
  except requests.RequestException:pass
  time.sleep(.1)
 raise AssertionError('child not ready')
with tempfile.TemporaryDirectory(prefix='account-restart-') as temp:
 db=Path(temp)/'test.db';script=Path(temp)/'child.py';script.write_text(CHILD,encoding='utf-8')
 with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
 base='http://127.0.0.1:'+str(port);env=os.environ.copy();env['SECRET_KEY']='restart-test-signing-key-only';env['APP_INSECURE']='1';env['PYTHONIOENCODING']='utf-8'
 def start(database,mode):return subprocess.Popen([sys.executable,str(script),str(ROOT),str(database),str(port),mode],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 process=start(db,'block');client=requests.Session();client.trust_env=False
 try:
  await_ready(base,process)
  info=client.get(base+'/api/account/session').json()
  registration=client.post(base+'/api/account/register',headers={'Origin':base,'X-CSRF-Token':info['csrf_token']},json=dict(username='restart_user',password='restart password 123',confirm_password='restart password 123',nickname='虚构重启同学',major_id=info['majors'][0]['id'],grade='master-1'))
  assert registration.status_code==200,registration.status_code
  uid=registration.json()['user']['id'];sid='restart-interview'
  with connect(db) as conn:
   conn.execute('INSERT INTO interviews(id,job,difficulty,started_at,status,owner_user_id) VALUES (?,?,?,?,?,?)',(sid,'Java 后端','校招标准','2026-11-01T10:00:00Z','finished',uid))
   for role,content,kind,seq in [('assistant','项目问题','main_question',1),('user','我的项目回答','answer',2)]:conn.execute('INSERT INTO messages(interview_id,role,content,message_type,created_at,sequence) VALUES (?,?,?,?,?,?)',(sid,role,content,kind,'2026-11-01T10:00:00Z',seq))
  assert client.get(base+'/api/report/'+sid,headers={'X-CSRF-Token':client.get(base+'/api/account/session').json()['csrf_token']}).status_code==202
  end=time.monotonic()+8
  while not Path(str(db)+'.entered').exists() and time.monotonic()<end:time.sleep(.05)
  assert Path(str(db)+'.entered').exists()
  orphan=db.parent/'.speech-temp'/(hashlib.sha256(sid.encode()).hexdigest()+'-forced.wav');orphan.write_bytes(b'fictional interrupted upload')
  unrelated=orphan.parent/'unknown.txt';unrelated.write_text('preserve unrelated file')
  process.terminate();process.wait(5)
  process=start(db,'ready');await_ready(base,process)
  assert not orphan.exists() and unrelated.exists()
  assert client.get(base+'/api/account/session').json()['user']['nickname']=='虚构重启同学'
  end=time.monotonic()+12
  while time.monotonic()<end:
   response=client.get(base+'/api/report/'+sid,headers={'X-CSRF-Token':client.get(base+'/api/account/session').json()['csrf_token']})
   if response.status_code==200 and response.json().get('available'):break
   time.sleep(.2)
  assert response.status_code==200 and response.json()['available']
  backup=Path(temp)/'backup.db'
  with connect(db) as src:
   with connect(backup) as dst:src.backup(dst)
  csrf=client.get(base+'/api/account/session').json()['csrf_token']
  assert client.delete(base+'/api/account',headers={'Origin':base,'X-CSRF-Token':csrf},json=dict(password='restart password 123',confirmation='注销账户')).status_code==200
  process.terminate();process.wait(5)
  with connect(backup) as src:
   with connect(db) as dst:src.backup(dst)
  process=start(db,'ready');await_ready(base,process)
  assert client.get(base+'/api/account/session').json()['user'] is None
  with connect(db) as conn:
   assert conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
   assert conn.execute('SELECT count(*) FROM users').fetchone()[0]==0
   assert conn.execute('SELECT count(*) FROM interviews').fetchone()[0]==0
  print('PASS actual restart restores authenticated profile and abandoned report; private audio orphan cleared; backup restore replays deletion hashes without resurrecting deleted data')
 finally:
  if process.poll() is None:process.terminate();process.wait(5)
