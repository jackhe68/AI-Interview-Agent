import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
import test_speech42 as env
from public_test import install

env.server.app.config.update(SECRET_KEY='test-only-cookie-key', SESSION_COOKIE_SECURE=True,
                             SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax')
install(env.server.app, env.database, daily_starts=3)
BASE='https://trial.test'
HEADERS={'Origin':BASE}

class PublicTests(unittest.TestCase):
    def setUp(self):
        with env.database.get_conn() as conn:
            conn.execute('DELETE FROM interviews');conn.execute('DELETE FROM trial_limits')
        env.server.SESSIONS.clear()
        self.a=env.server.app.test_client();self.b=env.server.app.test_client()

    def start(self,client):
        with patch.object(env.server,'call_deepseek',return_value='请介绍自己'):
            return client.post('/api/interview/start',base_url=BASE,headers=HEADERS,
                               json={'job':'Java 后端','level':'标准'})

    def test_browser_isolation_and_cookie(self):
        first=self.start(self.a);self.assertEqual(first.status_code,200)
        sid=first.json['session_id']
        cookie=first.headers.get('Set-Cookie','')
        self.assertIn('Secure',cookie);self.assertIn('HttpOnly',cookie);self.assertIn('SameSite=Lax',cookie)
        self.assertEqual(self.a.get('/api/interviews',base_url=BASE).json['total'],1)
        self.assertEqual(self.b.get('/api/interviews',base_url=BASE).json['total'],0)
        for path in ['/api/report/'+sid]:
            self.assertEqual(self.b.get(path,base_url=BASE).status_code,404)
        for path in ['/api/interview/answer','/api/interview/end']:
            self.assertEqual(self.b.post(path,base_url=BASE,headers=HEADERS,json={'session_id':sid,'answer':'hello'}).status_code,404)
        self.assertEqual(self.b.delete('/api/interview/'+sid,base_url=BASE,headers=HEADERS).status_code,404)
        self.assertEqual(self.b.post('/api/report/'+sid+'/speech-review',base_url=BASE,headers=HEADERS).status_code,404)
        with patch.object(env.server,'ask_next',return_value=('点评','下一题')):
            r=self.a.post('/api/interview/answer',base_url=BASE,headers=HEADERS,json={'session_id':sid,'answer':'我会Java'})
        self.assertEqual(r.status_code,200)
        self.assertEqual(self.a.get('/api/report/'+sid,base_url=BASE).status_code,200)

    def test_old_unowned_record_hidden(self):
        env.database.create_interview('unowned-old','Old','标准')
        self.assertEqual(self.a.get('/api/interviews',base_url=BASE).json['total'],0)
        self.assertEqual(self.a.get('/api/report/unowned-old',base_url=BASE).status_code,404)

    def test_origin_check_and_daily_cap(self):
        self.assertEqual(self.a.post('/api/interview/start',base_url=BASE,json={}).status_code,403)
        self.assertEqual(self.a.post('/api/interview/start',base_url=BASE,headers={'Origin':'https://elsewhere.test'},json={}).status_code,403)
        for _ in range(3):self.assertEqual(self.start(self.a).status_code,200)
        self.assertEqual(self.start(self.b).status_code,429)

    def test_speech_owned_even_when_analysis_off(self):
        sid=self.start(self.a).json['session_id']
        def upload(client):
            return client.post('/api/speech/transcribe',base_url=BASE,headers=HEADERS,
                               data={'session_id':sid,'audio':(io.BytesIO(b'audio'),'recording.webm')})
        with patch.object(env.speech,'transcribe',return_value=('测试文字',1)):
            self.assertEqual(upload(self.b).status_code,404)
            result=upload(self.a)
            self.assertEqual(result.status_code,200)
            self.assertEqual(result.json['text'],'测试文字')
            self.assertEqual(upload(self.a).status_code,200)  # ASR slot released

    def test_repeat_end_and_headers(self):
        sid=self.start(self.a).json['session_id']
        env.database.finish_interview(sid,'ended')
        with patch.object(env.server,'generate_report',side_effect=AssertionError('no duplicate cloud call')):
            result=self.a.post('/api/interview/end',base_url=BASE,headers=HEADERS,json={'session_id':sid})
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.headers['Cache-Control'],'no-store')
        self.assertEqual(result.headers['Permissions-Policy'],'microphone=(self)')

if __name__=='__main__':
    try:unittest.main(verbosity=2)
    finally:env.tearDownModule()
