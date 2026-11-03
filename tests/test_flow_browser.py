"""End-to-end browser checks against the real queue and isolated Flask app."""
import json
import sys
import threading
from pathlib import Path
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server
sys.path.insert(0,str(Path(__file__).parent))
import test_speech42 as env
from score_fixture import with_evidence

env.server.app.config['REPORT_JOBS_INLINE']=False
release=threading.Event();calls=[];failed_once=False
def messages_text(args):return str(args)
def provider(*args,**kwargs):
    global failed_once
    calls.append(1);release.wait(15)
    if 'retry-case' in messages_text(args) and not failed_once:
        failed_once=True
        raise env.server.APIError(504,'AI 响应超时，请稍后重试')
    return json.dumps(with_evidence(dict(knowledge_score=80,completeness_score=70,expression_score=90,job_relevance_score=60,weaknesses=[],suggestions=['结合案例'],overall_comment='浏览器隔离测试'),messages=args[0]))
env.server.call_deepseek=provider
db=env.database
for sid in ['unfinished','finished','retry']:
    db.create_interview(sid,'Java 后端','校招标准')
    db.add_message(sid,'assistant','请介绍你的项目','main_question',1)
db.add_message('finished','user','我负责订单接口','answer',2)
db.finish_interview('finished')
db.add_message('retry','user','retry-case','answer',2)
db.finish_interview('retry')
http=make_server('127.0.0.1',0,env.server.app,threaded=True)
threading.Thread(target=http.serve_forever,daemon=True).start()
base='http://127.0.0.1:'+str(http.server_port)
try:
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True)
        try:
            page=browser.new_page(viewport={'width':390,'height':900},reduced_motion='reduce')
            page.goto(base,wait_until='networkidle')
            for width in [375,390,412]:
                page.set_viewport_size({'width':width,'height':900})
                page.locator('.nav-toggle').click()
                assert page.locator('.nav__links a[href="/history"]').is_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.keyboard.press('Escape')
                assert page.locator('.nav-toggle').get_attribute('aria-expanded')=='false'
            page.wait_for_function('!document.querySelector("#resumeBanner").hidden')
            page.evaluate("localStorage.setItem('iv-answer-draft-v1:unfinished:1',JSON.stringify({text:'我还没写完的回答',updated_at:Date.now(),pending:null}))")
            page.locator('#resumeLatest').click();page.wait_for_url('**/interview')
            page.wait_for_function('document.querySelector("#answerInput").value.includes("没写完")')
            assert page.locator('#questionText').inner_text()=='请介绍你的项目'
            page.goto(base+'/history',wait_until='networkidle')
            page.locator('.resume-interview[data-session="unfinished"]').click();page.wait_for_url('**/interview')
            page.wait_for_function('document.querySelector("#answerInput").value.includes("没写完")')
            print('PASS phone menu, homepage resume, history resume and existing draft preservation')
            page.goto(base+'/report?id=finished',wait_until='networkidle')
            page.wait_for_function('document.querySelector("#reportEmpty").textContent.includes("报告正在生成") || document.querySelector("#reportEmpty").textContent.includes("报告已排队")')
            page.goto(base+'/history',wait_until='networkidle')
            release.set()
            page.goto(base+'/report?id=finished',wait_until='networkidle')
            page.wait_for_function('document.querySelector("#scoreNum").textContent === "77"',timeout=15000)
            page.reload(wait_until='networkidle')
            page.wait_for_function('document.querySelector("#scoreNum").textContent === "77"')
            assert len(calls)==1
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            print('PASS background report survives navigation, reload uses saved result, one model call')
            page.goto(base+'/report?id=retry',wait_until='networkidle')
            page.wait_for_function('document.querySelector("#reportEmpty").textContent.includes("AI 响应超时")',timeout=15000)
            count=len(calls)
            page.wait_for_timeout(2300)
            assert len(calls)==count
            page.locator('#retryReportBtn').click()
            page.wait_for_function('document.querySelector("#scoreNum").textContent === "77"',timeout=15000)
            assert len(calls)==count+1
            print('PASS failure remains readable without automatic calls; manual retry generates one report')
            page.set_viewport_size({'width':1280,'height':900})
            assert page.locator('.nav__links a[href="/history"]').is_visible()
            assert not page.locator('.nav-toggle').is_visible()
            print('PASS desktop navigation remains visible')
        finally:release.set();browser.close()
finally:http.shutdown()
