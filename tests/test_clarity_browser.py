"""Interaction checks with isolated data and intercepted failures; no real AI."""
import sys,threading
from pathlib import Path
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server
sys.path.insert(0,str(Path(__file__).parent))
import test_speech42 as env
db=env.database
db.create_interview('clarity','Java 后端','校招标准')
db.add_message('clarity','assistant','你如何验证订单接口的幂等性？','followup',1)
db.update_progress('clarity',3,1)
http=make_server('127.0.0.1',0,env.server.app,threaded=True)
threading.Thread(target=http.serve_forever,daemon=True).start()
base='http://127.0.0.1:'+str(http.server_port)
try:
 with sync_playwright() as p:
  browser=p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True)
  try:
   context=browser.new_context(viewport={'width':390,'height':900},timezone_id='America/Los_Angeles',reduced_motion='reduce')
   page=context.new_page()
   page.goto(base,wait_until='networkidle')
   assert '18:21' in page.evaluate("formatInterviewTime('2026-11-01T10:21:00Z')")
   assert '18:21' in page.evaluate("formatInterviewTime('2026-11-01T19:21:00')")
   assert '北京时间' in page.evaluate("formatInterviewTime('2026-11-01T10:21:00Z')")
   page.route('**/api/interview/start',lambda route:route.fulfill(status=503,json={'error':'服务暂时繁忙，当前选择仍保留，请稍后重试。'}))
   page.locator('[data-mode="direct"]').click();page.locator('.job-card').first.click();page.locator('#startBtn').click()
   page.wait_for_function('document.querySelector("#appNotice") && !document.querySelector("#appNotice").hidden')
   page.wait_for_timeout(3100);assert page.locator('#appNotice').is_visible()
   page.locator('#appNotice button').click();assert not page.locator('#appNotice').is_visible()
   print('PASS explicit Beijing time in another browser timezone; real start failure persists and can be dismissed')
   page.evaluate("localStorage.setItem('iv-session',JSON.stringify({session_id:'clarity',job:'Java 后端',level:'校招标准',question:'恢复中',question_sequence:1,progress:{main:3,total:3,type:'followup'}}))")
   page.goto(base+'/interview',wait_until='networkidle')
   page.wait_for_function('!document.querySelector("#submitAnswerBtn").disabled')
   assert page.locator('#progressPhase').inner_text()=='追问中'
   assert page.locator('#progressTrack').get_attribute('aria-valuenow')=='83'
   assert page.locator('#questionText').get_attribute('aria-live')=='polite'
   page.get_by_label('✍️ 回答内容（可文字输入或语音转写后编辑）').fill('回答草稿仍保留')
   page.route('**/api/interview/answer',lambda route:route.fulfill(status=503,json={'error':'请稍后重试'}))
   page.locator('#submitAnswerBtn').click()
   page.wait_for_function('!document.querySelector("#submitAnswerBtn").disabled')
   assert page.locator('#progressPhase').inner_text()=='追问中'
   print('PASS main/followup progress uses all six answer stages and survives operation state changes')
   for width in [390,1280]:
    page.set_viewport_size({'width':width,'height':900})
    page.locator('#endBtn').click()
    assert page.get_by_role('dialog',name='结束本场面试？').is_visible()
    assert page.locator('#cancelEndBtn').evaluate('(node)=>node===document.activeElement')
    page.keyboard.press('Shift+Tab');assert page.locator('#confirmEndBtn').evaluate('(node)=>node===document.activeElement')
    page.keyboard.press('Tab');assert page.locator('#cancelEndBtn').evaluate('(node)=>node===document.activeElement')
    page.keyboard.press('Escape');assert not page.locator('#endModal').is_visible()
    assert page.locator('#endBtn').evaluate('(node)=>node===document.activeElement')
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
   page.route('**/api/interview/end',lambda route:route.abort())
   page.locator('#endBtn').click();page.locator('#confirmEndBtn').click()
   page.wait_for_function('document.querySelector("#endError").textContent.includes("回答已保留")')
   page.wait_for_timeout(3100);assert page.locator('#endError').is_visible()
   page.keyboard.press('Escape')
   assert page.locator('#answerInput').input_value()=='回答草稿仍保留'
   assert not page.locator('#answerInput').evaluate('(node)=>node.inert || node.closest("[inert]") !== null')
   print('PASS keyboard focus trap, Escape/return focus, persistent end failure and retained draft on mobile/desktop')
  finally:browser.close()
finally:http.shutdown()
