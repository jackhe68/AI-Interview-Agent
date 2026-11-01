import io
import gc
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import database
TEMP = tempfile.TemporaryDirectory()
database.DB_PATH = str(Path(TEMP.name) / 'test.db')
CONNECTIONS = []
_get_conn = database.get_conn
def tracked_connection():
    connection = _get_conn()
    if threading.current_thread() is threading.main_thread():
        CONNECTIONS.append(connection)
    return connection
database.get_conn = tracked_connection
import app as server
server.app.config['REPORT_JOBS_INLINE'] = True
import speech

def tearDownModule():
    for connection in CONNECTIONS:
        connection.close()
    CONNECTIONS.clear()
    gc.collect()  # SQLite context managers commit; collection closes Windows file handles.
    TEMP.cleanup()

class SpeechTests(unittest.TestCase):
    def setUp(self):
        self.client = server.app.test_client()

    def post(self, content=b'audio', name='recording.webm'):
        return self.client.post('/api/speech/transcribe', data={'audio': (io.BytesIO(content), name)})

    def test_pages_health(self):
        for route in ['/', '/interview', '/report', '/history', '/api/health']:
            self.assertEqual(self.client.get(route).status_code, 200)

    def test_validation(self):
        self.assertEqual(self.client.post('/api/speech/transcribe').status_code, 400)
        self.assertEqual(self.post(name='bad.txt').status_code, 400)
        self.assertEqual(self.post(b'').status_code, 400)
        with patch.object(speech, 'is_available', return_value=False):
            self.assertEqual(self.post().status_code, 503)

    def test_success_and_cleanup(self):
        paths = []
        def transcribe(path):
            paths.append(path)
            self.assertEqual(Path(path).read_bytes(), b'audio')
            return '这是识别结果', 1.23
        with patch.object(speech, 'transcribe', side_effect=transcribe):
            r = self.post()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json, {'success': True, 'text': '这是识别结果', 'duration': 1.2})
        self.assertFalse(Path(paths[0]).exists())
        self.assertEqual(database.list_interviews(), [])  # 识别绝不创建面试或提交回答

    def test_failures_cleanup(self):
        for result, status in [(('', 1), 422), (RuntimeError('PRIVATE_ERROR'), 503), (ValueError('bad audio'), 502)]:
            paths = []
            def transcribe(path):
                paths.append(path)
                if isinstance(result, Exception):
                    raise result
                return result
            with patch.object(speech, 'transcribe', side_effect=transcribe):
                r = self.post()
            self.assertEqual(r.status_code, status)
            self.assertNotIn('PRIVATE_ERROR', r.get_data(as_text=True))
            self.assertFalse(Path(paths[0]).exists())

    def test_oversize(self):
        response = self.client.post('/api/speech/transcribe', data=b'x' * (26 * 1024 * 1024), content_type='application/octet-stream')
        self.assertEqual(response.status_code, 413)

if __name__ == '__main__':
    unittest.main(verbosity=2)
