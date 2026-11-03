"""Real homepage retry/storage behavior against an isolated server and AI double."""
import sys,threading,unittest
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server
sys.path.insert(0,str(Path(__file__).parent))
import test_speech42 as env
app=env.server.app
app.config.update(SECURITY_TEST_BYPASS=False,APP_INSECURE=True,SESSION_COOKIE_SECURE=False)

class RetryBrowserTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.http=make_server('127.0.0.1',0,app,threaded=True)
  threading.Thread(target=cls.http.serve_forever,daemon=True).start()
  cls.base='http://127.0.0.1:'+str(cls.http.server_port)
  cls.playwright=sync_playwright().start()
  cls.browser=cls.playwright.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True)
 @classmethod
 def tearDownClass(cls):cls.browser.close();cls.playwright.stop();cls.http.shutdown()
 def setUp(self):
  with env.database.get_conn() as c:c.execute('DELETE FROM interviews');c.execute('DELETE FROM start_requests')
  env.server.SESSIONS.clear();self.context=self.browser.new_context(viewport={'width':390,'height':844},reduced_motion='reduce')
  self.page=self.context.new_page();self.errors=[];self.page.on('pageerror',lambda error:self.errors.append(str(error)))
 def tearDown(self):self.context.close()
 def configure(self):
  self.page.goto(self.base,wait_until='networkidle');self.page.evaluate('Account.ready')
  self.page.locator('[data-mode=direct]').click();self.page.locator('.job-card').first.click()
 def start(self):
  self.page.locator('#startBtn').click();self.page.get_by_role('button',name='确认开始',exact=True).click()
 def test_saved_response_lost_then_refresh_retry_reuses_the_same_interview(self):
  self.configure();keys=[]
  def lose_response(route):
   keys.append(route.request.post_data_json['request_id'])
   response=route.fetch();self.assertEqual(response.status,200);route.abort()
  self.page.route('**/api/interview/start',lose_response)
  with patch.object(env.server,'call_deepseek',return_value='虚构首题') as ai:
   self.start();self.page.wait_for_function('document.querySelector("#appNotice")?.textContent.includes("历史记录")')
   self.assertEqual(len(env.database.list_interviews()),1)
   self.page.unroute('**/api/interview/start',lose_response)
   self.configure()
   with self.page.expect_request('**/api/interview/start') as retried:self.start()
   self.page.wait_for_url('**/interview');self.page.wait_for_function('!document.querySelector("#submitAnswerBtn").disabled')
   self.assertEqual(retried.value.post_data_json['request_id'],keys[0]);self.assertEqual(ai.call_count,1)
  self.assertEqual(len(env.database.list_interviews()),1);self.assertFalse(self.errors)
  self.assertEqual(self.page.evaluate("Object.keys(localStorage).filter(k=>k.startsWith('iv-start-request')).length"),0)
 def test_background_is_not_saved_in_retry_metadata(self):
  self.configure()
  result=self.page.evaluate('''async()=>{await InterviewStarts.prepare({job:'Java 后端',level:'校招标准',background:{resume_text:'fictional-sensitive-marker'}});return Object.keys(localStorage).filter(k=>k.startsWith('iv-start-request')).map(k=>localStorage.getItem(k)).join('')}''')
  self.assertNotIn('fictional-sensitive-marker',result);self.assertNotIn('resume_text',result)
 def test_storage_failure_stops_before_provider_dispatch(self):
  self.configure()
  self.page.evaluate('''(()=>{const original=Storage.prototype.setItem;Storage.prototype.setItem=function(k,v){if(k.startsWith('iv-start-request'))throw new DOMException('fictional','QuotaExceededError');return original.call(this,k,v)}})()''')
  with patch.object(env.server,'call_deepseek') as ai:
   self.start();self.page.wait_for_function('document.querySelector("#appNotice")?.textContent.includes("尚未发出AI")');ai.assert_not_called()
  self.assertTrue(self.page.locator('#startBtn').is_enabled());self.assertFalse(self.errors)
 def test_unknown_result_requires_explicit_new_attempt_and_never_auto_retries(self):
  self.configure();keys=[]
  def uncertain(route):
   keys.append(route.request.post_data_json['request_id'])
   route.fulfill(status=409,json=dict(error='虚构未知结果，请核对历史',code='start_uncertain'))
  self.page.route('**/api/interview/start',uncertain)
  self.start();self.page.wait_for_selector('#startResetBtn:visible')
  self.page.locator('#startResetBtn').click();self.assertEqual(len(keys),1)
  self.start();self.page.wait_for_selector('#startResetBtn:visible')
  self.assertEqual(len(keys),2);self.assertNotEqual(keys[0],keys[1]);self.assertFalse(self.errors)

if __name__=='__main__':
 try:unittest.main(verbosity=2)
 finally:env.tearDownModule()
