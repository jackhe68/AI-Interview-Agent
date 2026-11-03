from browser_fixture_state import stub_browser_state
"""Report recovery and separate voice feedback, using only an isolated database."""
import concurrent.futures
import json
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
import test_speech42 as env
from score_fixture import with_evidence

GRADE = json.dumps(with_evidence(dict(knowledge_score=80, completeness_score=70, expression_score=90,
                       job_relevance_score=60, weaknesses=[], suggestions=['结合案例'], overall_comment='测试评价'),answer='我负责Java接口开发'))


class ReportRecoveryTests(unittest.TestCase):
    def setUp(self):
        with env.database.get_conn() as conn:
            conn.execute('DELETE FROM interviews')
        env.server.SESSIONS.clear()
        env.database.create_interview('report-test', 'Java 后端', '校招标准')
        env.database.add_message('report-test', 'assistant', '请介绍项目', 'main_question', 1)
        env.database.add_message('report-test', 'user', '我负责Java接口开发', 'answer', 2)
        self.client = env.server.app.test_client()

    def finish(self):
        env.database.finish_interview('report-test', 'ended')

    def test_end_does_not_wait_for_scoring(self):
        with patch.object(env.server, 'call_deepseek', side_effect=AssertionError('end must not call AI')):
            response = self.client.post('/api/interview/end', json={'session_id': 'report-test'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json['finished'])
        self.assertIsNone(env.database.get_report('report-test'))
        self.assertEqual(env.database.get_interview('report-test')['status'], 'ended')

    def test_saved_score_is_immediate_and_voice_advice_is_separate(self):
        self.finish()
        with patch.object(env.server, 'call_deepseek', return_value=GRADE) as ai, \
             patch.object(env.server, 'review_interview_speech', side_effect=AssertionError('must be separate')):
            first = self.client.get('/api/report/report-test')
            second = self.client.get('/api/report/report-test')
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json['scores']['overall'], 77)
        self.assertEqual(second.json['scores'], first.json['scores'])
        self.assertEqual(ai.call_count, 1)

    def test_timeout_returns_specific_error_without_hidden_retry(self):
        self.finish()
        with patch.object(env.server, 'call_deepseek', side_effect=env.server.APIError(504, 'AI 响应超时，请稍后重试')) as ai:
            failed = self.client.get('/api/report/report-test')
        self.assertEqual(failed.status_code, 504)
        self.assertIn('AI 响应超时', failed.json['error'])
        self.assertEqual(ai.call_count, 1)
        self.assertEqual(len(env.database.get_messages('report-test')), 2)
        with patch.object(env.server, 'call_deepseek', return_value=GRADE):
            self.assertTrue(self.client.get('/api/report/report-test').json['available'])

    def test_simultaneous_reads_share_one_generation(self):
        self.finish()
        entered = threading.Event()
        release = threading.Event()
        def provider(*args, **kwargs):
            entered.set()
            if not release.wait(timeout=10):
                raise RuntimeError('test timeout')
            return GRADE
        def first_read():
            with env.server.app.test_client() as client:
                response = client.get('/api/report/report-test')
                return response.status_code, response.json
        with patch.object(env.server, 'call_deepseek', side_effect=provider) as ai:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(first_read)
                try:
                    self.assertTrue(entered.wait(timeout=5))
                    pending = self.client.get('/api/report/report-test')
                    self.assertEqual(pending.status_code, 202)
                    self.assertEqual(pending.json['reason'], 'generating')
                finally:
                    release.set()
                status, result = future.result(timeout=10)
        self.assertEqual(status, 200)
        self.assertTrue(result['available'])
        self.assertEqual(ai.call_count, 1)

    def test_browser_gateway_retry_and_voice_failure_keep_scores(self):
        from playwright.sync_api import sync_playwright
        from waitress import create_server
        self.finish()
        with patch.object(env.server, 'call_deepseek', return_value=GRADE):
            payload, status = env.server.report_to_json('report-test')
        self.assertEqual(status, 200)
        payload['speech_analyses'] = [dict(id='test-analysis', question='问题', answer='回答',
                                          analysis=dict(metrics={}, quality=dict(flags=[])), feedback=None)]
        http = create_server(env.server.app, host='127.0.0.1', port=0, threads=4)
        thread = threading.Thread(target=http.run, daemon=True)
        thread.start()
        base = 'http://127.0.0.1:' + str(http.effective_port)
        calls = []
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)
                try:
                    page = browser.new_page()
                    stub_browser_state(page)
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    def report_route(route):
                        calls.append(1)
                        if len(calls) == 1:
                            route.fulfill(status=502, content_type='text/html', body='<html>gateway unavailable</html>')
                        elif len(calls) == 2:
                            route.fulfill(status=202, json={'available': False, 'reason': 'generating'})
                        else:
                            route.fulfill(status=200, json=payload)
                    page.route('**/api/report/report-test', report_route)
                    page.route('**/api/report/report-test/speech-review', lambda route: route.fulfill(status=503, json={'error': '暂不可用'}))
                    page.goto(base + '/report?id=report-test', wait_until='networkidle')
                    self.assertIn('HTTP 502', page.locator('#emptyDesc').inner_text())
                    page.locator('#retryReportBtn').click()
                    page.wait_for_function("!document.querySelector('#reportBody').classList.contains('is-hidden')")
                    page.wait_for_function("!document.querySelector('#speechReviewBtn').disabled")
                    page.wait_for_function("document.querySelector('#scoreNum').textContent === '77'")
                    self.assertTrue(page.locator('#reportBody').is_visible())
                    self.assertIn('有效语音', page.locator('#speechReport').inner_text())
                    self.assertEqual(len(calls), 3)
                    self.assertEqual(errors, [])
                    # A failed End response must preserve the draft and allow retry.
                    page.evaluate("localStorage.setItem('iv-session',JSON.stringify({session_id:'report-test',job:'Java 后端',level:'校招标准',question:'问题',progress:{main:1,total:3,type:'main'}}))")
                    page.route('**/api/interview/end', lambda route: route.fulfill(status=503, json={'error': '结束请求暂不可用，请重试'}))
                    page.goto(base + '/interview', wait_until='networkidle')
                    page.locator('#answerInput').fill('保留这段未提交的草稿')
                    page.locator('#endBtn').click()
                    page.locator('#confirmEndBtn').click()
                    page.wait_for_function("document.querySelector('#endError').textContent.includes('结束请求暂不可用')")
                    self.assertTrue(page.url.endswith('/interview'))
                    self.assertEqual(page.locator('#answerInput').input_value(), '保留这段未提交的草稿')
                    page.unroute('**/api/interview/end')
                    page.route('**/api/interview/end', lambda route: route.fulfill(status=200, json={'finished': True}))
                    page.locator('#confirmEndBtn').click()
                    page.wait_for_url('**/report?*')
                    self.assertEqual(errors, [])
                finally:
                    browser.close()
        finally:
            http.close()
            http.task_dispatcher.shutdown()
            thread.join(timeout=3)


if __name__ == '__main__':
    try:
        unittest.main(verbosity=2)
    finally:
        env.tearDownModule()
