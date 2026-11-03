"""Typed SDK failures and bounded, individually-budgeted retries; no remote service."""
import json,sys,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).parent))
import test_speech42 as env
from openai import APIConnectionError,APITimeoutError,APIStatusError
from api_guard import PublicAPIGuard,RELAXED_TRIAL_LIMITS

SECRET='FICTIONAL_PRIVATE_ERROR_MARKER'
def response(content='虚构正常结果',finish='stop'):
 return SimpleNamespace(choices=[SimpleNamespace(finish_reason=finish,message=SimpleNamespace(content=content))])
def status_error(code,retry='60'):
 return APIStatusError(SECRET,response=SimpleNamespace(request=SimpleNamespace(url='https://fictional.invalid'),status_code=code,headers={'retry-after':retry}),body={'private':SECRET})

class ProviderTests(unittest.TestCase):
 def setUp(self):
  with env.database.get_conn() as c:
   c.execute('DELETE FROM interviews')
   if c.execute("SELECT 1 FROM sqlite_master WHERE name='trial_api_usage'").fetchone():c.execute('DELETE FROM trial_api_usage')
  self.create=Mock(return_value=response())
  fake=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=self.create)))
  self.client=patch.object(env.server,'client',fake);self.client.start();self.addCleanup(self.client.stop)
 def invoke(self):return env.server.call_deepseek([{'role':'user','content':'虚构待分析内容'}])
 def test_typed_errors_are_safe_and_do_not_retry_in_the_sdk_wrapper(self):
  cases=[(APITimeoutError(request=SimpleNamespace()),504,'超时'),
         (APIConnectionError(message=SECRET,request=SimpleNamespace()),502,'连接'),
         (status_error(401),502,'验证'),(status_error(403),502,'验证'),
         (status_error(402),503,'额度'),(status_error(429),429,'繁忙'),
         (status_error(503),502,'不可用'),(RuntimeError(SECRET),502,'异常')]
  for error,code,word in cases:
   with self.subTest(kind=type(error).__name__,code=code):
    self.create.reset_mock();self.create.side_effect=error
    with self.assertLogs(env.server.app.logger,level='WARNING') as logs:
     with self.assertRaises(env.server.APIError) as failed:self.invoke()
    self.assertEqual(failed.exception.code,code);self.assertIn(word,failed.exception.message)
    self.assertNotIn(SECRET,failed.exception.message);self.assertNotIn(SECRET,' '.join(logs.output));self.assertEqual(self.create.call_count,1)
 def test_bad_response_shapes_and_truncation_are_not_unhandled_500s(self):
  for value in (SimpleNamespace(choices=[]),SimpleNamespace(),SimpleNamespace(choices=[SimpleNamespace()]),
                response(None),response(42),response(''),response('   '),response('\ud800'),response('bad\x00text'),
                response('虚构截断','length'),response('unsupported','tool_calls')):
   with self.subTest(shape=type(value).__name__):
    self.create.return_value=value
    with self.assertRaises(env.server.APIError) as failed:self.invoke()
    self.assertEqual(failed.exception.code,502)
 def test_valid_response_preserves_text_and_token_ceiling(self):
  self.create.return_value=response('  虚构正常结果  ')
  self.assertEqual(self.invoke(),'虚构正常结果');self.assertEqual(self.create.call_args.kwargs['max_tokens'],10000)
 def test_invalid_retry_headers_keep_a_safe_default(self):
  for value in ('9'*5000,'-1','1.5','１',None):
   with self.subTest(header_type=type(value).__name__):
    self.create.side_effect=status_error(429,value)
    with self.assertRaises(env.server.APIError) as failed:self.invoke()
    self.assertEqual(failed.exception.code,429);self.assertEqual(failed.exception.retry_after,60)
 def guard(self,maximum=10):
  return PublicAPIGuard(env.server.app,env.database,limits=dict(RELAXED_TRIAL_LIMITS,ai_day_browser=maximum,ai_concurrent=1))
 def test_one_short_rate_limit_retry_reserves_two_attempts_and_releases_slot(self):
  self.create.side_effect=[status_error(429,'1'),response()]
  guard=self.guard()
  with env.server.app.test_request_context('/internal/test'),patch('api_guard.time.sleep') as sleep,patch('api_guard.random.uniform',return_value=.1):
   self.assertEqual(guard.wrap(env.server.call_deepseek,env.server.APIError)([{'role':'user','content':'虚构测试'}]),'虚构正常结果')
   sleep.assert_called_once_with(1.1)
  self.assertEqual(self.create.call_count,2)
  with env.database.get_conn() as c:self.assertEqual(c.execute("SELECT count FROM trial_api_usage WHERE bucket='ai_day_browser'").fetchone()[0],2)
  self.assertTrue(guard.slots.acquire(blocking=False));guard.slots.release()
 def test_long_wait_or_timeout_is_never_automatically_retried(self):
  for error in (status_error(429,'30'),APITimeoutError(request=SimpleNamespace())):
   self.create.reset_mock();self.create.side_effect=error
   with env.server.app.test_request_context('/internal/test'),patch('api_guard.time.sleep') as sleep:
    with self.assertRaises(env.server.APIError):self.guard().wrap(env.server.call_deepseek,env.server.APIError)([{'role':'user','content':'虚构测试'}])
    sleep.assert_not_called()
   self.assertEqual(self.create.call_count,1)
 def test_exhausted_budget_stops_before_the_second_provider_dispatch(self):
  self.create.side_effect=status_error(429,'1')
  with env.server.app.test_request_context('/internal/test'),patch('api_guard.time.sleep'),patch('api_guard.random.uniform',return_value=0):
   with self.assertRaises(env.server.APIError) as failed:self.guard(maximum=1).wrap(env.server.call_deepseek,env.server.APIError)([{'role':'user','content':'虚构测试'}])
   self.assertEqual(failed.exception.code,429)
  self.assertEqual(self.create.call_count,1)
 def test_repeated_short_429_stops_after_one_retry(self):
  self.create.side_effect=status_error(429,'1')
  with env.server.app.test_request_context('/internal/test'),patch('api_guard.time.sleep') as sleep:
   with self.assertRaises(env.server.APIError):self.guard().wrap(env.server.call_deepseek,env.server.APIError)([{'role':'user','content':'虚构测试'}])
  self.assertEqual(self.create.call_count,2);self.assertEqual(sleep.call_count,1)
 def test_json_contract_accepts_only_one_object_and_no_duplicate_fields(self):
  self.assertEqual(env.server.extract_json('```json\n{"valid":true}\n```'),{'valid':True})
  for text in ('prefix {"valid":true}','{"x":1} {"x":2}','{"x":1,"x":2}','[]','null','invalid','```json\n{}\n``` trailing'):
   self.assertIsNone(env.server.extract_json(text),text)
 def test_route_returns_a_gateway_error_for_an_empty_provider_envelope(self):
  self.create.return_value=SimpleNamespace(choices=[])
  result=env.server.app.test_client().post('/api/interview/start',json=dict(job='Java 后端',level='校招标准'))
  self.assertEqual(result.status_code,502);self.assertNotIn('IndexError',result.get_data(as_text=True))

if __name__=='__main__':
 try:unittest.main(verbosity=2)
 finally:env.tearDownModule()
