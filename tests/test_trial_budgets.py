"""Identity-scoped public budgets, persistent counts and queued report context."""
import sys,time,unittest
from pathlib import Path
from unittest.mock import patch
from flask import g
sys.path.insert(0,str(Path(__file__).parent))
import test_accounts as account
from api_guard import install,PublicAPIGuard,LimitExceeded,trial_limits_from_env
env=account.env;app=env.server.app;BASE=account.BASE
limits,user_limits=trial_limits_from_env({})
guard=install(env.server,env.database,limits=limits,user_limits=user_limits)

class BudgetTests(unittest.TestCase):
 def setUp(self):
  with env.database.get_conn() as c:
   c.execute('DELETE FROM users');c.execute('DELETE FROM interviews');c.execute('DELETE FROM trial_api_usage');c.execute('DELETE FROM auth_attempts')
  env.server.SESSIONS.clear()
  guard.limits=dict(limits,ai_day_browser=2,ai_min_browser=100,ai_min_ip=1000)
  guard.user_limits=dict(user_limits,ai_day_browser=4,ai_min_browser=100)
  self.a=app.test_client();self.b=app.test_client();self.guest=app.test_client()
  self.calls=0
  def provider(*args,**kwargs):self.calls+=1;return '虚构首题'
  self.provider=patch.object(env.server,'call_deepseek',guard.wrap(provider,env.server.APIError));self.provider.start();self.addCleanup(self.provider.stop)
 def start(self,client):return account.send(client,'/api/interview/start',dict(job='Java 后端',level='校招标准'))
 def register(self,client,name):
  response=account.send(client,'/api/account/register',account.payload(name));self.assertEqual(response.status_code,200)
 def test_guest_limit_is_separate_from_account_and_other_guest(self):
  self.register(self.a,'budget_a')
  self.assertEqual([self.start(self.guest).status_code for _ in range(3)],[200,200,429])
  self.assertEqual([self.start(self.a).status_code for _ in range(5)],[200,200,200,200,429])
  self.assertEqual(self.start(self.b).status_code,200)
  self.assertEqual(self.calls,7)
 def test_account_budget_is_shared_across_devices_and_persists_in_new_guard(self):
  self.register(self.a,'budget_a')
  token=self.a.get_cookie('iv_auth',domain='accounts.test')
  self.b.set_cookie('iv_auth',token.value,domain='accounts.test')
  self.assertEqual([self.start(c).status_code for c in (self.a,self.b,self.a,self.b)],[200]*4)
  self.assertEqual(self.start(self.b).status_code,429)
  restarted=PublicAPIGuard(app,env.database,limits=guard.limits,user_limits=guard.user_limits)
  with app.test_request_context('/api/health',base_url=BASE,headers={'Cookie':'iv_auth='+token.value}):
   app.preprocess_request()
   with self.assertRaises(LimitExceeded):restarted.consume('ai')
 def test_failed_dispatch_still_counts_and_limit_does_not_call_provider(self):
  def failed(*args,**kwargs):raise env.server.APIError(502,'虚构上游失败')
  with patch.object(env.server,'call_deepseek',guard.wrap(failed,env.server.APIError)):
   self.assertEqual([self.start(self.guest).status_code for _ in range(3)],[502,502,429])
  self.assertEqual(self.calls,0)
 def test_daily_reset_and_retry_after(self):
  now=2000000000
  with patch('api_guard.time.time',return_value=now):
   self.assertEqual([self.start(self.guest).status_code for _ in range(2)],[200,200])
   response=self.start(self.guest);self.assertEqual(response.status_code,429)
   day=int((now+9*3600)//86400)
   self.assertEqual(int(response.headers['Retry-After']),(day+1)*86400-9*3600-now)
  with patch('api_guard.time.time',return_value=now+86400):self.assertEqual(self.start(self.guest).status_code,200)
 def test_queued_account_uses_account_budget_and_legacy_queue_is_supported(self):
  self.register(self.a,'budget_a');token=self.a.get_cookie('iv_auth',domain='accounts.test')
  with app.test_request_context('/api/health',base_url=BASE,headers={'Cookie':'iv_auth='+token.value}):
   app.preprocess_request();context=guard.report_context()
  self.assertEqual(context[2],'account')
  with app.test_request_context('/internal/report-job'):
   g.report_subjects=context
   for _ in range(4):guard.consume('ai')
   with self.assertRaises(LimitExceeded):guard.consume('ai')
  with app.test_request_context('/internal/report-job'):
   g.report_subjects=['fictional-old-subject','fictional-old-ip']
   self.assertEqual(len(guard.identities()),2);self.assertFalse(guard.account_budget())
   guard.consume('ai')
 def test_shared_ip_has_a_separate_generous_backstop(self):
  guard.limits['ai_day_ip']=2
  self.assertEqual(self.start(self.a).status_code,200);self.assertEqual(self.start(self.b).status_code,200)
  self.assertEqual(self.start(self.guest).status_code,429)
 def test_configuration_defaults_and_validation(self):
  guests,users=trial_limits_from_env({})
  self.assertEqual(guests['ai_day_browser'],100);self.assertEqual(users['ai_day_browser'],1000)
  self.assertEqual(guests['ai_concurrent'],1000);self.assertIsNone(guests['ai_day_global'])
  guests,users=trial_limits_from_env({'TRIAL_GUEST_AI_DAILY':'150','TRIAL_ACCOUNT_AI_DAILY':'1500','TRIAL_AI_CONCURRENT':'20'})
  self.assertEqual(guests['ai_day_browser'],150);self.assertEqual(users['ai_day_browser'],1500);self.assertEqual(guests['ai_concurrent'],20)
  for values in ({'TRIAL_GUEST_AI_DAILY':'0'},{'TRIAL_AI_CONCURRENT':'1001'},{'TRIAL_ACCOUNT_AI_DAILY':'invalid'}):
   with self.assertRaises(ValueError):trial_limits_from_env(values)

if __name__=='__main__':
 try:unittest.main(verbosity=2)
 finally:env.tearDownModule()
