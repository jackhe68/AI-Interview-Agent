"""Major selector, server validation, prompt continuity, reports and browser workflows."""
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).parent))
import test_speech42 as env
from interview_catalog import DISCIPLINES, MAJORS, FEATURED_JOBS, JOBS, selection_for
from public_test import install as install_trial
from api_guard import install, RELAXED_TRIAL_LIMITS
from test_practice_value import GRADE
from pypdf import PdfReader

BASE='https://majors.test'
HEADERS={'Origin':BASE}
env.server.app.config.update(SECRET_KEY='majors-tests-only',SESSION_COOKIE_SECURE=True)
install_trial(env.server.app,env.database,daily_starts=None)
guard=install(env.server,env.database,limits=RELAXED_TRIAL_LIMITS)


class MajorPathTests(unittest.TestCase):
    def setUp(self):
        with env.database.get_conn() as conn: conn.execute('DELETE FROM interviews')
        env.server.SESSIONS.clear()
        self.owner=env.server.app.test_client()
        self.other=env.server.app.test_client()
        self.calls=[]
        def provider(messages,max_tokens=10000):
            self.calls.append(messages)
            if 'knowledge_score' in messages[-1]['content']: return json.dumps(GRADE)
            if len(messages)==2: return '请介绍你对这个岗位的理解，可以用课程或练习举例。'
            return json.dumps(dict(comment='请补充具体的处理思路',next_question='遇到不同需求时，你会如何调整方案？'))
        self.mock=patch.object(env.server,'call_deepseek',guard.wrap(provider,env.server.APIError))
        self.mock.start()

    def tearDown(self):self.mock.stop()

    def start(self,job='英语教师',major_id='english',client=None):
        data=dict(job=job,level='校招标准')
        if major_id is not None:data['major_id']=major_id
        return (client or self.owner).post('/api/interview/start',base_url=BASE,headers=HEADERS,json=data)

    def test_all_44_majors_start_with_a_real_allowed_direction(self):
        self.assertEqual(len(DISCIPLINES),6)
        self.assertEqual(len(MAJORS),44)
        self.assertEqual(len(JOBS),66)
        for id,item in MAJORS.items():
            response=self.start(item['roles'][0],id)
            self.assertEqual(response.status_code,200,response.json)
            sid=response.json['session_id']
            self.assertEqual(response.json['selection']['major'],item['name'])
            self.assertEqual(env.database.get_selection(sid),selection_for(id,item['roles'][0]))
            self.assertIn(item['name'],self.calls[-1][0]['content'])

    def test_invalid_and_mismatched_selection_rejected_before_ai(self):
        for id in ['not-a-major',123,True,{},'']:
            self.assertEqual(self.start(major_id=id).status_code,400)
        self.assertEqual(self.start(job='Java 后端',major_id='english').status_code,400)
        self.assertEqual(self.calls,[])

    def test_old_direct_jobs_continue_without_a_major(self):
        for job in FEATURED_JOBS:
            result=self.start(job,None)
            self.assertEqual(result.status_code,200)
            self.assertEqual(result.json['selection'],{})

    def test_selection_survives_restart_report_pdf_history_and_delete(self):
        sid=self.start().json['session_id']
        first=self.owner.post('/api/interview/answer',base_url=BASE,headers=HEADERS,json=dict(session_id=sid,answer='我会先了解学生基础，再设定课堂目标并设计活动。'))
        self.assertEqual(first.status_code,200)
        env.server.SESSIONS.clear()
        second=self.owner.post('/api/interview/answer',base_url=BASE,headers=HEADERS,json=dict(session_id=sid,answer='我会根据学习反馈调整活动，并检查学生能否用出所学内容。'))
        self.assertEqual(second.status_code,200)
        self.assertIn('英语',self.calls[-1][0]['content'])
        self.assertIn('英语教师',self.calls[-1][0]['content'])
        self.owner.post('/api/interview/end',base_url=BASE,headers=HEADERS,json=dict(session_id=sid))
        report=self.owner.get('/api/report/'+sid,base_url=BASE)
        self.assertEqual(report.json['interview']['selection']['major'],'英语')
        history=self.owner.get('/api/interviews',base_url=BASE).json
        self.assertEqual(history['items'][0]['selection']['major'],'英语')
        pdf=self.owner.get('/api/report/'+sid+'/export',base_url=BASE)
        self.assertEqual(pdf.status_code,200)
        text=''.join(p.extract_text() for p in PdfReader(BytesIO(pdf.data)).pages)
        self.assertIn('练习方向',text)
        self.assertIn('英语',text)
        self.assertEqual(self.other.get('/api/report/'+sid,base_url=BASE).status_code,404)
        self.owner.delete('/api/interview/'+sid,base_url=BASE,headers=HEADERS)
        self.assertEqual(env.database.get_selection(sid),{})

    def test_migration_is_additive_and_idempotent(self):
        self.start()
        with env.database.get_conn() as conn:
            before={name:[tuple(r) for r in conn.execute('SELECT * FROM '+name)] for name in ('interviews','messages','interview_selections')}
        env.database.init_db();env.database.init_db()
        with env.database.get_conn() as conn:
            after={name:[tuple(r) for r in conn.execute('SELECT * FROM '+name)] for name in before}
        self.assertEqual(before,after)

    def test_desktop_and_mobile_selection_replay_search_and_old_entry(self):
        from playwright.sync_api import sync_playwright
        from waitress import create_server
        http=create_server(env.server.app,host='127.0.0.1',port=0,threads=4)
        thread=threading.Thread(target=http.run,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(http.effective_port)
        sent=[]
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True)
                try:
                    for width in [1280,390]:
                        context=browser.new_context(viewport=dict(width=width,height=900),reduced_motion='reduce')
                        page=context.new_page(); page.set_default_timeout(20000)
                        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                        def start_route(route):
                            data=route.request.post_data_json;sent.append(data)
                            r=self.owner.post('/api/interview/start',base_url=BASE,headers=HEADERS,json=data)
                            route.fulfill(status=r.status_code,json=r.json)
                        def report_route(route):
                            sid=route.request.url.split('/api/report/')[1]
                            r=self.owner.get('/api/report/'+sid,base_url=BASE)
                            route.fulfill(status=r.status_code,json=r.json)
                        page.route('**/api/interview/start',start_route)
                        page.route('**/api/interview/*/state',lambda route:route.fulfill(status=200,json=self.owner.get('/api/interview/'+route.request.url.split('/api/interview/')[1].split('/')[0]+'/state',base_url=BASE).json))
                        page.route('**/api/report/*',report_route)
                        page.route('**/api/interview/*/background',lambda route:route.fulfill(status=200,json={'active':False}))
                        page.goto(base,wait_until='networkidle')
                        self.assertEqual(page.locator('.discipline-option').count(),6)
                        self.assertTrue(page.locator('#startBtn').is_disabled())
                        page.locator('[data-discipline="literature"]').click()
                        self.assertEqual(page.locator('#majorSelect option').count(),20)
                        page.locator('#majorSelect').select_option('english')
                        page.locator('[data-job="英语教师"]').click()
                        page.locator('[data-level="校招标准"]').click()
                        self.assertIn('英语教师',page.locator('#summaryText').inner_text())
                        self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                        target=os.getenv('MAJOR_PREVIEW_OUTPUT')
                        if target:
                            folder=Path(target);folder.mkdir(parents=True,exist_ok=True)
                            page.evaluate('window.scrollTo(0,0)')
                            page.screenshot(path=str(folder/('homepage-majors-desktop.png' if width==1280 else 'homepage-majors-mobile.png')),full_page=True)
                        page.locator('#startBtn').click();page.wait_for_url('**/interview')
                        self.assertEqual(sent[-1]['major_id'],'english')
                        self.assertNotIn('background',sent[-1])
                        self.assertIn('英语',page.locator('#jobBadge').inner_text())
                        saved=page.evaluate('JSON.parse(localStorage.getItem("iv-config"))')
                        self.assertEqual(saved['major_id'],'english')
                        sid=page.evaluate('JSON.parse(localStorage.getItem("iv-session")).session_id')
                        self.owner.post('/api/interview/answer',base_url=BASE,headers=HEADERS,json=dict(session_id=sid,answer='先了解学习基础，再设定课堂目标。'))
                        self.owner.post('/api/interview/end',base_url=BASE,headers=HEADERS,json=dict(session_id=sid))
                        page.goto(base+'/report?id='+sid,wait_until='networkidle')
                        self.assertIn('专业：英语',page.locator('#reportMeta').inner_text())
                        page.locator('#replaySameBtn').click();page.wait_for_url('**/interview')
                        self.assertEqual(sent[-1]['major_id'],'english')
                        page.goto(base,wait_until='networkidle')
                        self.assertEqual(page.locator('#majorSelect').input_value(),'english')
                        page.locator('#majorSearch').fill('日语')
                        self.assertTrue(page.locator('#startBtn').is_disabled())
                        page.locator('#majorSelect').select_option('japanese')
                        self.assertEqual(page.locator('#jobGrid .job-card').count(),3)
                        page.locator('[data-discipline="engineering"]').click()
                        self.assertEqual(page.locator('#jobGrid .job-card').count(),0)
                        self.assertTrue(page.locator('#startBtn').is_disabled())
                        page.locator('#majorSelect').select_option('software-engineering')
                        self.assertEqual(page.locator('#jobGrid .job-card').count(),3)
                        page.locator('[data-mode="direct"]').click()
                        self.assertTrue(page.locator('#majorPath').is_hidden())
                        self.assertEqual(page.locator('#jobGrid .job-card').count(),6)
                        page.locator('[data-job="Java 后端"]').click()
                        page.locator('#startBtn').click();page.wait_for_url('**/interview')
                        self.assertNotIn('major_id',sent[-1])
                        self.assertEqual(errors,[])
                        context.close()
                finally:browser.close()
        finally:
            http.close();http.task_dispatcher.shutdown();thread.join(timeout=3)


if __name__=='__main__':
    try:unittest.main(verbosity=2)
    finally:env.tearDownModule()
