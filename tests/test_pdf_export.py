"""PDF layout, ownership, retries and real desktop/mobile downloads. Isolated data only."""
import copy
from io import BytesIO
import json
from pathlib import Path
import re
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
import test_speech42 as env
from test_practice_value import ANSWER, GRADE
from public_test import install
from report_pdf import build_report_pdf
from pypdf import PdfReader

BASE = 'https://export.test'
env.server.app.config.update(SECRET_KEY='pdf-export-tests-only', SESSION_COOKIE_SECURE=True)
install(env.server.app, env.database, daily_starts=None)


class PDFExportTests(unittest.TestCase):
    def setUp(self):
        with env.database.get_conn() as conn:
            conn.execute('DELETE FROM interviews')
        env.server.SESSIONS.clear()
        self.owner = env.server.app.test_client()
        self.other = env.server.app.test_client()
        with patch.object(env.server, 'call_deepseek', return_value='如何排查并优化慢查询？'):
            response = self.owner.post('/api/interview/start', base_url=BASE, headers={'Origin': BASE},
                                       json=dict(job='Java 后端', level='校招标准'))
        self.sid = response.json['session_id']
        env.database.add_message(self.sid, 'user', ANSWER, 'answer', 2)
        env.database.finish_interview(self.sid, 'ended')
        with patch.object(env.server, 'call_deepseek', return_value=json.dumps(GRADE)):
            env.server.generate_report(self.sid)
        self.payload, status = env.server.report_to_json(self.sid)
        self.assertEqual(status, 200)

    def get(self, client=None):
        return (client or self.owner).get('/api/report/'+self.sid+'/export', base_url=BASE)

    def test_owner_download_is_embedded_searchable_pdf_and_never_calls_ai(self):
        before = env.database.get_report(self.sid)
        with patch.object(env.server, 'call_deepseek', side_effect=AssertionError('export must never call AI')):
            response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'application/pdf')
        self.assertIn('attachment;', response.headers['Content-Disposition'])
        self.assertIn('no-store', response.headers['Cache-Control'])
        self.assertTrue(response.data.startswith(b'%PDF-'))
        reader = PdfReader(BytesIO(response.data))
        text = '\n'.join(page.extract_text() for page in reader.pages)
        compact = re.sub(r'\s+', '', text)
        for expected in ['八维能力分析', '逐题复盘与重答练习', '参考回答（供练习）',
                         '下一步怎么练', '重答后自查', '联合索引', '复盘改进']:
            self.assertIn(expected, compact)
        for i, page in enumerate(reader.pages, 1):
            self.assertIn(f'第{i}页', re.sub(r'\s+', '', page.extract_text()))
        fonts = [font.get_object() for page in reader.pages
                 for font in page['/Resources']['/Font'].get_object().values()]
        self.assertTrue(any('/FontFile2' in font['/FontDescriptor'] for font in fonts if '/FontDescriptor' in font))
        self.assertEqual(env.database.get_report(self.sid), before)

    def test_cross_browser_and_unowned_records_are_not_exportable(self):
        with patch('report_pdf.build_report_pdf', side_effect=AssertionError('not authorized')):
            self.assertEqual(self.get(self.other).status_code, 404)
            env.database.create_interview('unowned-old', 'Java 后端', '校招标准')
            self.assertEqual(self.owner.get('/api/report/unowned-old/export', base_url=BASE).status_code, 404)

    def test_missing_or_active_report_is_rejected_without_generating_scores(self):
        with env.database.get_conn() as conn:
            conn.execute('DELETE FROM reports WHERE interview_id=?', (self.sid,))
        with patch.object(env.server, 'call_deepseek', side_effect=AssertionError('no hidden scoring')):
            self.assertEqual(self.get().status_code, 409)
            env.database.update_progress(self.sid, 1, 0, 'active')
            self.assertEqual(self.get().status_code, 409)

    def test_failed_export_can_retry_without_changing_saved_report(self):
        before = env.database.get_report(self.sid)
        with patch('report_pdf.build_report_pdf', side_effect=RuntimeError('PRIVATE_RENDER_DETAILS')):
            failed = self.get()
        self.assertEqual(failed.status_code, 503)
        self.assertIn('重试', failed.json['error'])
        self.assertNotIn('PRIVATE_RENDER_DETAILS', failed.get_data(as_text=True))
        self.assertEqual(self.get().status_code, 200)
        self.assertEqual(env.database.get_report(self.sid), before)

    def test_long_answers_references_code_and_missing_dimensions_are_complete(self):
        payload = copy.deepcopy(self.payload)
        review = payload['answer_reviews'][0]
        review['answer'] = ('这是长回答，用来检查跨页后内容仍然完整。\n'*190
                            + 'if (a < b && b > 0) { return "ok"; }\n'
                            + 'token_' + 'x'*1200 + '\nEND_OF_LONG_ANSWER')
        review['reference_answer'] = '参考回答的每一段都需要完整保留。\n'*180 + 'END_OF_REFERENCE'
        review['checklist'] += ['END_OF_CHECKLIST']
        payload['radar_dimensions'][4]['score'] = 0
        payload['radar_dimensions'][5]['score'] = None
        pdf = build_report_pdf(payload)
        reader = PdfReader(BytesIO(pdf))
        self.assertGreater(len(reader.pages), 5)
        compact = re.sub(r'\s+', '', '\n'.join(page.extract_text() for page in reader.pages))
        for token in ['END_OF_LONG_ANSWER', 'END_OF_REFERENCE', 'END_OF_CHECKLIST',
                      'if(a<b&&b>0){return"ok";}', '未评估']:
            self.assertIn(token, compact)
        self.assertGreaterEqual(compact.count('这是长回答，用来检查跨页后内容仍然完整。'), 190)
        self.assertGreaterEqual(compact.count('参考回答的每一段都需要完整保留。'), 180)
        folder = Path(__file__).resolve().parents[1] / 'docs' / 'pdf-export-validation'
        folder.mkdir(exist_ok=True)
        (folder/'long-answer-test.pdf').write_bytes(pdf)

    def test_desktop_and_mobile_retries_download_actual_pdf_and_block_double_click(self):
        from playwright.sync_api import sync_playwright
        from waitress import create_server
        http = create_server(env.server.app, host='127.0.0.1', port=0, threads=4)
        worker = threading.Thread(target=http.run, daemon=True)
        worker.start()
        base = 'http://127.0.0.1:' + str(http.effective_port)
        cookie_name = env.server.app.config['SESSION_COOKIE_NAME']
        cookie = self.owner.get_cookie(cookie_name, domain='export.test').value
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)
                try:
                    for width in [1280, 390]:
                        context = browser.new_context(viewport=dict(width=width, height=900), accept_downloads=True,
                                                      is_mobile=width < 600, has_touch=width < 600)
                        context.add_cookies([dict(name=cookie_name, value=cookie, url=base, httpOnly=True, secure=False, sameSite='Lax')])
                        page = context.new_page()
                        page.set_default_timeout(15000)
                        errors = []
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        page.goto(base+'/report?id='+self.sid, wait_until='networkidle')
                        page.wait_for_function("document.querySelector('#scoreNum').textContent === '77'")
                        url = '**/api/report/'+self.sid+'/export'
                        def gateway(route):
                            route.fulfill(status=502, content_type='text/html', body='<html>gateway unavailable</html>')
                        page.route(url, gateway)
                        page.locator('#exportBtn').click()
                        page.wait_for_function("document.querySelector('#exportStatus').textContent.includes('HTTP 502')")
                        self.assertEqual(page.locator('#exportBtn').inner_text(), '重试导出 PDF')
                        self.assertTrue(page.locator('#reportBody').is_visible())
                        page.unroute(url)
                        page.route(url, lambda route: route.fulfill(status=200, content_type='application/pdf', body=b'not a pdf'))
                        page.locator('#exportBtn').click()
                        page.wait_for_function("document.querySelector('#exportStatus').textContent.includes('不是有效 PDF')")
                        page.unroute(url)
                        page.route(url, lambda route: route.abort())
                        page.locator('#exportBtn').click()
                        page.wait_for_function("document.querySelector('#exportStatus').textContent.includes('连接中断')")
                        page.unroute(url)
                        entered, release = threading.Event(), threading.Event()
                        calls = []
                        def held_export(payload):
                            calls.append(1)
                            entered.set()
                            if not release.wait(10):
                                raise RuntimeError('Export test timed out')
                            return build_report_pdf(payload)
                        with patch('report_pdf.build_report_pdf', side_effect=held_export):
                            try:
                                with page.expect_download() as pending:
                                    page.locator('#exportBtn').click()
                                    self.assertTrue(entered.wait(5))
                                    self.assertTrue(page.locator('#exportBtn').is_disabled())
                                    self.assertIn('正在生成 PDF', page.locator('#exportStatus').inner_text())
                                    page.evaluate("document.querySelector('#exportBtn').dispatchEvent(new MouseEvent('click'))")
                                    self.assertEqual(len(calls), 1)
                                    release.set()
                                download = pending.value
                                self.assertTrue(download.suggested_filename.endswith('.pdf'))
                                downloaded = Path(download.path()).read_bytes()
                                self.assertTrue(downloaded.startswith(b'%PDF-'))
                                self.assertGreater(len(PdfReader(BytesIO(downloaded)).pages), 0)
                            finally:
                                release.set()
                        page.wait_for_function("document.querySelector('#exportStatus').textContent.includes('PDF 已生成')")
                        self.assertFalse(page.locator('#exportBtn').is_disabled())
                        self.assertEqual(page.locator('#scoreNum').inner_text(), '77')
                        self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                        self.assertEqual(errors, [])
                        context.close()
                finally:
                    browser.close()
        finally:
            http.close()
            http.task_dispatcher.shutdown()
            worker.join(timeout=3)


if __name__ == '__main__':
    try:
        unittest.main(verbosity=2)
    finally:
        env.tearDownModule()
