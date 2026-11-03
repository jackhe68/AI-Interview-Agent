"""Temporary trial quotas are disabled without exposing other users' records."""
import concurrent.futures
import json
import sys
import threading
import time
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
import test_speech42 as env
from score_fixture import with_evidence
from public_test import install as install_trial
from api_guard import install, RELAXED_TRIAL_LIMITS

BASE = 'https://trial.test'
HEADERS = {'Origin': BASE}
env.server.app.config.update(SECRET_KEY='relaxed-test-only', SESSION_COOKIE_SECURE=True)
install_trial(env.server.app, env.database, daily_starts=None)
guard = install(env.server, env.database, limits=RELAXED_TRIAL_LIMITS)


def provider(messages, max_tokens=10000):
    if 'knowledge_score' in messages[-1]['content']:
        return json.dumps(with_evidence(dict(knowledge_score=80, completeness_score=70,
                              expression_score=90, job_relevance_score=60,
                              weaknesses=[], suggestions=['建议'], overall_comment='总评'),messages))
    if len(messages) == 2:
        return '请介绍你的项目经历'
    return json.dumps(dict(comment='回答清楚', next_question='请说明项目难点'))


env.server.call_deepseek = guard.wrap(provider, env.server.APIError)


class RelaxedTrialTests(unittest.TestCase):
    def setUp(self):
        with env.database.get_conn() as conn:
            conn.execute('DELETE FROM interviews')
            conn.execute('DELETE FROM trial_limits')
            conn.execute('DELETE FROM trial_api_usage')
        env.server.SESSIONS.clear()
        self.client = env.server.app.test_client()

    def start(self):
        return self.client.post('/api/interview/start', base_url=BASE, headers=HEADERS,
                                json={'job': 'Java 后端', 'level': '校招标准'})

    def test_existing_high_counts_do_not_block_repeated_access(self):
        day_text = datetime.now(timezone(timedelta(hours=9))).date().isoformat()
        day = int((time.time() + 9 * 3600) // 86400)
        minute = int(time.time() // 60)
        with env.database.get_conn() as conn:
            conn.execute('INSERT INTO trial_limits VALUES (?,1000000)', (day_text,))
            for bucket, window in [('ai_day_global', day), ('http_min_global', minute)]:
                conn.execute('INSERT INTO trial_api_usage VALUES (?,?,?,1000000)',
                             (bucket, 'all', window))
        for _ in range(35):
            self.assertEqual(self.start().status_code, 200)
        for _ in range(130):
            self.assertEqual(self.client.get('/api/interviews', base_url=BASE).status_code, 200)
        with env.database.get_conn() as conn:
            self.assertEqual(conn.execute('SELECT starts FROM trial_limits').fetchone()['starts'], 1000000)
            self.assertEqual(conn.execute('SELECT COUNT(*) AS n FROM trial_api_usage').fetchone()['n'], 2)

    def test_fifty_simultaneous_ai_calls_are_accepted(self):
        self.assertEqual(RELAXED_TRIAL_LIMITS['ai_concurrent'], 1000)
        barrier = threading.Barrier(50)
        def slow_provider(messages, max_tokens):
            barrier.wait(timeout=15)
            return 'ok'
        wrapped = guard.wrap(slow_provider, env.server.APIError)
        def call(_):
            with env.server.app.test_request_context(base_url=BASE):
                return wrapped([{'role': 'system', 'content': 'test'}])
        with concurrent.futures.ThreadPoolExecutor(max_workers=50) as pool:
            self.assertEqual(list(pool.map(call, range(50))), ['ok'] * 50)

    def test_thousand_slots_reject_overflow_and_recover(self):
        acquired = 0
        try:
            for _ in range(1000):
                self.assertTrue(guard.slots.acquire(blocking=False))
                acquired += 1
            with env.server.app.test_request_context(base_url=BASE):
                with self.assertRaises(env.server.APIError) as error:
                    env.server.call_deepseek([{'role': 'system', 'content': 'test'}])
                self.assertEqual(error.exception.code, 429)
        finally:
            for _ in range(acquired):
                guard.slots.release()
        with env.server.app.test_request_context(base_url=BASE):
            self.assertEqual(env.server.call_deepseek(
                [{'role': 'system', 'content': 'test'}, {'role': 'user', 'content': 'test'}]),
                '请介绍你的项目经历')

    def test_fifty_http_starts_leave_health_available(self):
        import requests
        from waitress import create_server
        active = 0
        lock = threading.Lock()
        all_entered = threading.Event()
        release = threading.Event()
        def held_provider(messages, max_tokens):
            nonlocal active
            with lock:
                active += 1
                if active == 50:
                    all_entered.set()
            if not release.wait(timeout=30):
                raise RuntimeError('Concurrent test timed out')
            return '请介绍你的项目经历'
        http = create_server(env.server.app, host='127.0.0.1', port=0,
                             threads=54)  # Exercise 50 waiting requests without 1000 test threads.
        thread = threading.Thread(target=http.run, daemon=True)
        thread.start()
        base = 'http://127.0.0.1:' + str(http.effective_port)
        def start(_):
            with requests.Session() as client:
                client.trust_env = False
                return client.post(base + '/api/interview/start',
                                   headers={'Origin': base.replace('http:', 'https:')},
                                   json={'job': 'Java 后端', 'level': '校招标准'}, timeout=40).status_code
        try:
            with patch.object(env.server, 'call_deepseek', guard.wrap(held_provider, env.server.APIError)):
                with concurrent.futures.ThreadPoolExecutor(max_workers=50) as pool:
                    futures = [pool.submit(start, i) for i in range(50)]
                    try:
                        self.assertTrue(all_entered.wait(timeout=20), '50 AI requests must enter together')
                        with requests.Session() as client:
                            client.trust_env = False
                            self.assertEqual(client.get(base + '/api/health', timeout=5).status_code, 200)
                    finally:
                        release.set()
                    self.assertEqual([f.result() for f in futures], [200] * 50)
        finally:
            release.set()
            http.close()
            http.task_dispatcher.shutdown()
            thread.join(timeout=3)

    def test_answer_end_report_and_record_isolation(self):
        sid = self.start().json['session_id']
        answer = self.client.post('/api/interview/answer', base_url=BASE, headers=HEADERS,
                                  json={'session_id': sid, 'answer': '我负责Java项目的接口开发'})
        self.assertEqual(answer.status_code, 200)
        ended = self.client.post('/api/interview/end', base_url=BASE, headers=HEADERS,
                                 json={'session_id': sid})
        self.assertEqual(ended.status_code, 200)
        report = self.client.get('/api/report/' + sid, base_url=BASE)
        self.assertEqual(report.json['scores']['overall'], 77)
        other = env.server.app.test_client()
        self.assertEqual(other.get('/api/report/' + sid, base_url=BASE).status_code, 404)
        self.assertEqual(other.get('/api/interviews', base_url=BASE).json['total'], 0)

    def test_invalid_request_and_foreign_origin_still_rejected(self):
        self.assertEqual(self.client.post('/api/interview/start', base_url=BASE,
                                          headers={'Origin': 'https://other.test'},
                                          json={'job': 'Java 后端', 'level': '校招标准'}).status_code, 403)
        self.assertEqual(self.client.post('/api/interview/start', base_url=BASE,
                                          headers=HEADERS, json={'job': 'x', 'level': 'x'}).status_code, 400)


if __name__ == '__main__':
    try:
        unittest.main(verbosity=2)
    finally:
        env.tearDownModule()
