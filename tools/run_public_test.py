"""Start the external trial origin on loopback; connect only this port to a tunnel."""
import os
import secrets
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
RUNTIME = ROOT / '.public-test'
RUNTIME.mkdir(exist_ok=True)

# Set DB path BEFORE importing the application, so init_db cannot touch old history.
import database
database.DB_PATH = str(RUNTIME / 'trials.db')
import app as server
from public_test import install

secret_path = RUNTIME / 'cookie.key'
try:
    with secret_path.open('x', encoding='ascii') as secret_file:
        secret_file.write(secrets.token_hex(32))
except FileExistsError:
    pass
server.app.config.update(SECRET_KEY=secret_path.read_text(encoding='ascii').strip(),
                         APP_INSECURE=False, TRUST_CLOUDFLARE=True, SESSION_COOKIE_NAME='iv_trial_browser', SESSION_COOKIE_SECURE=True,
                         SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                         PERMANENT_SESSION_LIFETIME=timedelta(days=14))
install(server.app, database, daily_starts=None)
from api_guard import install as install_api_guard, trial_limits_from_env
TRIAL_LIMITS, ACCOUNT_LIMITS = trial_limits_from_env()
install_api_guard(server, database, limits=TRIAL_LIMITS, user_limits=ACCOUNT_LIMITS, trust_cloudflare=True)
from candidate_background import start_cleanup
start_cleanup(database)

if __name__ == '__main__':
    from waitress import serve
    # Leave workers available for pages/health while all AI slots are occupied.
    print(f"AI concurrency limit: {TRIAL_LIMITS['ai_concurrent']}; "
          f"request threads: {TRIAL_LIMITS['ai_concurrent'] + 4}", flush=True)
    serve(server.app, host='127.0.0.1', port=5010,
          threads=TRIAL_LIMITS['ai_concurrent'] + 4, channel_timeout=240,
          max_request_body_size=26 * 1024 * 1024,
          trusted_proxy='127.0.0.1', trusted_proxy_headers={'x-forwarded-proto'})
