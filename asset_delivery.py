"""Content-versioned public static assets; keep HTML and user APIs uncached."""
import hashlib
from pathlib import Path
from flask import request, url_for
from flask.sessions import SecureCookieSessionInterface


class AssetSessionInterface(SecureCookieSessionInterface):
    def should_set_cookie(self, app, session):
        # Flask otherwise refreshes permanent cookies even for untouched sessions.
        return request.endpoint != 'static' and super().should_set_cookie(app, session)


def install(app):
    app.session_interface = AssetSessionInterface()
    root = Path(app.static_folder).resolve()
    versions = {}

    def fingerprint(filename):
        path = (root / filename).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            return None
        stat = path.stat()
        signature = (stat.st_mtime_ns, stat.st_size)
        saved = versions.get(filename)
        if saved is None or saved[0] != signature:
            saved = (signature, hashlib.sha256(path.read_bytes()).hexdigest()[:16])
            versions[filename] = saved
        return saved[1]

    def asset_url(filename):
        return url_for('static', filename=filename, v=fingerprint(filename))

    app.jinja_env.globals['asset_url'] = asset_url

    @app.after_request
    def cache_static(response):
        if request.endpoint == 'static' and response.status_code in (200,304):
            filename = (request.view_args or {}).get('filename','')
            version = fingerprint(filename)
            if version and request.args.get('v') == version:
                response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
            else:
                response.headers['Cache-Control'] = 'no-cache'
        return response

    return fingerprint
