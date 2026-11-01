"""Formal entry point retains ownership and CSRF even with AI quotas disabled."""
import os,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ['API_GUARD']='0';os.environ['APP_INSECURE']='0'
import database
with tempfile.TemporaryDirectory(prefix='formal-auth-') as temporary:
 database.DB_PATH=str(Path(temporary)/'formal.db')
 import deploy.wsgi as entry
 app=entry.server.app;entry.server.call_deepseek=lambda *args,**kwargs:'请介绍你的虚构项目'
 base='https://formal.test';a=app.test_client();b=app.test_client()
 def info(client):return client.get('/api/account/session',base_url=base).json
 def post(client,path,body):return client.post(path,base_url=base,headers={'Origin':base,'X-CSRF-Token':info(client)['csrf_token']},json=body)
 for client,name in [(a,'formal_a'),(b,'formal_b')]:
  catalog=info(client)
  registration=post(client,'/api/account/register',dict(username=name,password='formal password 123',confirm_password='formal password 123',nickname='虚构测试同学',major_id=catalog['majors'][0]['id'],grade='graduated'))
  assert registration.status_code==200
  cookie=registration.headers['Set-Cookie'];assert 'Secure' in cookie and 'HttpOnly' in cookie and 'SameSite=Lax' in cookie
 sid=post(a,'/api/interview/start',dict(job='Java 后端',level='校招标准')).json['session_id']
 assert b.get('/api/interview/'+sid+'/state',base_url=base).status_code==404
 assert a.post('/api/interview/end',base_url=base,json=dict(session_id=sid)).status_code==403
 assert a.get('/api/report/'+sid,base_url=base).status_code==403
 assert not b.get('/api/interviews',base_url=base).json['items']
 assert app.extensions['accounts'] and app.extensions['public_trial_installed']
 print('PASS formal entry: secure cookies, ownership and CSRF remain enforced with API_GUARD=0')
