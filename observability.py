"""Request correlation and content-free timing; no credentials or bodies logged."""
import json,secrets,time,logging
from flask import g,request

def install(app):
    from flask.logging import default_handler
    if not app.logger.handlers:app.logger.addHandler(default_handler)
    app.logger.propagate=False  # Waitress later configures root logging; avoid duplicate timing rows.
    app.logger.setLevel(logging.INFO)
    def begin():
        g.request_id=secrets.token_hex(8);g.request_started=time.perf_counter()
    app.before_request_funcs.setdefault(None,[]).insert(0,begin)
    @app.after_request
    def end(response):
        elapsed=(time.perf_counter()-g.get('request_started',time.perf_counter()))*1000
        db=g.get('db_ms',0);ai=g.get('ai_ms',0)
        response.headers['X-Request-ID']=g.get('request_id','')
        response.headers['Server-Timing']=f'app;dur={elapsed:.2f}, db;dur={db:.2f}, ai;dur={ai:.2f}'
        if request.endpoint!='static':app.logger.info(json.dumps(dict(event='request_timing',request_id=g.get('request_id'),endpoint=request.endpoint,status=response.status_code,app_ms=round(elapsed,2),db_ms=round(db,2),ai_ms=round(ai,2))))
        return response
