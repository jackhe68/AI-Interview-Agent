"""Report replay uses real retry metadata, timeout and persistent storage-failure UX."""
import sys,threading,unittest
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server
sys.path.insert(0,str(Path(__file__).parent))
import test_speech42 as env
app=env.server.app;app.config.update(SECURITY_TEST_BYPASS=False,APP_INSECURE=True,SESSION_COOKIE_SECURE=False)

class ReplayTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.http=make_server('127.0.0.1',0,app,threaded=True);threading.Thread(target=cls.http.serve_forever,daemon=True).start()
  cls.base='http://127.0.0.1:'+str(cls.http.server_port)
  cls.playwright=sync_playwright().start();cls.browser=cls.playwright.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True)
 @classmethod
 def tearDownClass(cls):cls.browser.close();cls.playwright.stop();cls.http.shutdown()
 def setUp(self):
  with env.database.get_conn() as c:c.execute('DELETE FROM interviews');c.execute('DELETE FROM start_requests')
  env.server.SESSIONS.clear();self.context=self.browser.new_context(viewport={'width':390,'height':844},reduced_motion='reduce');self.page=self.context.new_page();self.errors=[]
  self.page.on('pageerror',lambda error:self.errors.append(str(error)))
  self.page.goto(self.base,wait_until='networkidle');self.page.evaluate('Account.ready')
  info=self.context.request.get(self.base+'/api/account/session').json()
  with patch.object(env.server,'call_deepseek',return_value='虚构旧题目'):
   started=self.context.request.post(self.base+'/api/interview/start',headers={'Origin':self.base,'X-CSRF-Token':info['csrf_token']},data=dict(job='Java 后端',level='校招标准'))
  self.assertEqual(started.status,200);self.sid=started.json()['session_id']
  env.database.add_message(self.sid,'user','虚构旧回答','answer',2);env.database.finish_interview(self.sid)
  env.database.save_report(dict(interview_id=self.sid,overall_score=77,knowledge_score=80,completeness_score=70,expression_score=90,job_relevance_score=60,weaknesses=[],suggestions=[],overall_comment='虚构历史报告',knowledge_summary='虚构旧规则',confidence_note='',detail={}))
  self.page.evaluate("localStorage.setItem('iv-config',JSON.stringify({job:'Java 后端',level:'校招标准'}))")
 def tearDown(self):self.context.close()
 def report(self):
  self.page.goto(self.base+'/report?id='+self.sid,wait_until='networkidle')
  self.page.wait_for_function('!document.querySelector("#reportBody").classList.contains("is-hidden")')
 def test_storage_failure_stays_on_report_and_retry_reuses_the_saved_new_interview(self):
  self.report()
  self.page.evaluate('''(()=>{window.originalReplaySetItem=Storage.prototype.setItem;Storage.prototype.setItem=function(k,v){if(k==='iv-session')throw new DOMException('fictional','QuotaExceededError');return window.originalReplaySetItem.call(this,k,v)}})()''')
  with patch.object(env.server,'call_deepseek',return_value='虚构新首题') as ai:
   self.page.locator('#replaySameBtn').click()
   self.page.wait_for_function('document.querySelector("#appNotice")?.textContent.includes("浏览器未能保存")')
   self.assertIn('/report?',self.page.url);self.assertTrue(self.page.locator('#replaySameBtn').is_enabled())
   self.assertEqual(len(env.database.list_interviews()),2)
   self.page.evaluate('(()=>{Storage.prototype.setItem=window.originalReplaySetItem})()')
   self.page.locator('#replaySameBtn').click();self.page.wait_for_url('**/interview')
   self.page.wait_for_function('!document.querySelector("#submitAnswerBtn").disabled')
   self.assertEqual(ai.call_count,1)
  self.assertEqual(len(env.database.list_interviews()),2);self.assertFalse(self.errors)
 def test_html_gateway_failure_restores_button_and_keeps_report(self):
  self.report();self.page.route('**/api/interview/start',lambda route:route.fulfill(status=503,content_type='text/html',body='Fictional gateway failure'))
  self.page.locator('#replaySameBtn').click();self.page.wait_for_function('document.querySelector("#appNotice")?.textContent.includes("历史记录")')
  self.assertTrue(self.page.locator('#replaySameBtn').is_enabled());self.assertIn('/report?',self.page.url);self.assertFalse(self.errors)
 def test_timeout_is_bounded_and_never_automatically_retried(self):
  self.page.add_init_script('''const nativeFetch=window.fetch.bind(window),nativeTimeout=window.setTimeout.bind(window);window.replayCalls=0;
   window.setTimeout=function(fn,ms,...args){return nativeTimeout(fn,ms===90000?20:ms,...args)};
   window.fetch=function(input,options){const req=new Request(input,options);if(location.pathname==='/report' && new URL(req.url).pathname==='/api/interview/start'){window.replayCalls++;return new Promise((resolve,reject)=>{const cancel=()=>reject(new DOMException('Timeout','AbortError'));if(req.signal.aborted)cancel();else req.signal.addEventListener('abort',cancel);});}return nativeFetch(req);};''')
  self.report();self.page.locator('#replaySameBtn').click();self.page.wait_for_function('document.querySelector("#appNotice")?.textContent.includes("超时")')
  self.assertEqual(self.page.evaluate('replayCalls'),1);self.assertTrue(self.page.locator('#replaySameBtn').is_enabled());self.assertIn('/report?',self.page.url)

if __name__=='__main__':
 try:unittest.main(verbosity=2)
 finally:env.tearDownModule()
