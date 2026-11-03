"""Final UI checks: real routes/Edge, fictional data and an AI contract double only."""
import copy,json,os,sys,threading,time,unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server
from pypdf import PdfReader
sys.path.insert(0,str(Path(__file__).parent))
import test_speech42 as env
from score_fixture import with_evidence
from test_practice_value import GRADE

app=env.server.app
app.config.update(SECURITY_TEST_BYPASS=False,APP_INSECURE=True,SESSION_COOKIE_SECURE=False,AUTH_RATE_LIMIT=1000,REPORT_JOBS_INLINE=False)
OUT=Path(os.environ.get('TEST_ARTIFACT_DIR',str(Path(__file__).parents[1]/'.test-artifacts/final-ui')))
OUT.mkdir(parents=True,exist_ok=True)
LONG='反馈起始唯一标记：先明确目标、约束和个人职责。\n'+('\n'.join('第%d步：结合订单接口说明分析、验证和取舍，补充能核对的结果。'%i for i in range(1,16)))+'\n反馈末尾唯一标记：用结果验证改进。'
release=threading.Event();release.set();entered=threading.Event();grade_calls=[];fail_grade=[False]
def provider(messages,**kwargs):
    if 'knowledge_score' in messages[-1]['content']:
        grade_calls.append(1);entered.set()
        if not release.wait(30):raise env.server.APIError(504,'虚构服务等待超时')
        if fail_grade[0]:raise env.server.APIError(504,'虚构服务超时，请手动重试')
        result=with_evidence(GRADE,messages)
        anchor=result['radar_dimensions'][0]
        for key in ('problem_analysis','practical_application','examples','reflection'):
            result['radar_dimensions'].append(dict(key=key,score=65,answer_sequence=anchor['answer_sequence'],evidence=anchor['evidence'],reason='虚构契约评分说明'))
        return json.dumps(result)
    if len(messages)==2 and '请开始面试' in messages[-1]['content']:return '请介绍你负责的订单接口项目。'
    return json.dumps(dict(comment=LONG,next_question='请说明订单接口的验证过程。',answer_outline=['职责','分析','验证结果'],reference_answer='结合自己的订单接口项目，说明职责、验证方法与结果。'))
env.server.call_deepseek=provider

class FinalUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http=make_server('127.0.0.1',0,app,threaded=True)
        cls.thread=threading.Thread(target=cls.http.serve_forever,daemon=True);cls.thread.start()
        cls.base='http://127.0.0.1:'+str(cls.http.server_port)
        cls.pw=sync_playwright().start()
        cls.browser=cls.pw.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True)
    @classmethod
    def tearDownClass(cls):
        release.set();cls.browser.close();cls.pw.stop();cls.http.shutdown();cls.thread.join(3)
    def setUp(self):
        release.set();entered.clear();fail_grade[0]=False
        self.contexts=[]
    def tearDown(self):
        release.set()
        for ctx in self.contexts:ctx.close()
    def page(self,width=390):
        ctx=self.browser.new_context(viewport=dict(width=width,height=900),reduced_motion='reduce');self.contexts.append(ctx)
        page=ctx.new_page();page.set_default_timeout(12000);page.goto(self.base,wait_until='networkidle');page.evaluate('Account.ready')
        return page
    def api(self,page,path,method='GET',body=None):
        return page.evaluate('''async p=>{const r=await fetch(p.path,{method:p.method,headers:{'Content-Type':'application/json'},body:p.body===null?undefined:JSON.stringify(p.body)});return {status:r.status,data:await r.json()}}''',dict(path=path,method=method,body=body))
    def start(self,page):
        result=self.api(page,'/api/interview/start','POST',dict(job='Java 后端',level='校招标准'))
        self.assertEqual(result['status'],200);session=result['data']
        page.evaluate('s=>localStorage.setItem("iv-session",JSON.stringify(s))',session)
        return session['session_id']
    def state(self,page,sid):return self.api(page,'/api/interview/'+sid+'/state')['data']
    def answer(self,page,sid,skip=False):
        result=self.api(page,'/api/interview/answer','POST',dict(session_id=sid,answer=env.server.SKIP_ANSWER if skip else '我负责订单接口，使用事务控制一致性，并比较并发测试前后的结果。'))
        self.assertEqual(result['status'],200);return result['data']
    def interview(self,page):page.goto(self.base+'/interview',wait_until='networkidle');page.wait_for_function('document.querySelector("#questionText").textContent.includes("订单接口")')
    def shot(self,page,name):
        page.evaluate('scrollTo(0,0)');page.screenshot(path=str(OUT/(name+'.png')),full_page=True)
    def layout(self,page):
        self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
        self.assertTrue(page.locator('#aiFeedback').evaluate('(e)=>e.scrollWidth<=e.clientWidth'))
    def test_feedback_expands_one_text_area(self):
        for width in (1280,390):
            page=self.page(width);sid=self.start(page);self.answer(page,sid);self.interview(page)
            original=self.state(page,sid)['comment']
            card=page.locator('#aiFeedback');body=page.locator('#feedbackBody');summary=page.locator('#feedbackSummary')
            self.assertFalse(card.evaluate('(e)=>e.open'));self.shot(page,'feedback-collapsed-'+str(width))
            collapsed=body.bounding_box()['height'];summary.click()
            self.assertTrue(card.evaluate('(e)=>e.open'));self.assertEqual(body.text_content(),original)
            self.assertEqual(card.inner_text().count('反馈起始唯一标记'),1)
            self.assertEqual(page.locator('#feedbackTag').inner_text(),'收起详情')
            self.assertGreater(body.bounding_box()['height'],collapsed)
            self.layout(page);self.shot(page,'feedback-expanded-'+str(width))
            tag=page.locator('#feedbackTag').bounding_box();text=body.bounding_box()
            self.assertLessEqual(tag['y']+tag['height'],text['y']+1)
            summary.focus();page.keyboard.press('Enter')
            self.assertFalse(card.evaluate('(e)=>e.open'));self.assertEqual(body.text_content(),original)
            self.assertEqual(page.locator('#feedbackTag').inner_text(),'展开详情')
            self.assertAlmostEqual(body.bounding_box()['height'],collapsed,delta=1);self.layout(page)
    def capture_before(self):
        for width in (1280,390):
            page=self.page(width);sid=self.start(page);self.answer(page,sid);self.interview(page)
            self.shot(page,'before-feedback-collapsed-'+str(width));page.locator('#feedbackSummary').click();self.shot(page,'before-feedback-expanded-'+str(width))
            for _ in range(5):self.answer(page,sid)
            page.reload(wait_until='networkidle');self.shot(page,'before-completed-'+str(width))
    def test_normal_completion_refresh_report_and_pdf(self):
        for width in (1280,390):
            page=self.page(width);sid=self.start(page)
            for _ in range(5):self.answer(page,sid)
            self.interview(page);self.assertTrue(page.locator('#voiceCard').is_visible());self.assertTrue(page.locator('#answerCard').is_visible())
            last='最后回答唯一标记：我负责订单接口，使用事务控制一致性，并比较并发测试前后的结果。'
            page.locator('#answerInput').fill(last);page.locator('#submitAnswerBtn').click()
            page.wait_for_function('document.querySelector("#completionTitle").textContent==="本场面试已完成"')
            state=self.state(page,sid);self.assertTrue(state['completion']['all_answered']);self.assertEqual(state['completion']['question_count'],6)
            self.assertEqual(page.locator('#completionStatus').inner_text(),'全部问题已完成')
            self.assertEqual(page.locator('#lastAnswerText').inner_text(),last)
            question=page.locator('#questionText').inner_text();comment=page.locator('#feedbackBody').inner_text()
            self.assertIn('反馈末尾唯一标记',comment)
            for selector in ('#voiceCard','#micBtn','#answerInput','#submitAnswerBtn','#answerStage','#skipBtn','#endBtn'):
                self.assertFalse(page.locator(selector).is_visible(),selector)
            self.assertEqual(page.locator('#viewReportBtn').inner_text(),'生成并查看报告')
            self.assertEqual(page.locator('#progressTrack').get_attribute('aria-valuenow'),'100')
            page.reload(wait_until='networkidle');page.wait_for_function('!document.querySelector("#completionCard").classList.contains("is-hidden")')
            self.assertEqual(page.locator('#questionText').inner_text(),question);self.assertEqual(page.locator('#feedbackBody').inner_text(),comment)
            self.assertEqual(page.locator('#lastAnswerText').inner_text(),last);self.assertFalse(page.locator('#answerCard').is_visible())
            self.layout(page);self.shot(page,'completed-'+str(width))
            before=len(grade_calls)
            page.locator('#viewReportBtn').click();page.wait_for_url('**/report?*')
            page.wait_for_function('!document.querySelector("#reportBody").classList.contains("is-hidden")')
            page.reload(wait_until='networkidle');self.assertEqual(len(grade_calls),before+1)
            with page.expect_download() as download:page.locator('#exportBtn').click()
            pdf=Path(download.value.path()).read_bytes();(OUT/('report-'+str(width)+'.pdf')).write_bytes(pdf)
            reader=PdfReader(BytesIO(pdf));text=''.join(p.extract_text() for p in reader.pages);compact=''.join(text.split())
            for expected in ('八维能力分析','专业知识','回答完整性','逻辑表达','岗位相关性','问题分析','实践应用','举例论证','复盘改进','反馈末尾唯一标记','最后回答唯一标记'):
                self.assertIn(expected,compact)
            self.shot(page,'report-'+str(width));self.interview(page)
            page.wait_for_function('document.querySelector("#viewReportBtn").textContent==="查看面试报告"')
    def test_partial_skipped_and_manual_end_have_accurate_states(self):
        page=self.page();sid=self.start(page);self.answer(page,sid);self.interview(page)
        page.evaluate('const s=JSON.parse(localStorage.getItem("iv-session"));s.finished=true;localStorage.setItem("iv-session",JSON.stringify(s))')
        page.reload(wait_until='networkidle')
        self.assertTrue(page.locator('#answerCard').is_visible());self.assertTrue(page.locator('#voiceCard').is_visible());self.assertFalse(page.locator('#completionCard').is_visible())
        self.assertEqual(self.state(page,sid)['completion']['kind'],'active');self.shot(page,'unfinished-390')
        page.locator('#answerInput').fill('刷新后继续回答，补充验证结果。');page.locator('#submitAnswerBtn').click()
        page.wait_for_function('document.querySelector("#answeredCount").textContent==="2"')
        self.answer(page,sid,True)
        for _ in range(3):self.answer(page,sid)
        self.assertEqual(self.state(page,sid)['completion']['kind'],'skipped');self.assertFalse(self.state(page,sid)['completion']['all_answered'])
        page.reload(wait_until='networkidle');self.assertIn('跳过了1个问题',page.locator('#completionDescription').inner_text());self.assertNotIn('已完成全部作答',page.locator('#completionCard').inner_text());self.shot(page,'skipped-390')
        other=self.page();early=self.start(other);self.answer(other,early)
        self.assertEqual(self.api(other,'/api/interview/end','POST',dict(session_id=early))['status'],200)
        self.interview(other);self.assertEqual(self.state(other,early)['completion']['kind'],'ended')
        self.assertNotIn('已完成全部作答',other.locator('#completionCard').inner_text());self.assertNotEqual(other.locator('#progressTrack').get_attribute('aria-valuenow'),'100')
        self.assertFalse(other.locator('#answerCard').is_visible());self.shot(other,'ended-390')
    def test_report_running_ready_failed_and_interrupted(self):
        page=self.page();sid=self.start(page)
        for _ in range(6):self.answer(page,sid)
        before=len(grade_calls);release.clear();entered.clear()
        try:
            self.assertEqual(self.api(page,'/api/report/'+sid)['status'],202);self.assertTrue(entered.wait(3))
            for _ in range(2):self.assertEqual(self.api(page,'/api/report/'+sid)['status'],202)
            self.interview(page);button=page.locator('#viewReportBtn')
            self.assertEqual(button.inner_text(),'报告生成中');self.assertTrue(button.is_disabled());self.shot(page,'report-generating-390')
            page.locator('#feedbackSummary').click();page.wait_for_timeout(2700)
            self.assertFalse(page.locator('#aiFeedback').evaluate('(e)=>e.open'));self.assertTrue(button.is_disabled())
            self.assertEqual(len(grade_calls),before+1)
        finally:release.set()
        page.wait_for_function('document.querySelector("#viewReportBtn").textContent==="查看面试报告"',timeout=12000)
        self.assertTrue(button.is_enabled());self.assertEqual(len(grade_calls),before+1)
        failed=self.start(page)
        for _ in range(6):self.answer(page,failed)
        fail_grade[0]=True;self.api(page,'/api/report/'+failed)
        end=time.monotonic()+5
        while self.state(page,failed)['report_state']!='failed' and time.monotonic()<end:time.sleep(.05)
        self.interview(page);self.assertIn('报告生成失败',page.locator('#completionReportHint').inner_text());self.assertTrue(button.is_enabled());self.shot(page,'report-failed-390')
        calls=len(grade_calls);page.wait_for_timeout(2700);self.assertEqual(len(grade_calls),calls)
        # Simulate a restarted process, without letting the live test worker reclaim this task.
        with env.database.get_conn() as conn:conn.execute("UPDATE report_jobs SET state='running',lease_until=? WHERE interview_id=?",(time.time()+90,failed))
        with patch.object(env.server,'REPORT_JOB_SERVICE',None):
            page.reload(wait_until='networkidle');self.assertIn('处理中断',page.locator('#completionReportHint').inner_text());self.assertTrue(button.is_enabled())
    def test_finished_api_rejects_new_answers_and_inconsistent_records(self):
        page=self.page();sid=self.start(page)
        for _ in range(6):self.answer(page,sid)
        count=len(env.database.get_messages(sid));calls=len(grade_calls)
        self.assertEqual(self.api(page,'/api/interview/answer','POST',dict(session_id=sid,answer='完成后的新回答'))['status'],409)
        env.server.SESSIONS.clear()
        self.assertEqual(self.api(page,'/api/interview/answer','POST',dict(session_id=sid,answer='重启恢复后的新回答'))['status'],409)
        self.assertEqual(len(env.database.get_messages(sid)),count);self.assertEqual(len(grade_calls),calls)
        # Status alone is insufficient: persisted question/answer coverage must agree.
        partial=self.start(page);self.answer(page,partial);env.database.finish_interview(partial,'finished')
        self.assertFalse(self.state(page,partial)['completion']['all_answered'])
        missing=self.start(page)
        for _ in range(5):self.answer(page,missing)
        env.database.finish_interview(missing,'finished')
        state=self.state(page,missing);self.assertEqual(state['completion']['unanswered'],1);self.assertFalse(state['completion']['all_answered'])
        other=self.page();self.assertEqual(self.api(other,'/api/interview/'+sid+'/state')['status'],404)

if __name__=='__main__':
    try:
        if '--capture-before' in sys.argv:
            case=FinalUITests();FinalUITests.setUpClass();case.setUp()
            try:case.capture_before()
            finally:case.tearDown();FinalUITests.tearDownClass()
        else:unittest.main(verbosity=2)
    finally:env.tearDownModule()
