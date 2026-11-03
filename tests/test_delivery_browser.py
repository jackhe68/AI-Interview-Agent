"""Immediate feedback, safe rendering, cached revisits and final report transition."""
import json,sys,threading
from pathlib import Path
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server
sys.path.insert(0,str(Path(__file__).parent))
import test_speech42 as env
from score_fixture import with_evidence
env.server.app.config['REPORT_JOBS_INLINE']=False
release=threading.Event();calls=[]
def provider(*a,**k):
 calls.append(1);release.wait(40)
 return json.dumps(with_evidence(dict(knowledge_score=80,completeness_score=70,expression_score=90,job_relevance_score=60,weaknesses=[],suggestions=['结合案例'],overall_comment='请围绕实际职责与结果作答。',knowledge_summary='这是一段正常正文样式的总评摘要，用于验证长文字的阅读体验。'),messages=a[0]))
env.server.call_deepseek=provider
db=env.database;db.create_interview('delivery','Java 后端','校招标准')
for n in range(2):
 db.add_message('delivery','assistant','请介绍项目 <img src=x onerror="window.partialXSS=1">','main_question',n*3+1)
 db.add_message('delivery','user','接口开发 <script>window.partialXSS=1</script>','answer',n*3+2)
 db.add_message('delivery','assistant','请补充职责与结果。<script>window.partialXSS=1</script>','comment',n*3+3)
db.finish_interview('delivery')
http=make_server('127.0.0.1',0,env.server.app,threaded=True)
threading.Thread(target=http.serve_forever,daemon=True).start()
base='http://127.0.0.1:'+str(http.server_port)
try:
 with sync_playwright() as p:
  browser=p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True)
  try:
   page=browser.new_page(viewport={'width':390,'height':900},reduced_motion='reduce')
   page.goto(base,wait_until='networkidle');page.goto(base,wait_until='networkidle')
   resources=page.evaluate("performance.getEntriesByType('resource').filter(e=>e.name.includes('/static/')).map(e=>({name:e.name,transfer:e.transferSize}))")
   assert resources and all(item['transfer']==0 for item in resources),resources
   print('PASS second homepage visit uses locally cached versioned assets')
   page.goto(base+'/report?id=delivery',wait_until='networkidle')
   page.locator('#partialReport').wait_for(state='visible')
   assert '请补充职责与结果' in page.locator('#partialReviews').inner_text()
   assert page.locator('#partialReviews script,#partialReviews img').count()==0
   assert page.evaluate('window.partialXSS') is None
   page.wait_for_function('document.querySelector("#retryReportBtn").disabled && document.querySelector("#retryReportBtn").textContent.includes("自动更新")')
   assert not page.locator('#exportBtn').is_enabled()
   page.locator('#partialReviews details').nth(1).locator('summary').click()
   page.wait_for_timeout(2300)
   assert page.locator('#partialReviews details').nth(1).get_attribute('open') is not None
   assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
   page.evaluate('window.scrollTo(0,0)')
   page.screenshot(path=str(Path(__file__).resolve().parents[1]/'docs/delivery-wait-mobile.png'),full_page=True)
   print('PASS saved feedback is immediately visible, safely escaped and stable across polls; no false retry prompt')
   release.set()
   page.wait_for_function('!document.querySelector("#reportBody").classList.contains("is-hidden")',timeout=15000)
   assert not page.locator('#partialReport').is_visible()
   assert len(calls)==1
   page.wait_for_function('document.querySelector("#scoreNum").textContent === "77"')
   assert page.locator('#commentHead').evaluate('(node)=>getComputedStyle(node).fontSize')=='15px'
   assert page.locator('#radarNote').get_attribute('class')=='report-note'
   page.set_viewport_size({'width':1280,'height':900})
   assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
   page.screenshot(path=str(Path(__file__).resolve().parents[1]/'docs/delivery-final-desktop.png'),full_page=True)
   print('PASS final result replaces partial view, report readability on mobile/desktop, one AI request')
  finally:release.set();browser.close()
finally:http.shutdown()
