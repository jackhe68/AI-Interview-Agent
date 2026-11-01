"""UTC output and legacy compatibility without rewriting stored timestamps."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
import test_speech42 as env
from interview_time import utc_time,display_time,parse_time

class TimeTests(unittest.TestCase):
    def setUp(self):
        with env.database.get_conn() as conn:conn.execute('DELETE FROM interviews')
        env.server.SESSIONS.clear()

    def test_offsets_and_date_boundary(self):
        self.assertEqual(utc_time('2026-11-01T19:21:00'),'2026-11-01T10:21:00Z')
        self.assertEqual(utc_time('2026-11-01T18:21:00+08:00'),'2026-11-01T10:21:00Z')
        self.assertEqual(display_time('2026-11-01T10:21:00Z'),'2026-11-01 18:21（北京时间）')
        self.assertEqual(display_time('2026-11-01T00:15:00+09:00'),'2026-10-31 23:15（北京时间）')
        self.assertEqual(display_time('invalid'),'时间未知')

    def test_new_records_are_utc(self):
        env.database.create_interview('new','Java 后端','校招标准')
        with env.database.get_conn() as conn:
            raw=conn.execute("SELECT started_at FROM interviews WHERE id='new'").fetchone()[0]
        self.assertTrue(raw.endswith('Z'));self.assertEqual(parse_time(raw).utcoffset().total_seconds(),0)

    def test_mixed_history_is_sorted_by_actual_time_without_rewrite(self):
        for sid in ['old','new']:env.database.create_interview(sid,'Java 后端','校招标准')
        with env.database.get_conn() as conn:
            conn.execute("UPDATE interviews SET started_at='2026-11-01T19:21:00' WHERE id='old'")
            conn.execute("UPDATE interviews SET started_at='2026-11-01T10:22:00Z' WHERE id='new'")
        self.assertEqual([r['id'] for r in env.database.list_interviews()],['new','old'])
        self.assertEqual(env.database.get_interview('old')['started_at'],'2026-11-01T10:21:00Z')
        with env.database.get_conn() as conn:self.assertEqual(conn.execute("SELECT started_at FROM interviews WHERE id='old'").fetchone()[0],'2026-11-01T19:21:00')

    def test_duration_handles_legacy_start_and_utc_end(self):
        env.database.create_interview('mixed','Java 后端','校招标准')
        env.database.add_message('mixed','assistant','问题','main_question',1)
        with env.database.get_conn() as conn:
            conn.execute("UPDATE interviews SET started_at='2026-11-01T19:00:00',ended_at='2026-11-01T10:05:00Z',status='ended' WHERE id='mixed'")
        response=env.server.app.test_client().get('/api/interview/mixed/state')
        self.assertEqual(response.json['elapsed_seconds'],300)
        self.assertEqual(env.server.load_session('mixed')['started_at'],parse_time('2026-11-01T10:00:00Z').timestamp())

if __name__=='__main__':unittest.main()
