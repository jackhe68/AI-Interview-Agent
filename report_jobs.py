"""Persistent single-worker report queue. Leases recover abandoned work on revisit."""
import json
import threading
import time
import uuid


class ReportJobs:
    LEASE = 90

    def __init__(self, db, app, generate):
        self.db, self.app, self.generate = db, app, generate
        self.lock = threading.Lock()
        self.thread = None
        with db.get_conn() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS report_jobs (
                interview_id TEXT PRIMARY KEY REFERENCES interviews(id) ON DELETE CASCADE,
                state TEXT NOT NULL, token TEXT, lease_until REAL NOT NULL DEFAULT 0,
                subjects TEXT NOT NULL DEFAULT '[]', error TEXT NOT NULL DEFAULT '',
                updated_at REAL NOT NULL)''')

    def ensure(self, sid, subjects=(), retry=False):
        now = time.time()
        with self.db.get_conn() as conn:
            conn.execute("INSERT OR IGNORE INTO report_jobs(interview_id,state,subjects,updated_at) VALUES (?,'pending',?,?)",
                         (sid, json.dumps(subjects), now))
            if retry:
                conn.execute("UPDATE report_jobs SET state='pending', error='', subjects=?, updated_at=? WHERE interview_id=? AND state='failed'",
                             (json.dumps(subjects), now, sid))
        self.start()
        return self.status(sid)

    def status(self, sid):
        with self.db.get_conn() as conn:
            row = conn.execute('SELECT state,error,lease_until FROM report_jobs WHERE interview_id=?', (sid,)).fetchone()
        return dict(row) if row else None

    def start(self):
        with self.lock:
            if self.thread is None or not self.thread.is_alive():
                self.thread = threading.Thread(target=self.run, daemon=True, name='report-jobs')
                self.thread.start()

    def claim(self):
        now = time.time()
        with self.db.get_conn() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute("SELECT interview_id,subjects FROM report_jobs WHERE state='pending' OR (state='running' AND lease_until<?) ORDER BY updated_at LIMIT 1", (now,)).fetchone()
            if not row:
                return None
            token = uuid.uuid4().hex
            conn.execute("UPDATE report_jobs SET state='running', token=?,lease_until=?,updated_at=? WHERE interview_id=?", (token, now+self.LEASE, now, row['interview_id']))
            return dict(row), token

    def heartbeat(self, sid, token, stop):
        while not stop.wait(10):
            try:
                with self.db.get_conn() as conn:
                    conn.execute("UPDATE report_jobs SET lease_until=? WHERE interview_id=? AND token=? AND state='running'", (time.time()+self.LEASE, sid, token))
            except Exception:
                self.app.logger.warning('Report heartbeat unavailable')

    def run(self):
        # Idle workers exit; a later report visit restarts them and recovers leases.
        idle = 0
        while idle < 120:
            try:
                claimed = self.claim()
                if not claimed:
                    idle += 1
                    time.sleep(1)
                    continue
                idle = 0
                job, token = claimed
                sid = job['interview_id']
                stop = threading.Event()
                pulse = threading.Thread(target=self.heartbeat, args=(sid,token,stop), daemon=True)
                pulse.start()
                error = ''
                try:
                    from flask import g
                    with self.app.test_request_context('/internal/report-job'):
                        g.report_subjects = json.loads(job['subjects'])
                        self.generate(sid)
                except Exception as exc:
                    error = getattr(exc, 'message', '报告暂时生成失败，请稍后点击重试；面试记录已保留。')
                    self.app.logger.warning('Report job failed (%s)', type(exc).__name__)
                finally:
                    stop.set()
                    pulse.join(timeout=1)
                with self.db.get_conn() as conn:
                    conn.execute('UPDATE report_jobs SET state=?,error=?,lease_until=0,updated_at=? WHERE interview_id=? AND token=?',
                                 ('failed' if error else 'done',error,time.time(),sid,token))
            except Exception:
                self.app.logger.warning('Report worker temporarily unavailable')
                time.sleep(2)
