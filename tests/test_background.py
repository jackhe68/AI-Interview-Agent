from browser_fixture_state import stub_browser_state
"""Optional background, privacy lifecycle, public ownership and mobile UI."""
import json
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import test_speech42 as env
from public_test import install as install_trial
from api_guard import install, RELAXED_TRIAL_LIMITS
from candidate_background import CONSENT_VERSION

BASE = 'https://trial.test'
HEADERS = {'Origin': BASE}
CALLS = []
PROFILE = {'major':'软件工程', 'skills':'Redis、MySQL',
           'projects':'校园二手交易平台。我负责Redis热商品缓存与MySQL持久化。', 'focus':'缓存设计'}
env.server.app.config.update(SECRET_KEY='background-test-only', SESSION_COOKIE_SECURE=True)
install_trial(env.server.app, env.database, daily_starts=None)
guard = install(env.server, env.database, limits=RELAXED_TRIAL_LIMITS)


def provider(messages, max_tokens=10000):
    CALLS.append(messages)
    if 'knowledge_score' in messages[-1]['content']:
        return json.dumps(dict(knowledge_score=80, completeness_score=70, expression_score=90,
                              job_relevance_score=60, weaknesses=[], suggestions=['结合案例'], overall_comment='测试评价'))
    if len(messages) == 2:
        return '请结合项目经历介绍自己'
    return json.dumps(dict(comment='表述清楚', next_question='请说明Redis缓存与数据库的一致性方案'))


env.server.call_deepseek = guard.wrap(provider, env.server.APIError)


class BackgroundTests(unittest.TestCase):
    def setUp(self):
        with env.database.get_conn() as conn:
            conn.execute('DELETE FROM interviews')
        env.server.SESSIONS.clear()
        CALLS.clear()
        self.a = env.server.app.test_client()
        self.b = env.server.app.test_client()

    def start(self, client=None, **extra):
        return (client or self.a).post('/api/interview/start', base_url=BASE, headers=HEADERS,
                                      json=dict(job='Java 后端', level='校招标准', **extra))

    def with_profile(self):
        response = self.start(background=PROFILE, background_consent=True)
        self.assertEqual(response.status_code, 200)
        return response.json['session_id']

    def test_skip_uses_original_prompt_and_saves_no_profile(self):
        response = self.start()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json['background_active'])
        self.assertNotIn('candidate_background', CALLS[0][0]['content'])
        with env.database.get_conn() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM interview_backgrounds').fetchone()[0], 0)

    def test_consent_type_and_size_validation_before_ai(self):
        for extra in [dict(background=PROFILE), dict(background=PROFILE, background_consent='true'),
                      dict(background=[]), dict(background={'model':'attack'}, background_consent=True),
                      dict(background={'skills':['Redis']}, background_consent=True),
                      dict(background={'projects':'x'*1501}, background_consent=True)]:
            self.assertEqual(self.start(**extra).status_code, 400)
        self.assertEqual(CALLS, [])

    def test_common_identifiers_rejected_without_echo(self):
        for value in ['手机号13800138000', '身份证号11010519491231002X', '邮箱test@example.com']:
            response = self.start(background={'resume_text':value}, background_consent=True)
            self.assertEqual(response.status_code, 400)
            self.assertNotIn(value, response.get_data(as_text=True))
        self.assertEqual(CALLS, [])

    def test_context_survives_restart_and_is_not_echoed_to_browser(self):
        sid = self.with_profile()
        self.assertIn('candidate_background', CALLS[0][0]['content'])
        self.assertIn(PROFILE['projects'], CALLS[0][0]['content'])
        with env.database.get_conn() as conn:
            row = conn.execute('SELECT * FROM interview_backgrounds WHERE interview_id=?', (sid,)).fetchone()
            self.assertEqual(row['consent_version'], CONSENT_VERSION)
            self.assertAlmostEqual(row['expires_at']-time.time(), 86400, delta=5)
        env.server.SESSIONS.clear()
        response = self.a.post('/api/interview/answer', base_url=BASE, headers=HEADERS,
                               json={'session_id':sid, 'answer':'我负责接口和缓存设计'})
        self.assertEqual(response.status_code, 200)
        self.assertIn(PROFILE['projects'], CALLS[-1][0]['content'])
        status = self.a.get('/api/interview/'+sid+'/background', base_url=BASE)
        self.assertEqual(status.json, {'active': True})
        self.assertNotIn('background', env.server.SESSIONS[sid])

    def test_owner_only_clear_and_future_prompt_without_background(self):
        sid = self.with_profile()
        path = '/api/interview/'+sid+'/background'
        self.assertEqual(self.b.get(path, base_url=BASE).status_code, 404)
        self.assertEqual(self.b.delete(path, base_url=BASE, headers=HEADERS).status_code, 404)
        self.assertEqual(self.a.delete(path, base_url=BASE, headers={'Origin':'https://other.test'}).status_code, 403)
        self.assertEqual(self.a.delete(path, base_url=BASE, headers=HEADERS).json, {'cleared':True})
        self.assertEqual(self.a.get(path, base_url=BASE).json, {'active':False})
        self.a.post('/api/interview/answer', base_url=BASE, headers=HEADERS,
                    json={'session_id':sid,'answer':'继续回答'})
        self.assertNotIn('candidate_background', CALLS[-1][0]['content'])
        self.assertTrue(env.database.get_messages(sid))

    def test_expiry_and_purge(self):
        sid = self.with_profile()
        with env.database.get_conn() as conn:
            conn.execute('UPDATE interview_backgrounds SET expires_at=?', (time.time()-1,))
        self.assertEqual(env.database.get_background(sid), {})
        with env.database.get_conn() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM interview_backgrounds').fetchone()[0], 0)
        sid = self.with_profile()
        with env.database.get_conn() as conn:
            conn.execute('UPDATE interview_backgrounds SET expires_at=?', (time.time()-1,))
        env.database.purge_expired_backgrounds()
        self.assertEqual(env.database.get_background(sid), {})

    def test_end_natural_finish_and_delete_cascade(self):
        sid = self.with_profile()
        self.a.post('/api/interview/answer', base_url=BASE, headers=HEADERS, json={'session_id':sid,'answer':'回答'})
        self.assertEqual(self.a.post('/api/interview/end', base_url=BASE, headers=HEADERS, json={'session_id':sid}).status_code, 200)
        self.assertEqual(env.database.get_background(sid), {})
        report = self.a.get('/api/report/'+sid, base_url=BASE)
        self.assertEqual(report.json['scores']['overall'], 77)
        self.assertNotIn(PROFILE['projects'], CALLS[-1][-1]['content'])
        sid = self.with_profile()
        env.database.update_progress(sid, 3, 1, 'finished')
        self.assertEqual(env.database.get_background(sid), {})
        sid = self.with_profile()
        self.assertEqual(self.a.delete('/api/interview/'+sid, base_url=BASE, headers=HEADERS).status_code, 200)
        with env.database.get_conn() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM interview_backgrounds').fetchone()[0], 0)

    def test_migration_is_additive_and_idempotent(self):
        self.with_profile()
        names = ['interviews','messages','reports','speech_analyses','interview_backgrounds']
        with env.database.get_conn() as conn:
            before = {name:[tuple(row) for row in conn.execute('SELECT * FROM '+name)] for name in names}
        env.database.init_db(); env.database.init_db()
        with env.database.get_conn() as conn:
            after = {name:[tuple(row) for row in conn.execute('SELECT * FROM '+name)] for name in names}
        self.assertEqual(before, after)

    def test_mobile_ui_opt_in_clear_and_no_browser_profile_storage(self):
        from playwright.sync_api import sync_playwright
        from waitress import create_server
        http = create_server(env.server.app, host='127.0.0.1', port=0, threads=4)
        thread = threading.Thread(target=http.run, daemon=True)
        thread.start()
        base = 'http://127.0.0.1:'+str(http.effective_port)
        sent = []
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)
                try:
                    page = browser.new_page(viewport={'width':390,'height':844})
                    stub_browser_state(page)
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    def start_route(route):
                        sent.append(route.request.post_data_json)
                        route.fulfill(status=200, json=dict(session_id='browser-test',job='Java 后端',level='校招标准',question='请介绍项目',progress=dict(main=1,total=3,type='main'),background_active=bool(sent[-1].get('background'))))
                    page.route('**/api/interview/start', start_route)
                    page.route('**/api/interview/browser-test/background', lambda route: route.fulfill(status=200,json={'cleared':True} if route.request.method=='DELETE' else {'active':bool(sent[-1].get('background'))}))
                    page.goto(base, wait_until='networkidle')
                    self.assertFalse(page.locator('#backgroundEnabled').is_checked())
                    self.assertTrue(page.locator('#backgroundFields').is_hidden())
                    page.locator('.entry-mode[data-mode="direct"]').click()
                    page.locator('.job-card[data-job="Java 后端"]').click()
                    page.locator('.seg[data-level="校招标准"]').click()
                    page.locator('#backgroundEnabled').check()
                    page.locator('#bgProjects').fill(PROFILE['projects'])
                    page.locator('#startBtn').click()
                    self.assertEqual(sent, [])
                    page.locator('#backgroundConsent').check()
                    self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth+1'))
                    page.locator('#candidateBackground').screenshot(path=str(env.ROOT/'docs/background-mobile-form.png'))
                    page.locator('#startBtn').click()
                    page.wait_for_url('**/interview')
                    self.assertEqual(sent[0]['background']['projects'], PROFILE['projects'])
                    self.assertTrue(sent[0]['background_consent'])
                    self.assertEqual(page.locator('.mock-banner').count(), 0)
                    self.assertTrue(page.locator('#backgroundSession').is_visible())
                    self.assertNotIn(PROFILE['projects'], page.evaluate('JSON.stringify(localStorage)+JSON.stringify(sessionStorage)'))
                    self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth+1'))
                    page.screenshot(path=str(env.ROOT/'docs/background-mobile-interview.png'), full_page=True)
                    page.locator('#clearSessionBackgroundBtn').click()
                    page.wait_for_function("document.querySelector('#backgroundSession').classList.contains('is-hidden')")
                    self.assertTrue(page.locator('#backgroundSession').is_hidden())
                    page.goto(base, wait_until='networkidle')
                    page.locator('#backgroundEnabled').check()
                    page.locator('#bgResume').fill('清除测试经历')
                    page.locator('#clearBackgroundBtn').click()
                    self.assertEqual(page.locator('#bgResume').input_value(), '')
                    self.assertFalse(page.locator('#backgroundEnabled').is_checked())
                    self.assertTrue(page.locator('#backgroundFields').is_hidden())
                    page.locator('#startBtn').click()
                    page.wait_for_url('**/interview')
                    self.assertNotIn('background', sent[-1])
                    self.assertTrue(page.locator('#backgroundSession').is_hidden())
                    page.route('**/api/interviews', lambda route: route.fulfill(status=200, json={'items':[
                        dict(id='browser-test',job='Java 后端',difficulty='校招标准',status='active',
                             started_at='2026-11-01T00:00:00',answered_count=0,can_view_report=False,overall_score=None)]}))
                    page.route('**/api/interview/browser-test', lambda route: route.fulfill(status=200,json={'deleted':True}))
                    page.goto(base+'/history',wait_until='networkidle')
                    page.locator('.h-del').click()
                    page.locator('.h-del-yes').click()
                    page.wait_for_function("localStorage.getItem('iv-session') === null")
                    self.assertEqual(errors, [])
                finally:
                    browser.close()
        finally:
            http.close(); http.task_dispatcher.shutdown(); thread.join(timeout=3)


if __name__ == '__main__':
    try:
        unittest.main(verbosity=2)
    finally:
        env.tearDownModule()
