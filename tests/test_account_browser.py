"""Real browser account/guest flow against isolated DB and provider doubles."""
import json,sys,threading,os
from pathlib import Path
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server
sys.path.insert(0,str(Path(__file__).parent))
import test_speech42 as env
from score_fixture import with_evidence
app=env.server.app;app.config.update(SECURITY_TEST_BYPASS=False,APP_INSECURE=True,SESSION_COOKIE_SECURE=False,AUTH_RATE_LIMIT=1000)
prompts=[]
def provider(messages,**kwargs):
 prompts.append(json.dumps(messages,ensure_ascii=False))
 if 'knowledge_score' in messages[-1]['content']:return json.dumps(with_evidence(dict(knowledge_score=80,completeness_score=70,expression_score=90,job_relevance_score=60,weaknesses=[],suggestions=['补充结果'],overall_comment='本场练习反馈',knowledge_summary='基于已回答内容',answer_reviews=[]),messages))
 if len(messages)==2 and '请开始面试' in messages[-1]['content']:return '请介绍你负责的学习项目。'
 return json.dumps(dict(comment='请进一步说明你的职责和结果。',next_question='这个方案的取舍是什么？',next_step='补充具体案例',answer_outline=['职责','结果'],reference_answer='可结合自己的实际项目描述。',checklist=['能否说明个人职责']))
env.server.call_deepseek=provider
http=make_server('127.0.0.1',0,app,threaded=True);threading.Thread(target=http.serve_forever,daemon=True).start()
base='http://127.0.0.1:'+str(http.server_port)
ROOT=Path(__file__).resolve().parents[1]
out=Path(os.environ.get('TEST_ARTIFACT_DIR',str(ROOT/'.test-artifacts/account-screenshots'))).resolve();out.mkdir(parents=True,exist_ok=True)
def register(page,name,nick):
 page.goto(base+'/account',wait_until='networkidle');page.locator('#showRegister').click()
 form=page.locator('#registerForm');form.locator('[name=username]').fill(name);form.locator('[name=password]').fill('browser password 123');form.locator('[name=confirm_password]').fill('browser password 123')
 form.locator('[name=nickname]').fill(nick);form.locator('[name=major_id]').select_option(index=1);form.locator('[name=grade]').select_option('master-1')
 form.locator('[name=username]').focus();page.keyboard.press('Tab');assert page.evaluate('document.activeElement.name')=='password'
 form.locator('[name=confirm_password]').fill('a different password');form.locator('button').click();assert '不一致' in form.locator('[data-error=confirm_password]').inner_text()
 page.screenshot(path=str(out/('registration-'+str(page.viewport_size['width'])+'.png')),full_page=True)
 form.locator('[name=confirm_password]').fill('browser password 123');form.locator('button').click()
 page.wait_for_function('!document.querySelector("#signedAccount").hidden')
try:
 with sync_playwright() as p:
  browser=p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True)
  try:
   context=browser.new_context(viewport={'width':1280,'height':900},reduced_motion='reduce');page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   page.goto(base,wait_until='networkidle');page.locator('[data-mode=direct]').click();page.locator('.job-card').first.click();page.locator('#startBtn').click();page.get_by_role('button',name='确认开始',exact=True).click();page.wait_for_url('**/interview')
   page.wait_for_function('!document.querySelector("#submitAnswerBtn").disabled')
   guest_sid=page.evaluate("JSON.parse(localStorage.getItem('iv-session')).session_id")
   page.locator('#answerInput').fill('这是游客写到一半的回答')
   register(page,'browser_a','虚构甲同学')
   assert page.locator('#claimSection').is_visible()
   assert '1 场' in page.locator('#claimCount').inner_text()
   page.locator('#claimConfirm').check();page.locator('#claimButton').click();page.wait_for_function('document.querySelector("#accountStatus").textContent.includes("已保存 1 场")')
   form=page.locator('#profileForm');form.locator('[name=nickname]').fill('虚构甲新称呼');form.locator('[name=grade]').select_option('graduated');form.locator('button').click();page.wait_for_function('document.querySelector("#accountStatus").textContent.includes("资料已保存")')
   page.reload(wait_until='networkidle');assert page.locator('#profileForm [name=nickname]').input_value()=='虚构甲新称呼'
   page.evaluate('window.scrollTo(0,0)')
   page.screenshot(path=str(out/'profile-desktop.png'),full_page=True)
   page.goto(base+'/history',wait_until='networkidle');page.wait_for_selector('.history-row')
   assert not page.locator('#historyEmpty').is_visible()
   page.locator('.resume-interview').click();page.wait_for_url('**/interview');page.wait_for_function('!document.querySelector("#submitAnswerBtn").disabled')
   def lost_response(route):
    response=route.fetch();assert response.status==200;route.abort()
   page.route('**/api/interview/answer',lost_response,times=1)
   page.locator('#answerInput').fill('我负责订单接口，用唯一请求号保证重复请求不会创建两笔订单。');page.locator('#submitAnswerBtn').click();page.wait_for_function('document.querySelector("#answeredCount").textContent === "1"')
   assert not page.locator('#aiFeedback').get_attribute('open')
   page.context.set_offline(True);page.locator('#answerInput').fill('离线编辑的回答草稿');page.locator('#submitAnswerBtn').click();page.wait_for_timeout(400)
   assert page.locator('#answerInput').input_value()=='离线编辑的回答草稿'
   page.context.set_offline(False);page.reload(wait_until='networkidle');page.wait_for_function('!document.querySelector("#submitAnswerBtn").disabled')
   assert page.locator('#answerInput').input_value()=='离线编辑的回答草稿'
   page.locator('#endBtn').click();page.locator('#confirmEndBtn').click();page.wait_for_url('**/report?*');page.wait_for_function('!document.querySelector("#reportBody").classList.contains("is-hidden")')
   page.screenshot(path=str(out/'report-desktop.png'),full_page=True)
   page.locator('.reanswer-open').first.click();page.locator('#reanswerText').fill('新的练习稿，补充事务边界和并发测试结果。');page.locator('#saveReanswer').click();page.wait_for_function('document.querySelector("#reanswerStatus").textContent.includes("重答已保存")');page.locator('#closeReanswer').click()
   with page.expect_download():page.locator('#exportBtn').click()
   assert all('虚构甲' not in text for text in prompts)
   other=browser.new_context(viewport={'width':390,'height':844},reduced_motion='reduce');b=other.new_page();register(b,'browser_b','虚构乙同学')
   assert b.evaluate('document.documentElement.scrollWidth<=innerWidth')
   b.evaluate('window.scrollTo(0,0)')
   b.screenshot(path=str(out/'profile-mobile.png'),full_page=True)
   b.goto(base+'/history',wait_until='networkidle');b.wait_for_function('!document.querySelector("#historyEmpty").hidden')
   assert b.locator('#historyEmpty').is_visible();assert b.locator('.history-row').count()==0
   assert b.evaluate("async sid=>(await fetch('/api/interview/'+sid+'/state')).status",guest_sid)==404
   b.route('**/api/interviews',lambda route:route.abort());b.reload(wait_until='networkidle');b.wait_for_function('document.querySelector("#historyStatusText").textContent.includes("网络")')
   assert not b.locator('#historyEmpty').is_visible();b.unroute('**/api/interviews')
   b.screenshot(path=str(out/'history-error-mobile.png'),full_page=True)
   page.goto(base+'/history',wait_until='networkidle');page.wait_for_selector('.history-row');page.locator('.h-del').click();page.locator('.h-del-yes').click();page.wait_for_function('!document.querySelector("#historyEmpty").hidden');assert page.locator('.history-row').count()==0
   page.goto(base,wait_until='networkidle');page.locator('[data-mode=direct]').click();page.locator('.job-card').first.click();page.locator('#startBtn').click();page.get_by_role('button',name='确认开始',exact=True).click();page.wait_for_url('**/interview');page.wait_for_function('!document.querySelector("#submitAnswerBtn").disabled');page.locator('#answerInput').fill('退出后不能显示给别人看的草稿')
   page.set_viewport_size({'width':390,'height':844});page.evaluate('scrollTo(0,0)');page.screenshot(path=str(out/'interview-mobile.png'),full_page=True)
   page.set_viewport_size({'width':390,'height':450});page.locator('#submitAnswerBtn').scroll_into_view_if_needed();assert page.locator('#submitAnswerBtn').bounding_box()['y']<450
   assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
   logout=context.new_page();logout.goto(base+'/account',wait_until='networkidle');logout.locator('#logoutButton').click();logout.wait_for_url(base+'/')
   page.wait_for_url(base+'/');assert page.evaluate("localStorage.getItem('iv-session')") is None
   assert page.evaluate("Object.keys(localStorage).filter(k=>k.startsWith('iv-answer-draft')).length") ==0
   def login_in_browser(name,password):
    logout.goto(base+'/account',wait_until='networkidle');f=logout.locator('#loginForm');f.locator('[name=username]').fill(name);f.locator('[name=password]').fill(password);f.locator('[name=password]').press('Enter');logout.wait_for_function('!document.querySelector("#signedAccount").hidden')
   login_in_browser('browser_a','browser password 123')
   assert logout.locator('#profileForm [name=nickname]').input_value()=='虚构甲新称呼'
   assert logout.evaluate("localStorage.getItem('iv-session')") is None
   logout.locator('#logoutButton').click();logout.wait_for_url(base+'/')
   login_in_browser('browser_b','browser password 123')
   assert logout.locator('#profileForm [name=nickname]').input_value()=='虚构乙同学'
   f=logout.locator('#passwordForm');f.locator('[name=current_password]').fill('browser password 123');f.locator('[name=password]').fill('new browser password 456');f.locator('[name=confirm_password]').fill('new browser password 456');f.locator('button').click();logout.wait_for_function('document.querySelector("#accountStatus").textContent.includes("密码已更新")')
   assert b.evaluate("async()=> (await (await fetch('/api/account/session')).json()).user") is None
   logout.locator('#logoutButton').click();logout.wait_for_url(base+'/');login_in_browser('browser_b','new browser password 456')
   f=logout.locator('#deleteForm');f.locator('[name=password]').fill('new browser password 456');f.locator('[name=confirmation]').fill('注销账户');f.locator('button').click();logout.wait_for_function('!document.querySelector("#anonymousAccount").hidden')
   assert logout.evaluate("async()=> (await (await fetch('/api/account/session')).json()).user") is None
   assert not errors,errors
   print('PASS browser registration/login state, profile persistence, confirmed guest migration, scoped history, answer/report/PDF/reanswer, mobile error states and cross-tab logout isolation')
  finally:browser.close()
finally:http.shutdown()
