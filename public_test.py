"""Small-group HTTPS trial: separate DB selected by runner, browser-scoped access.

HTTPS trial/formal entry-point policy. Account ownership also applies in the local app.
"""
import hashlib
import secrets
import threading
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from flask import g, jsonify, request, session
from interview_time import normalize_interview


def install(app, db, daily_starts=30):
    app.extensions['public_trial_installed']=True
    with db.get_conn() as conn:
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS trial_owners (
                interview_id TEXT PRIMARY KEY REFERENCES interviews(id) ON DELETE CASCADE,
                owner_hash TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_trial_owner ON trial_owners(owner_hash);
            CREATE TABLE IF NOT EXISTS trial_limits (day TEXT PRIMARY KEY, starts INTEGER NOT NULL);
        ''')
    asr_slot = threading.BoundedSemaphore(1)

    def owner():
        if not session.get('trial_browser'):
            session['trial_browser'] = secrets.token_hex(32)
            session.permanent = True
        return hashlib.sha256(session['trial_browser'].encode()).hexdigest()

    def owns(sid):
        from accounts import owns as account_owns
        return account_owns(db,sid)

    @app.before_request
    def protect_trial():
        if request.path.startswith('/static/'):
            return None
        owner()
        if request.method in ('POST', 'DELETE', 'PUT', 'PATCH'):
            origin = request.headers.get('Origin', '')
            try:
                parsed = urlsplit(origin)
            except ValueError:
                return jsonify(error='请求来源不正确'), 403
            if parsed.scheme != 'https' or parsed.netloc != request.host:
                return jsonify(error='请从试用网站页面内操作，或刷新页面后重试'), 403
        sid = None
        if request.endpoint in ('api_answer', 'api_end'):
            data = request.get_json(silent=True)
            if not isinstance(data, dict):
                return jsonify(error='请求格式不正确'), 400
            sid = data.get('session_id')
        elif request.endpoint in ('api_report', 'api_report_generate', 'api_export_report', 'api_interview_state', 'api_delete_interview', 'api_speech_review', 'api_clear_background'):
            sid = (request.view_args or {}).get('session_id')
        elif request.endpoint == 'api_transcribe':
            sid = request.form.get('session_id')
        if sid is not None or request.endpoint in ('api_answer', 'api_end', 'api_transcribe'):
            if not owns(sid):
                return jsonify(error='当前浏览器没有这场面试的访问权限，请从首页重新开始'), 404
        if request.endpoint == 'api_end':
            interview = db.get_interview(sid)
            if interview and interview['status'] != 'active':
                return jsonify(finished=True)
        if request.endpoint == 'api_transcribe':
            if not asr_slot.acquire(blocking=False):
                return jsonify(success=False, error='另一段录音正在识别，请稍后点击重新识别'), 429
            g.trial_asr_slot = True
        if request.endpoint == 'api_start' and request.method == 'POST' and daily_starts is not None:
            day = datetime.now(timezone(timedelta(hours=9))).date().isoformat()
            with db.get_conn() as conn:
                conn.execute('INSERT OR IGNORE INTO trial_limits(day,starts) VALUES (?,0)', (day,))
                cur = conn.execute('UPDATE trial_limits SET starts=starts+1 WHERE day=? AND starts<?', (day, daily_starts))
                if not cur.rowcount:
                    return jsonify(error='今天的试用场次已用完，请明天再试；已有面试仍可继续'), 429

    @app.after_request
    def finish_trial(response):
        if request.endpoint == 'api_start' and response.status_code == 200 and g.get('security_bypass'):
            data = response.get_json(silent=True) or {}
            sid = data.get('session_id')
            if sid:
                try:
                    with db.get_conn() as conn:
                        conn.execute('INSERT OR IGNORE INTO trial_owners(interview_id,owner_hash) VALUES (?,?)', (sid, owner()))
                except Exception:
                    error_response = jsonify(error='试用记录关联失败，请重新开始')
                    error_response.status_code = 503
                    return error_response
        if not request.path.startswith('/static/'):
            response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['X-Robots-Tag'] = 'noindex, noarchive'
        response.headers['Content-Security-Policy'] = "frame-ancestors 'none'"
        response.headers['Permissions-Policy'] = 'microphone=(self)'
        return response

    @app.teardown_request
    def release_trial_slot(error):
        if g.pop('trial_asr_slot', False):
            asr_slot.release()

    # Existing history UI receives only rows owned by this browser.
    def browser_history():
        try:
            limit = max(1, min(int(request.args.get('limit', 50)), 200))
        except (ValueError, TypeError):
            limit = 50
        with db.get_conn() as conn:
            rows = conn.execute('''
                SELECT i.id,i.job,i.difficulty,i.started_at,i.ended_at,i.status,r.overall_score,
                (SELECT COUNT(*) FROM messages m WHERE m.interview_id=i.id AND m.role='user') AS answered_count
                FROM interviews i JOIN trial_owners o ON o.interview_id=i.id
                LEFT JOIN reports r ON r.interview_id=i.id
                WHERE o.owner_hash=? ORDER BY interview_timestamp(i.started_at) DESC LIMIT ?
            ''', (owner(), limit)).fetchall()
        items = []
        for row in rows:
            item = normalize_interview(row)
            item['selection'] = db.get_selection(item['id'])
            item['has_report'] = item['overall_score'] is not None
            item['can_view_report'] = item['status'] in ('finished', 'ended') and item['answered_count'] > 0
            items.append(item)
        return jsonify(total=len(items), items=items)
    app.view_functions['api_interviews'] = app.extensions.get('account_history',browser_history)
