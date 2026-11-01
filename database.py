# -*- coding: utf-8 -*-
"""
AI Interview Agent · SQLite 持久化层（第三阶段）
-------------------------------------------------
三张表：
  interviews  面试主记录
  messages    面试对话消息（问题/追问/回答/点评）
  reports     AI 评分报告
- 自动初始化（init_db 幂等）
- 全部参数化 SQL，防注入
- 外键 + 唯一约束保证关联与去重
- 异常统一捕获，向上抛出 RuntimeError（不外显堆栈给前端）
- 不存储任何 API 密钥
"""
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from interview_time import normalize_interview, timestamp

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "interviews.db")


class ManagedConnection(sqlite3.Connection):
    def execute(self, *args, **kwargs):
        started=time.perf_counter()
        try:return super().execute(*args,**kwargs)
        finally:
            from flask import has_request_context,g
            if has_request_context():g.db_ms=g.get('db_ms',0)+(time.perf_counter()-started)*1000

    def __exit__(self, exc_type, exc_value, traceback):
        started=time.perf_counter()
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()
            from flask import has_request_context,g
            if has_request_context():g.db_ms=g.get('db_ms',0)+(time.perf_counter()-started)*1000


def get_conn():
    started=time.perf_counter()
    conn = sqlite3.connect(DB_PATH, factory=ManagedConnection)
    from flask import has_request_context,g
    if has_request_context():g.db_ms=g.get('db_ms',0)+(time.perf_counter()-started)*1000
    conn.row_factory = sqlite3.Row
    conn.create_function("interview_timestamp", 1, timestamp, deterministic=True)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """幂等建表。Flask 启动时调用。"""
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS interviews (
            id              TEXT PRIMARY KEY,
            job             TEXT NOT NULL,
            difficulty      TEXT NOT NULL,
            started_at      TEXT NOT NULL,
            ended_at        TEXT,
            status          TEXT NOT NULL DEFAULT 'active',   -- active | finished | ended
            current_question INTEGER NOT NULL DEFAULT 1,
            followup_count  INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS messages (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            interview_id    TEXT NOT NULL,
            role            TEXT NOT NULL,                     -- assistant | user
            content         TEXT NOT NULL,
            message_type    TEXT NOT NULL,                     -- main_question | followup | answer | comment
            created_at      TEXT NOT NULL,
            sequence        INTEGER NOT NULL,
            UNIQUE(interview_id, sequence),
            FOREIGN KEY(interview_id) REFERENCES interviews(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS reports (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            interview_id         TEXT NOT NULL UNIQUE,
            overall_score        INTEGER NOT NULL,
            knowledge_score      INTEGER NOT NULL,
            completeness_score   INTEGER NOT NULL,
            expression_score     INTEGER NOT NULL,
            job_relevance_score  INTEGER NOT NULL,
            weaknesses           TEXT NOT NULL,                -- JSON 数组
            suggestions          TEXT NOT NULL,                -- JSON 数组
            overall_comment      TEXT NOT NULL,
            knowledge_summary    TEXT NOT NULL,
            confidence_note      TEXT NOT NULL DEFAULT '',
            detail               TEXT NOT NULL DEFAULT '{}',   -- 预留 JSON 明细
            created_at           TEXT NOT NULL,
            FOREIGN KEY(interview_id) REFERENCES interviews(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_messages_interview ON messages(interview_id);

        CREATE TABLE IF NOT EXISTS speech_analyses (
            id TEXT PRIMARY KEY,
            interview_id TEXT NOT NULL REFERENCES interviews(id) ON DELETE CASCADE,
            question_sequence INTEGER NOT NULL,
            message_id INTEGER UNIQUE REFERENCES messages(id) ON DELETE CASCADE,
            result_json TEXT NOT NULL,
            feedback_json TEXT,
            created_at TEXT NOT NULL,
            expires_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_speech_interview ON speech_analyses(interview_id);
        CREATE TABLE IF NOT EXISTS interview_backgrounds (
            interview_id TEXT PRIMARY KEY REFERENCES interviews(id) ON DELETE CASCADE,
            profile_json TEXT NOT NULL,
            consent_version TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_background_expiry ON interview_backgrounds(expires_at);
        CREATE TABLE IF NOT EXISTS interview_selections (
            interview_id TEXT PRIMARY KEY REFERENCES interviews(id) ON DELETE CASCADE,
            selection_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS answer_receipts (
            interview_id TEXT NOT NULL REFERENCES interviews(id) ON DELETE CASCADE,
            request_id TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            response_json TEXT NOT NULL,
            PRIMARY KEY(interview_id, request_id)
        );
        """)

    from account_migration import migrate
    migrate(__import__(__name__))
    from deletion_journal import replay
    replay(__import__(__name__))


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ------------------------------------------------------------------
# interviews
# ------------------------------------------------------------------
def create_interview(interview_id, job, difficulty, background=None, selection=None):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO interviews(id, job, difficulty, started_at, status) "
            "VALUES (?, ?, ?, ?, 'active')",
            (interview_id, job, difficulty, _now()),
        )
        from accounts import bind_record
        bind_record(conn, interview_id)
        if background:
            from candidate_background import CONSENT_VERSION, RETENTION_SECONDS
            conn.execute('INSERT INTO interview_backgrounds VALUES (?,?,?,?,?)',
                         (interview_id, json.dumps(background, ensure_ascii=False),
                          CONSENT_VERSION, _now(), time.time() + RETENTION_SECONDS))
        if selection:
            conn.execute('INSERT INTO interview_selections VALUES (?,?)',
                         (interview_id, json.dumps(selection, ensure_ascii=False)))


def get_selection(interview_id):
    with get_conn() as conn:
        row = conn.execute('SELECT selection_json FROM interview_selections WHERE interview_id=?',
                           (interview_id,)).fetchone()
        return json.loads(row['selection_json']) if row else {}


def get_interview(interview_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM interviews WHERE id = ?", (interview_id,)
        ).fetchone()
        return normalize_interview(row) if row else None


def update_progress(interview_id, current_question, followup_count, status=None):
    with get_conn() as conn:
        if status:
            conn.execute(
                "UPDATE interviews SET current_question=?, followup_count=?, status=? WHERE id=?",
                (current_question, followup_count, status, interview_id),
            )
        else:
            conn.execute(
                "UPDATE interviews SET current_question=?, followup_count=? WHERE id=?",
                (current_question, followup_count, interview_id),
            )
        if status in ('finished', 'ended'):
            conn.execute('DELETE FROM interview_backgrounds WHERE interview_id=?', (interview_id,))


def finish_interview(interview_id, status="finished"):
    with get_conn() as conn:
        conn.execute(
            "UPDATE interviews SET status=?, ended_at=? WHERE id=?",
            (status, _now(), interview_id),
        )
        conn.execute('DELETE FROM interview_backgrounds WHERE interview_id=?', (interview_id,))


def purge_expired_backgrounds():
    with get_conn() as conn:
        conn.execute('DELETE FROM interview_backgrounds WHERE expires_at<=?', (time.time(),))


def get_background(interview_id):
    with get_conn() as conn:
        conn.execute('DELETE FROM interview_backgrounds WHERE interview_id=? AND expires_at<=?',
                     (interview_id, time.time()))
        row = conn.execute('SELECT profile_json FROM interview_backgrounds WHERE interview_id=?',
                           (interview_id,)).fetchone()
        return json.loads(row['profile_json']) if row else {}


def clear_background(interview_id):
    with get_conn() as conn:
        conn.execute('DELETE FROM interview_backgrounds WHERE interview_id=?', (interview_id,))


# ------------------------------------------------------------------
# messages
# ------------------------------------------------------------------
def add_message(interview_id, role, content, message_type, sequence):
    """幂等：UNIQUE(interview_id, sequence) 防重复插入同一条消息。"""
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO messages(interview_id, role, content, message_type, created_at, sequence) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (interview_id, role, content, message_type, _now(), sequence),
        )


def get_messages(interview_id):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE interview_id=? ORDER BY sequence ASC",
            (interview_id,),
        ).fetchall()
        return [normalize_interview(r) for r in rows]


def next_sequence(interview_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) AS m FROM messages WHERE interview_id=?",
            (interview_id,),
        ).fetchone()
        return int(row["m"]) + 1


# ------------------------------------------------------------------
# reports
# ------------------------------------------------------------------
def save_report(report):
    """report: dict。UNIQUE(interview_id) 防重复；已存在则替换。"""
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO reports(interview_id, overall_score, knowledge_score, completeness_score,
                                expression_score, job_relevance_score, weaknesses, suggestions,
                                overall_comment, knowledge_summary, confidence_note, detail, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(interview_id) DO UPDATE SET
                overall_score=excluded.overall_score,
                knowledge_score=excluded.knowledge_score,
                completeness_score=excluded.completeness_score,
                expression_score=excluded.expression_score,
                job_relevance_score=excluded.job_relevance_score,
                weaknesses=excluded.weaknesses,
                suggestions=excluded.suggestions,
                overall_comment=excluded.overall_comment,
                knowledge_summary=excluded.knowledge_summary,
                confidence_note=excluded.confidence_note,
                detail=excluded.detail,
                created_at=excluded.created_at
            """,
            (
                report["interview_id"],
                report["overall_score"],
                report["knowledge_score"],
                report["completeness_score"],
                report["expression_score"],
                report["job_relevance_score"],
                json.dumps(report["weaknesses"], ensure_ascii=False),
                json.dumps(report["suggestions"], ensure_ascii=False),
                report["overall_comment"],
                report["knowledge_summary"],
                report.get("confidence_note", ""),
                json.dumps(report.get("detail", {}), ensure_ascii=False),
                _now(),
            ),
        )


def get_report(interview_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM reports WHERE interview_id=?", (interview_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["weaknesses"] = json.loads(d["weaknesses"]) if d["weaknesses"] else []
        d["suggestions"] = json.loads(d["suggestions"]) if d["suggestions"] else []
        d["detail"] = json.loads(d["detail"]) if d["detail"] else {}
        return d


# ------------------------------------------------------------------
# 历史列表
# ------------------------------------------------------------------
def list_interviews(limit=50):
    """按开始时间倒序返回面试列表，含综合评分与回答数（LEFT JOIN reports / messages）。"""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT i.id, i.job, i.difficulty, i.started_at, i.ended_at, i.status,
                   r.overall_score,
                   (SELECT COUNT(*) FROM messages m WHERE m.interview_id = i.id AND m.role = 'user') AS answered_count
            FROM interviews i
            LEFT JOIN reports r ON r.interview_id = i.id
            GROUP BY i.id
            ORDER BY interview_timestamp(i.started_at) DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [normalize_interview(r) for r in rows]


def delete_interview(interview_id):
    """删除一场面试及其消息、报告（外键 ON DELETE CASCADE 级联）。返回是否删除了行。"""
    from flask import has_request_context,g
    with get_conn() as conn:
        if has_request_context() and not g.get('security_bypass') and conn.execute('SELECT 1 FROM interviews WHERE id=?',(interview_id,)).fetchone():
            from deletion_journal import record
            record(__import__(__name__),[interview_id])
        cur = conn.execute("DELETE FROM interviews WHERE id = ?", (interview_id,))
        removed=cur.rowcount > 0
    from speech_temp import cleanup
    cleanup(__import__(__name__),[interview_id])
    return removed


def interview_exists(interview_id):
    with get_conn() as conn:
        row = conn.execute("SELECT 1 FROM interviews WHERE id = ?", (interview_id,)).fetchone()
        return row is not None


def current_question_sequence(conn, interview_id):
    row = conn.execute("SELECT sequence FROM messages WHERE interview_id=? AND role='assistant' "
                       "AND message_type IN ('main_question','followup') ORDER BY sequence DESC LIMIT 1",
                       (interview_id,)).fetchone()
    return row['sequence'] if row else None


def save_pending_speech(analysis_id, interview_id, question_sequence, result):
    """Only server-computed measurements; no raw audio and no client JSON accepted."""
    if result.get('status') not in ('ok', 'partial') or not isinstance(result.get('metrics'), dict):
        return False
    with get_conn() as conn:
        conn.execute('DELETE FROM speech_analyses WHERE message_id IS NULL AND expires_at<?', (time.time(),))
        iv = conn.execute('SELECT status FROM interviews WHERE id=?', (interview_id,)).fetchone()
        if not iv or iv['status'] != 'active' or current_question_sequence(conn, interview_id) != question_sequence:
            return False
        conn.execute('INSERT INTO speech_analyses(id,interview_id,question_sequence,result_json,created_at,expires_at) '
                     'VALUES (?,?,?,?,?,?)',
                     (analysis_id, interview_id, question_sequence,
                      json.dumps(result, ensure_ascii=False, allow_nan=False), _now(), time.time() + 3600))
        return True


def get_pending_speech(analysis_id, interview_id):
    with get_conn() as conn:
        row = conn.execute('SELECT * FROM speech_analyses WHERE id=? AND interview_id=? '
                           'AND message_id IS NULL AND expires_at>?',
                           (analysis_id, interview_id, time.time())).fetchone()
        if not row or row['question_sequence'] != current_question_sequence(conn, interview_id):
            return None
        return json.loads(row['result_json'])


def add_answer_with_speech(interview_id, content, sequence, analysis_id=None):
    """Atomically insert an answer and consume its scoped, single-use analysis ID."""
    with get_conn() as conn:
        # Acquire the SQLite write lock before validating an optional association.
        conn.execute('BEGIN IMMEDIATE')
        if analysis_id:
            row = conn.execute('SELECT question_sequence FROM speech_analyses WHERE id=? AND interview_id=? '
                               'AND message_id IS NULL AND expires_at>?',
                               (analysis_id, interview_id, time.time())).fetchone()
            if not row or row['question_sequence'] != current_question_sequence(conn, interview_id):
                raise ValueError('invalid_analysis_id')
        cur = conn.execute('INSERT INTO messages(interview_id,role,content,message_type,created_at,sequence) '
                           "VALUES (?,'user',?,'answer',?,?)", (interview_id, content, _now(), sequence))
        if analysis_id:
            conn.execute('UPDATE speech_analyses SET message_id=? WHERE id=? AND interview_id=? AND message_id IS NULL',
                         (cur.lastrowid, analysis_id, interview_id))
        return cur.lastrowid


def get_answer_receipt(interview_id, request_id):
    with get_conn() as conn:
        row = conn.execute('SELECT request_hash,response_json FROM answer_receipts WHERE interview_id=? AND request_id=?',
                           (interview_id, request_id)).fetchone()
        return dict(request_hash=row['request_hash'], response=json.loads(row['response_json'])) if row else None


def commit_answer_turn(interview_id, answer, sequence, analysis_id, comment, next_question,
                       question_type, main, followups, finished, expected_question,
                       request_id, request_hash, response):
    """Commit the answer, feedback, state and retry receipt in one transaction."""
    with get_conn() as conn:
        conn.execute('BEGIN IMMEDIATE')
        iv = conn.execute('SELECT status FROM interviews WHERE id=?', (interview_id,)).fetchone()
        if not iv or iv['status'] != 'active' or current_question_sequence(conn, interview_id) != expected_question:
            raise ValueError('question_changed')
        if analysis_id:
            row = conn.execute('SELECT question_sequence FROM speech_analyses WHERE id=? AND interview_id=? '
                               'AND message_id IS NULL AND expires_at>?', (analysis_id, interview_id, time.time())).fetchone()
            if not row or row['question_sequence'] != expected_question:
                raise ValueError('invalid_analysis_id')
        cur = conn.execute("INSERT INTO messages(interview_id,role,content,message_type,created_at,sequence) VALUES (?,'user',?,'answer',?,?)",
                           (interview_id, answer, _now(), sequence))
        if analysis_id:
            conn.execute('UPDATE speech_analyses SET message_id=? WHERE id=? AND interview_id=?',
                         (cur.lastrowid, analysis_id, interview_id))
        conn.execute("INSERT INTO messages(interview_id,role,content,message_type,created_at,sequence) VALUES (?,'assistant',?,'comment',?,?)",
                     (interview_id, comment, _now(), sequence+1))
        if next_question:
            conn.execute("INSERT INTO messages(interview_id,role,content,message_type,created_at,sequence) VALUES (?,'assistant',?,?,?,?)",
                         (interview_id, next_question, question_type, _now(), sequence+2))
        conn.execute('UPDATE interviews SET current_question=?,followup_count=? WHERE id=?', (main, followups, interview_id))
        if finished:
            conn.execute("UPDATE interviews SET status='finished',ended_at=? WHERE id=?", (_now(), interview_id))
            conn.execute('DELETE FROM interview_backgrounds WHERE interview_id=?', (interview_id,))
        if request_id:
            conn.execute('INSERT INTO answer_receipts VALUES (?,?,?,?)',
                         (interview_id, request_id, request_hash, json.dumps(response, ensure_ascii=False)))


def list_speech_analyses(interview_id):
    with get_conn() as conn:
        rows = conn.execute('SELECT s.*,m.content AS answer,q.content AS question FROM speech_analyses s '
                            'JOIN messages m ON m.id=s.message_id AND m.interview_id=s.interview_id '
                            'JOIN messages q ON q.interview_id=s.interview_id AND q.sequence=s.question_sequence '
                            'WHERE s.interview_id=? ORDER BY m.sequence', (interview_id,)).fetchall()
        return [dict(id=r['id'], message_id=r['message_id'], question=r['question'], answer=r['answer'],
                     analysis=json.loads(r['result_json']),
                     feedback=json.loads(r['feedback_json']) if r['feedback_json'] else None) for r in rows]


def save_speech_feedback(analysis_id, interview_id, feedback):
    with get_conn() as conn:
        conn.execute('UPDATE speech_analyses SET feedback_json=? WHERE id=? AND interview_id=? AND message_id IS NOT NULL',
                     (json.dumps(feedback, ensure_ascii=False, allow_nan=False), analysis_id, interview_id))


def get_profile_snapshot(interview_id):
    with get_conn() as conn:
        row=conn.execute('SELECT major,grade,consent,version FROM interview_profile_snapshots WHERE interview_id=?',(interview_id,)).fetchone()
    return dict(row) if row else {}
