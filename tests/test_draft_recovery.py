"""Draft persistence and final-feedback review, using isolated SQLite and mocked AI."""
import json
from pathlib import Path
import sys
import threading
import unittest
import uuid
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parent))
import test_speech42 as env
from test_practice_value import GRADE
from score_fixture import with_evidence
from public_test import install as install_trial
from api_guard import install, RELAXED_TRIAL_LIMITS

BASE='https://draft.test';HEADERS={'Origin':BASE}
env.server.app.config.update(SECRET_KEY='draft-tests-only',SESSION_COOKIE_SECURE=True)
install_trial(env.server.app,env.database,daily_starts=None)
guard=install(env.server,env.database,limits=RELAXED_TRIAL_LIMITS)

class DraftRecoveryTests(unittest.TestCase):
    def setUp(self):
        with env.database.get_conn() as conn:conn.execute('DELETE FROM interviews')
        env.server.SESSIONS.clear();self.owner=env.server.app.test_client();self.other=env.server.app.test_client()
        self.ai_calls=0;self.grade_calls=0
        def provider(messages,max_tokens=10000):
            self.ai_calls+=1
            if 'knowledge_score' in messages[-1]['content']:
                self.grade_calls+=1;return json.dumps(with_evidence(GRADE,messages))
            if len(messages)==2:return '请介绍你解决问题的思路。'
            return json.dumps(dict(comment='本题建议：补充验证方式。',next_question='请进一步说明如何验证效果。',
                                   answer_outline=['说明目标','解释验证步骤'],reference_answer='先设定目标，再比较前后结果。'))
        self.provider=provider
        self.patch=patch.object(env.server,'call_deepseek',guard.wrap(provider,env.server.APIError));self.patch.start()
        result=self.owner.post('/api/interview/start',base_url=BASE,headers=HEADERS,json=dict(job='Java 后端',level='校招标准'))
        self.start=result.json;self.sid=self.start['session_id']

    def tearDown(self):self.patch.stop()
    def state(self):return self.owner.get('/api/interview/'+self.sid+'/state',base_url=BASE).json
    def answer(self,request_id=None,question=None,text='先定位问题，再比较处理前后的结果。'):
        data=dict(session_id=self.sid,answer=text,question_sequence=question or self.state()['question_sequence'],request_id=request_id or uuid.uuid4().hex)
        return self.owner.post('/api/interview/answer',base_url=BASE,headers=HEADERS,json=data)

    def test_retry_receipt_survives_restart_and_does_not_repeat_ai_or_answer(self):
        id=uuid.uuid4().hex;first=self.answer(id,1);self.assertEqual(first.status_code,200)
        count=self.ai_calls;env.server.SESSIONS.clear()
        again=self.answer(id,1)
        self.assertEqual(again.json,first.json);self.assertEqual(self.ai_calls,count)
        self.assertEqual(self.state()['answered_count'],1)
        self.assertEqual(self.answer(id,1,text='不同内容').status_code,409)
        self.assertEqual(self.answer(question=1).status_code,409)
        self.assertEqual(self.ai_calls,count)

    def test_atomic_failure_rolls_back_entire_turn_and_allows_retry(self):
        with env.database.get_conn() as conn:
            conn.execute("CREATE TRIGGER reject_feedback BEFORE INSERT ON messages WHEN NEW.message_type='comment' BEGIN SELECT RAISE(ABORT,'test rollback'); END")
        id=uuid.uuid4().hex
        try:self.assertEqual(self.answer(id,1).status_code,500)
        finally:
            with env.database.get_conn() as conn:conn.execute('DROP TRIGGER reject_feedback')
        self.assertEqual(self.state()['answered_count'],0)
        self.assertEqual(self.state()['question_sequence'],1)
        self.assertIsNone(env.database.get_answer_receipt(self.sid,id))
        self.assertEqual(self.answer(id,1).status_code,200)

    def test_duplicate_inflight_request_does_not_dispatch_a_second_ai_call(self):
        from concurrent.futures import ThreadPoolExecutor
        entered,release=threading.Event(),threading.Event()
        id=uuid.uuid4().hex
        data=dict(session_id=self.sid,answer='相同的回答',question_sequence=1,request_id=id)
        def held(messages,max_tokens=10000):
            entered.set()
            if not release.wait(10):raise RuntimeError('test timed out')
            return self.provider(messages,max_tokens)
        def post():
            # Separate test client with the same signed browser identity.
            client=env.server.app.test_client()
            cookie=self.owner.get_cookie(env.server.app.config['SESSION_COOKIE_NAME'],domain='draft.test')
            client.set_cookie(cookie.key,cookie.value,domain='draft.test')
            return client.post('/api/interview/answer',base_url=BASE,headers=HEADERS,json=data)
        with patch.object(env.server,'call_deepseek',guard.wrap(held,env.server.APIError)):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future=pool.submit(post)
                try:
                    self.assertTrue(entered.wait(5))
                    self.assertEqual(post().status_code,409)
                finally:release.set()
                self.assertEqual(future.result(timeout=10).status_code,200)
            self.assertEqual(post().status_code,200)
        self.assertEqual(self.state()['answered_count'],1)

    def test_state_and_receipts_are_owner_scoped_and_deleted_with_interview(self):
        self.assertEqual(self.other.get('/api/interview/'+self.sid+'/state',base_url=BASE).status_code,404)
        self.answer()
        self.assertTrue(self.state()['comment'])
        self.owner.delete('/api/interview/'+self.sid,base_url=BASE,headers=HEADERS)
        with env.database.get_conn() as conn:self.assertEqual(conn.execute('SELECT COUNT(*) FROM answer_receipts').fetchone()[0],0)

    def test_last_answer_preserves_feedback_without_generating_report(self):
        last_id=None;last_q=None
        for _ in range(6):
            last_id=uuid.uuid4().hex;last_q=self.state()['question_sequence']
            result=self.answer(last_id,last_q)
            self.assertEqual(result.status_code,200)
        self.assertTrue(result.json['finished'])
        self.assertIn('参考回答',self.state()['comment'])
        self.assertIsNone(env.database.get_report(self.sid))
        self.assertEqual(self.grade_calls,0)
        self.assertEqual(self.answer(last_id,last_q).json,result.json)

    def browser(self):
        from waitress import create_server
        http=create_server(env.server.app,host='127.0.0.1',port=0,threads=4)
        thread=threading.Thread(target=http.run,daemon=True);thread.start()
        return http,thread,'http://127.0.0.1:'+str(http.effective_port)

    def routes(self,page,lost=None,offline=None):
        def state_route(route):
            if offline and offline[0]:route.abort();return
            response=self.owner.get('/api/interview/'+self.sid+'/state',base_url=BASE)
            route.fulfill(status=response.status_code,json=response.json)
        def answer_route(route):
            if offline and offline[0]:route.abort();return
            response=self.owner.post('/api/interview/answer',base_url=BASE,headers=HEADERS,json=route.request.post_data_json)
            if lost is not None and lost[0]:lost[0]=False;route.abort()
            else:route.fulfill(status=response.status_code,json=response.json)
        page.route('**/api/interview/*/state',state_route)
        page.route('**/api/interview/answer',answer_route)
        page.route('**/api/interview/*/background',lambda route:route.fulfill(status=200,json={'active':False}))
        page.route('**/api/report/*',lambda route:route.fulfill(status=200,json=self.owner.get('/api/report/'+self.sid,base_url=BASE).json))

    def test_desktop_mobile_refresh_offline_lost_response_and_manual_report(self):
        from playwright.sync_api import sync_playwright
        http,thread,base=self.browser()
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True)
                try:
                    for width in [1280,390]:
                        if self.state()['finished']:
                            self.start=self.owner.post('/api/interview/start',base_url=BASE,headers=HEADERS,json=dict(job='Java 后端',level='校招标准')).json
                            self.sid=self.start['session_id']
                        context=browser.new_context(viewport=dict(width=width,height=900),reduced_motion='reduce')
                        page=context.new_page();page.set_default_timeout(15000)
                        page.add_init_script('if(!localStorage.getItem("iv-session"))localStorage.setItem("iv-session",'+json.dumps(json.dumps(self.start))+')')
                        lost=[False];offline=[False];self.routes(page,lost,offline)
                        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                        page.goto(base+'/interview',wait_until='networkidle')
                        page.wait_for_function("!document.querySelector('#submitAnswerBtn').disabled")
                        text='刷新后也要保留这段回答。\n还可以继续修改。'
                        page.locator('#answerInput').fill(text);page.reload(wait_until='networkidle')
                        self.assertEqual(page.locator('#answerInput').input_value(),text)
                        page.locator('#clearDraftBtn').click();self.assertEqual(page.locator('#answerInput').input_value(),'')
                        context.set_offline(True)
                        offline[0]=True
                        page.locator('#answerInput').fill('断网时输入的内容仍要保存。')
                        page.locator('#submitAnswerBtn').click()
                        page.wait_for_function("document.querySelector('#draftStatus').textContent.includes('暂未连上')")
                        self.assertEqual(self.state()['answered_count'],0)
                        context.set_offline(False);offline[0]=False;page.reload(wait_until='networkidle')
                        self.assertEqual(page.locator('#answerInput').input_value(),'断网时输入的内容仍要保存。')
                        lost[0]=True
                        page.locator('#submitAnswerBtn').click()
                        page.wait_for_function("document.querySelector('#answeredCount').textContent === '1'")
                        self.assertEqual(self.state()['answered_count'],1)
                        self.assertEqual(page.locator('#answerInput').input_value(),'')
                        page.reload(wait_until='networkidle');self.assertEqual(page.locator('#answerInput').input_value(),'')
                        # Advance elsewhere: this tab must not send its stale answer as the new question.
                        page.locator('#answerInput').fill('本页保留的旧题草稿。')
                        self.answer()
                        page.locator('#recoverStateBtn').click()
                        page.wait_for_function("document.querySelector('#answeredCount').textContent === '2'")
                        self.assertEqual(page.locator('#answerInput').input_value(),'')
                        self.assertIn('旧题草稿',page.locator('#previousDraftText').text_content())
                        while self.state()['answered_count']<5:self.answer()
                        page.reload(wait_until='networkidle')
                        page.locator('#answerInput').fill('这是最后一题的手动回答。')
                        page.locator('#submitAnswerBtn').click()
                        page.wait_for_function("!document.querySelector('#completionCard').classList.contains('is-hidden')")
                        page.wait_for_timeout(2300)
                        self.assertTrue(page.url.endswith('/interview'))
                        self.assertIn('参考回答',page.locator('#feedbackBody').inner_text())
                        self.assertEqual(self.grade_calls,0 if width==1280 else 1)
                        page.reload(wait_until='networkidle')
                        self.assertTrue(page.locator('#completionCard').is_visible())
                        self.assertIn('参考回答',page.locator('#feedbackBody').inner_text())
                        self.assertEqual(page.evaluate("Object.keys(localStorage).filter(k=>k.startsWith('iv-answer-draft-v1:')).length"),0)
                        self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
                        shot=Path(__file__).parents[1]/'docs'/f'final-review-{width}.png'
                        page.locator('#aiFeedback').screenshot(path=str(shot))
                        page.locator('#viewReportBtn').click();page.wait_for_url('**/report?*')
                        page.wait_for_function("document.querySelector('#scoreNum').textContent === '77'")
                        self.assertEqual(self.grade_calls,1 if width==1280 else 2)
                        self.assertEqual(errors,[]);context.close()
                finally:browser.close()
        finally:http.close();http.task_dispatcher.shutdown();thread.join(timeout=3)

    def test_expiry_and_unavailable_storage_have_honest_ui(self):
        from playwright.sync_api import sync_playwright
        http,thread,base=self.browser()
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True)
                try:
                    page=browser.new_page()
                    page.add_init_script('localStorage.setItem("iv-session",'+json.dumps(json.dumps(self.start))+');')
                    self.routes(page);page.goto(base+'/interview',wait_until='networkidle')
                    key='iv-answer-draft-v1:'+self.sid+':1'
                    page.evaluate('(key)=>localStorage.setItem(key,JSON.stringify({text:"过期草稿",updated_at:Date.now()-25*3600*1000}))',key)
                    page.reload(wait_until='networkidle');self.assertEqual(page.locator('#answerInput').input_value(),'')
                    page.add_init_script("const put=Storage.prototype.setItem;Storage.prototype.setItem=function(k,v){if(k.startsWith('iv-answer-draft-v1:'))throw new Error('storage unavailable');return put.call(this,k,v)}")
                    page.reload(wait_until='networkidle');page.locator('#answerInput').fill('仍可编辑，但不能声称已保存。')
                    self.assertIn('暂不能保存',page.locator('#draftStatus').inner_text())
                finally:browser.close()
        finally:http.close();http.task_dispatcher.shutdown();thread.join(timeout=3)

if __name__=='__main__':
    try:unittest.main(verbosity=2)
    finally:env.tearDownModule()
