"""Final UI checks: real routes/Edge, fictional data and an AI contract double only."""
import copy,json,os,sys,threading,time,unittest
from io import BytesIO
from pathlib import Path
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

if __name__=='__main__':
    try:
        if '--capture-before' in sys.argv:
            case=FinalUITests();FinalUITests.setUpClass();case.setUp()
            try:case.capture_before()
            finally:case.tearDown();FinalUITests.tearDownClass()
        else:unittest.main(verbosity=2)
    finally:env.tearDownModule()
