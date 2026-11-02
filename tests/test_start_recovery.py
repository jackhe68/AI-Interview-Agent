"""Browser start failures remain actionable; isolated data and AI doubles."""
import sys,threading,unittest
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server
sys.path.insert(0,str(Path(__file__).parent))
import test_speech42 as env

class StartRecoveryTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.http=make_server('127.0.0.1',0,env.server.app,threaded=True)
  threading.Thread(target=cls.http.serve_forever,daemon=True).start()
  cls.base='http://127.0.0.1:'+str(cls.http.server_port)
  cls.playwright=sync_playwright().start()
  cls.browser=cls.playwright.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True)
 @classmethod
 def tearDownClass(cls):
  cls.browser.close();cls.playwright.stop();cls.http.shutdown()
 def setUp(self):
  with env.database.get_conn() as conn:conn.execute('DELETE FROM interviews')
  env.server.SESSIONS.clear();self.page=self.browser.new_page();self.errors=[]
  self.page.on('pageerror',lambda error:self.errors.append(str(error)))
 def tearDown(self):self.page.close()
 def configure(self):
  self.page.goto(self.base,wait_until='networkidle')
  self.page.locator('[data-mode=direct]').click();self.page.locator('.job-card').first.click()
 def test_html_gateway_failure_restores_start_button(self):
  self.page.route('**/api/interview/start',lambda route:route.fulfill(status=503,content_type='text/html',body='Gateway unavailable'))
  self.configure();self.page.locator('#startBtn').click()
  self.page.wait_for_function('!document.querySelector("#startBtn").disabled')
  self.assertIn('历史记录',self.page.locator('#appNotice').inner_text());self.assertFalse(self.errors)
 def test_timeout_can_recover_without_automatic_retry(self):
  self.page.add_init_script('''const nativeFetch=window.fetch.bind(window),nativeTimeout=window.setTimeout.bind(window);
   window.setTimeout=function(fn,ms,...args){return nativeTimeout(fn,ms===90000?20:ms,...args)};
   window.simulatedStartCalls=0;
   window.fetch=function(input,options){const req=new Request(input,options);
    if(new URL(req.url).pathname==='/api/interview/start'){window.simulatedStartCalls++;return new Promise((resolve,reject)=>req.signal.addEventListener('abort',()=>reject(new DOMException('Timeout','AbortError'))));}
    return nativeFetch(req);};''')
  self.configure();self.page.locator('#startBtn').click()
  self.page.wait_for_function('document.querySelector("#appNotice")?.textContent.includes("超时")')
  self.assertTrue(self.page.locator('#startBtn').is_enabled())
  self.assertEqual(self.page.evaluate('simulatedStartCalls'),1);self.assertFalse(self.errors)
 def test_storage_failure_keeps_saved_record_and_does_not_redirect_loop(self):
  self.configure()
  self.page.evaluate('''(()=>{const original=Storage.prototype.setItem;
   Storage.prototype.setItem=function(key,value){if(key==='iv-session')throw new DOMException('Unavailable','QuotaExceededError');return original.call(this,key,value)};})()''')
  with patch.object(env.server,'call_deepseek',return_value='请介绍你的虚构项目') as ai:
   self.page.locator('#startBtn').click()
   self.page.wait_for_function('document.querySelector("#appNotice")?.textContent.includes("浏览器未能保存")')
   self.assertEqual(ai.call_count,1)
  self.assertEqual(self.page.url,self.base+'/');self.assertTrue(self.page.locator('#startBtn').is_enabled())
  self.assertEqual(len(env.database.list_interviews()),1);self.assertFalse(self.errors)

if __name__=='__main__':
 try:unittest.main(verbosity=2)
 finally:env.tearDownModule()
