# -*- coding: utf-8 -*-
"""生产入口：Waitress 单进程多线程，只监听回环，由 Nginx 反代。

为什么不用 gunicorn -w N：
app.py 里的 SESSIONS、REPORT_INFLIGHT 和几把 threading.Lock 都在进程内存中，
多 worker 会让 busy 锁与“报告生成中”状态失效，导致重复生成/并发写库。
"""
import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # deploy/ 的上一级 = 项目根
os.chdir(ROOT)

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

SECRET_KEY_FILE = ROOT / ".secret_key"


def _secret_key() -> str:
    """优先 .env 的 SECRET_KEY，其次复用持久化文件，最后生成一次。"""
    key = (os.getenv("SECRET_KEY") or "").strip()
    if key:
        return key
    if SECRET_KEY_FILE.exists():
        saved = SECRET_KEY_FILE.read_text(encoding="ascii").strip()
        if saved:
            return saved
    key = secrets.token_hex(32)
    SECRET_KEY_FILE.write_text(key, encoding="ascii")
    os.chmod(SECRET_KEY_FILE, 0o600)
    return key


import app as server  # noqa: E402  (导入即执行 init_db)

server.app.config.update(
    SECRET_KEY=_secret_key(),
    SESSION_COOKIE_NAME="iv_browser",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    # 正式站全站 HTTPS；若临时用 IP:5010 调试，启动前设 APP_INSECURE=1
    SESSION_COOKIE_SECURE=os.getenv("APP_INSECURE") != "1",
)

# Nginx 在 127.0.0.1 上反代，必须让 Flask 认识真实客户端 IP，
# 否则 api_guard 会把所有访客当成同一个 127.0.0.1（每 IP 限额失效）。
from werkzeug.middleware.proxy_fix import ProxyFix  # noqa: E402

server.app.wsgi_app = ProxyFix(server.app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# 公网限流：默认开启，防止 DeepSeek 账单被刷、防止并发把 4 核打满。
# 额度见 api_guard.DEFAULTS（全局 300 次/天、单浏览器 50、单 IP 200、并发 2）。
# 需要关掉时在 .env 里加 API_GUARD=0。
if os.getenv("API_GUARD", "1") != "0":
    from api_guard import install as install_api_guard  # noqa: E402

    install_api_guard(server, server.dbm)

from candidate_background import start_cleanup  # noqa: E402

start_cleanup(server.dbm)

if __name__ == "__main__":
    from waitress import serve

    serve(
        server.app,
        host="127.0.0.1",
        port=int(os.getenv("PORT", "5010")),
        threads=int(os.getenv("WAITRESS_THREADS", "8")),
        # 与 app.py 的 MAX_CONTENT_LENGTH(25MB) 对齐，给 1MB 余量
        max_request_body_size=26 * 1024 * 1024,
        # 转写 + 评分链路较慢，配合 Nginx proxy_read_timeout 240s
        channel_timeout=240,
    )
