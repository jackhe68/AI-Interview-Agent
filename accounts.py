"""Username/password accounts with revocable opaque sessions and server-side ownership."""
import hashlib,hmac,json,os,re,secrets,sqlite3,time,uuid
from pathlib import Path
from urllib.parse import urlsplit
from flask import g,jsonify,request,session,render_template,has_request_context
from werkzeug.exceptions import HTTPException
from werkzeug.security import generate_password_hash,check_password_hash
from interview_catalog import MAJORS,JOBS,LEVELS
from interview_time import normalize_interview

GRADES = {**{f'undergrad-{i}':f'本科{i}年级' for i in range(1,6)},
          **{f'master-{i}':f'研究生（硕士）{i}年级' for i in range(1,4)},
          **{f'doctor-{i}':f'博士{i}年级' for i in range(1,6)},
          **{f'college-{i}':f'专科{i}年级' for i in range(1,4)},'graduated':'已毕业','other':'其他学习阶段'}
COOKIE='iv_auth'

def digest(value):return hashlib.sha256(value.encode()).hexdigest()

def guest_hash():
    if not session.get('trial_browser'):
        session['trial_browser']=secrets.token_hex(32);session.permanent=True
    return digest(session['trial_browser'])

def owns(db,sid):
    if not isinstance(sid,str) or not sid:return False
    with db.get_conn() as conn:
        row=conn.execute('SELECT owner_user_id FROM interviews WHERE id=?',(sid,)).fetchone()
        if not row:return False
        if row['owner_user_id']:
            return bool(g.get('current_user') and row['owner_user_id']==g.current_user['id'])
        # While signed in, unclaimed guest records require explicit migration first.
        if g.get('current_user'):return False
        return conn.execute('SELECT 1 FROM trial_owners WHERE interview_id=? AND owner_hash=?',(sid,guest_hash())).fetchone() is not None

def bind_record(conn,sid):
    if not has_request_context() or g.get('security_bypass'):return
    user=g.get('current_user')
    if user:conn.execute('UPDATE interviews SET owner_user_id=? WHERE id=?',(user['id'],sid))
    else:conn.execute('INSERT OR IGNORE INTO trial_owners VALUES (?,?)',(sid,guest_hash()))

def profile_for(db,uid):
    with db.get_conn() as conn:
        row=conn.execute('SELECT u.id,u.username,p.nickname,p.major_id,p.other_major,p.grade FROM users u JOIN user_profiles p ON p.user_id=u.id WHERE u.id=?',(uid,)).fetchone()
    if not row:return None
    result=dict(row);result['major']=MAJORS.get(result['major_id'],{}).get('name',result['other_major'])
    result['grade_label']=GRADES.get(result['grade'],'其他学习阶段')
    return result

def valid_text(value):
    if not isinstance(value,str):return False
    try:value.encode('utf-8')
    except UnicodeError:return False
    return not any(ord(c)<32 or ord(c)==127 for c in value)

def valid_password(value):
    if not isinstance(value,str) or len(value)>128:return False
    try:value.encode('utf-8')
    except UnicodeError:return False
    return True

def profile_fields(data):
    errors={}
    nick=data.get('nickname');major=data.get('major_id');other=data.get('other_major','');grade=data.get('grade')
    if not valid_text(nick) or not 1<=len(nick.strip())<=40:errors['nickname']='请输入1至40字的称呼，可使用昵称'
    if not isinstance(major,str) or (major not in MAJORS and major!='other'):errors['major_id']='请选择专业或其他'
    if not valid_text(other) or len(other.strip())>80 or (major=='other' and not other.strip()):errors['other_major']='选择其他时请填写1至80字的专业'
    if not isinstance(grade,str) or grade not in GRADES:errors['grade']='请选择当前学习阶段'
    return errors,dict(nickname=nick.strip() if isinstance(nick,str) else '',major_id=major,other_major=other.strip() if isinstance(other,str) and major=='other' else '',grade=grade)

def passwords(data):
    password=data.get('password');confirm=data.get('confirm_password')
    if not isinstance(password,str) or not 10<=len(password)<=128:return {'password':'密码须为10至128个字符'}
    try:password.encode('utf-8')
    except UnicodeError:return {'password':'密码包含不支持的字符，请重新输入'}
    if password!=confirm:return {'confirm_password':'两次输入的密码不一致'}
    return {}

def install(app,db,server):
    if app.extensions.get('accounts'):return
    app.extensions['accounts']=True
    if not app.secret_key:
        secret=Path(app.root_path)/'.secret_key'
        try:
            with secret.open('x',encoding='ascii') as f:f.write(secrets.token_hex(32))
        except FileExistsError:pass
        app.secret_key=os.getenv('SECRET_KEY') or secret.read_text(encoding='ascii').strip()
    app.config.update(SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Lax',SESSION_COOKIE_SECURE=not app.config.get('APP_INSECURE',False))
    app.config.setdefault('AUTH_SESSION_SECONDS',7*24*3600)
    dummy=generate_password_hash('not-an-account-password-fixture',method='scrypt')

    def error(text,status=400,code='invalid_request',fields=None):
        body=dict(error=text,code=code)
        if fields:body['fields']=fields
        return jsonify(body),status

    def csrf():
        token=request.cookies.get(COOKIE,'')
        if g.get('current_user'):
            return hmac.new(str(app.secret_key).encode(),('csrf:'+token).encode(),hashlib.sha256).hexdigest()
        if not session.get('csrf_token'):session['csrf_token']=secrets.token_hex(32)
        return session['csrf_token']

    def limited(kind,username=''):
        # Only configured trusted tunnel traffic may supply the client IP header.
        ip=request.remote_addr or 'unknown'
        if app.config.get('TRUST_CLOUDFLARE') and ip in ('127.0.0.1','::1'):ip=request.headers.get('CF-Connecting-IP',ip)
        now=int(time.time());window=now//900
        entries=[(kind+':ip:'+ip,5 if kind=='register' else 30)]
        if username:entries.append((kind+':name:'+username,10))
        override=app.config.get('AUTH_RATE_LIMIT')
        with db.get_conn() as conn:
            conn.execute('BEGIN IMMEDIATE')
            for raw,maximum in entries:
                key=hmac.new(str(app.secret_key).encode(),raw.encode(),hashlib.sha256).hexdigest()
                row=conn.execute('SELECT count FROM auth_attempts WHERE subject=? AND window=?',(key,window)).fetchone()
                if row and row['count'] >= (override if override is not None else maximum):return True
            for raw,maximum in entries:
                key=hmac.new(str(app.secret_key).encode(),raw.encode(),hashlib.sha256).hexdigest()
                conn.execute('INSERT INTO auth_attempts VALUES (?,?,1) ON CONFLICT(subject,window) DO UPDATE SET count=count+1',(key,window))
            conn.execute('DELETE FROM auth_attempts WHERE window<?',(now//900-96,))
        return False

    def identity():
        g.current_user=None
        token=request.cookies.get(COOKIE,'')
        if token and len(token)<=128:
            with db.get_conn() as conn:
                row=conn.execute('SELECT user_id FROM auth_sessions WHERE token_hash=? AND expires_at>?',(digest(token),time.time())).fetchone()
            if row:g.current_user=profile_for(db,row['user_id'])
        guest_hash()

    def new_session(uid,response,*,expected_hash,revoke_all=False,new_password_hash=None):
        token=secrets.token_urlsafe(32);now=time.time()
        with db.get_conn() as conn:
            conn.execute('BEGIN IMMEDIATE')
            current=conn.execute('SELECT password_hash FROM users WHERE id=?',(uid,)).fetchone()
            if not current or not hmac.compare_digest(current['password_hash'],expected_hash):
                return error('登录信息已更新，请使用当前密码重新登录',401,'credentials_changed')
            if new_password_hash is not None:
                conn.execute('UPDATE users SET password_hash=? WHERE id=?',(new_password_hash,uid))
            if revoke_all:conn.execute('DELETE FROM auth_sessions WHERE user_id=?',(uid,))
            old=request.cookies.get(COOKIE,'')
            if old:conn.execute('DELETE FROM auth_sessions WHERE token_hash=?',(digest(old),))
            conn.execute('DELETE FROM auth_sessions WHERE expires_at<=?',(now,))
            conn.execute('INSERT INTO auth_sessions VALUES (?,?,?,?)',(digest(token),uid,now,now+app.config['AUTH_SESSION_SECONDS']))
        response.set_cookie(COOKIE,token,max_age=app.config['AUTH_SESSION_SECONDS'],httponly=True,
                            secure=not app.config.get('APP_INSECURE',False),samesite='Lax',path='/')
        return response

    @app.before_request
    def account_security():
        if request.endpoint=='static':return
        g.security_bypass=bool(app.config.get('SECURITY_TEST_BYPASS',False))
        if g.security_bypass:return
        identity()
        if request.method in ('POST','PUT','PATCH','DELETE') and request.path.startswith('/api/'):
            if request.path.startswith('/api/account') and (request.content_length or 0)>16384:return error('账户信息过长，请精简后重试',413)
            try:origin=urlsplit(request.headers.get('Origin',''))
            except ValueError:return error('请求来源不正确',403,'csrf_failed')
            if origin.netloc!=request.host or origin.scheme!=request.scheme:
                return error('请求来源不正确，请刷新页面后重试',403,'csrf_failed')
            provided=request.headers.get('X-CSRF-Token','')
            if not provided or not hmac.compare_digest(provided,csrf()):return error('安全信息已更新，请刷新页面后重试',403,'csrf_failed')
        if request.endpoint=='api_start':
            data=request.get_json(silent=True)
            if not isinstance(data,dict):return error('开始信息须为有效对象')
            if not isinstance(data.get('job'),str) or data['job'] not in JOBS or not isinstance(data.get('level'),str) or data['level'] not in LEVELS:return error('请选择页面提供的岗位和难度')
        if request.method in ('POST','PATCH','PUT','DELETE') and request.endpoint!='api_transcribe' and (request.content_length or 0)>32768:return error('请求内容过长，请精简后重试',413)
        sid=None
        if request.endpoint in ('api_answer','api_end'):
            data=request.get_json(silent=True)
            if not isinstance(data,dict):return error('请提交正确格式的回答',400)
            sid=data.get('session_id')
        elif request.endpoint=='api_transcribe':sid=request.form.get('session_id')
        elif request.view_args and 'session_id' in request.view_args:sid=request.view_args['session_id']
        if sid is not None or request.endpoint in ('api_answer','api_end','api_transcribe'):
            if not owns(db,sid):return error('无法访问这场面试，请使用对应账户或原游客浏览器',404,'not_found')
        # Reading the report can enqueue AI work; require a synchronizer token on this GET too.
        if request.endpoint=='api_report' and request.method=='GET':
            provided=request.headers.get('X-CSRF-Token','')
            if not provided or not hmac.compare_digest(provided,csrf()):return error('请从报告页面继续，或刷新页面后重试',403,'csrf_failed')

    @app.after_request
    def private_responses(response):
        if request.endpoint!='static':response.headers['Cache-Control']='no-store'
        response.headers.setdefault('X-Content-Type-Options','nosniff')
        if request.path.startswith('/api/') and response.status_code>=400:
            data=response.get_json(silent=True)
            if isinstance(data,dict):
                data.setdefault('code','request_failed');data.setdefault('request_id',g.get('request_id',''))
                response.set_data(app.json.dumps(data));response.mimetype='application/json'
            if response.status_code==429:response.headers.setdefault('Retry-After','900')
        return response

    @app.errorhandler(404)
    def missing(exc):
        if request.path.startswith('/api/'):return error('未找到可访问的内容',404,'not_found')
        return render_template('error.html',message='这个页面不存在，请从首页继续。'),404

    @app.errorhandler(405)
    def wrong_method(exc):
        if request.path.startswith('/api/'):return error('此操作方式不受支持',405,'method_not_allowed')
        return render_template('error.html',message='此操作方式不受支持，请从页面按钮继续。'),405

    @app.errorhandler(Exception)
    def sanitized_failure(exc):
        status=exc.code if isinstance(exc,HTTPException) else 500
        messages={400:'请求格式不正确，请检查后重试',413:'内容过大，请精简或缩短录音后重试'}
        message=messages.get(status,'服务暂时无法确认操作结果，请刷新页面核对后重试')
        if status>=500:app.logger.error('Request failed (%s)',type(exc).__name__)
        if request.path.startswith('/api/'):return error(message,status,'request_failed')
        return render_template('error.html',message=message),status

    def require_user():
        return error('请先登录账户',401,'login_required') if not g.get('current_user') else None

    def data_object(allowed):
        data=request.get_json(silent=True)
        if not isinstance(data,dict) or set(data)-set(allowed):return None
        return data

    @app.get('/api/account/session')
    def account_session():
        user=g.get('current_user');owner=guest_hash()
        with db.get_conn() as conn:
            count=conn.execute('SELECT count(*) FROM interviews i JOIN trial_owners o ON o.interview_id=i.id WHERE i.owner_user_id IS NULL AND o.owner_hash=?',(owner,)).fetchone()[0]
        return jsonify(user=user,csrf_token=csrf(),scope='legacy' if g.get('security_bypass') else 'user:'+user['id'] if user else 'guest:'+owner,
                       guest_count=count,majors=[dict(id=m['id'],name=m['name']) for m in MAJORS.values()],grades=GRADES)

    @app.post('/api/account/register')
    def account_register():
        data=data_object(['username','password','confirm_password','nickname','major_id','other_major','grade'])
        if data is None:return error('注册信息格式不正确')
        username=data.get('username','')
        if not isinstance(username,str) or not re.fullmatch('[A-Za-z][A-Za-z0-9_]{2,31}',username):return error('请检查用户名格式',fields={'username':'用户名须以字母开头，3至32位字母、数字或下划线'})
        username=username.lower()
        if limited('register',username):return error('注册尝试较多，请稍后再试',429,'rate_limited')
        errors,profile=profile_fields(data);errors.update(passwords(data))
        if errors:return error('请检查填写内容',fields=errors)
        uid=uuid.uuid4().hex;hashed=generate_password_hash(data['password'],method='scrypt')
        try:
            with db.get_conn() as conn:
                conn.execute('INSERT INTO users VALUES (?,?,?,?)',(uid,username,hashed,db._now()))
                conn.execute('INSERT INTO user_profiles VALUES (?,?,?,?,?)',(uid,profile['nickname'],profile['major_id'],profile['other_major'],profile['grade']))
        except sqlite3.IntegrityError:return error('该用户名已被使用',409,'username_taken',{'username':'该用户名已被使用，请换一个'})
        return new_session(uid,jsonify(ok=True,user=profile_for(db,uid)),expected_hash=hashed)

    @app.post('/api/account/login')
    def account_login():
        data=data_object(['username','password'])
        if data is None:return error('登录信息格式不正确')
        username=data.get('username');password=data.get('password')
        if not isinstance(username,str) or not re.fullmatch('[A-Za-z][A-Za-z0-9_]{2,31}',username) or not isinstance(password,str) or len(password)>128:return error('用户名或密码不正确',401,'invalid_credentials')
        try:password.encode('utf-8')
        except UnicodeError:return error('用户名或密码不正确',401,'invalid_credentials')
        if limited('login',username.lower()):return error('登录尝试较多，请稍后再试',429,'rate_limited')
        with db.get_conn() as conn:row=conn.execute('SELECT * FROM users WHERE username=?',(username.lower(),)).fetchone()
        valid=check_password_hash(row['password_hash'] if row else dummy,password)
        if not row or not valid:return error('用户名或密码不正确',401,'invalid_credentials')
        return new_session(row['id'],jsonify(ok=True,user=profile_for(db,row['id'])),expected_hash=row['password_hash'])

    @app.post('/api/account/logout')
    def account_logout():
        with db.get_conn() as conn:conn.execute('DELETE FROM auth_sessions WHERE token_hash=?',(digest(request.cookies.get(COOKIE,'')),))
        response=jsonify(ok=True);response.delete_cookie(COOKIE,path='/');return response

    @app.route('/api/account/profile',methods=['GET','PATCH'])
    def account_profile():
        denied=require_user()
        if denied:return denied
        if request.method=='GET':return jsonify(user=g.current_user)
        data=data_object(['nickname','major_id','other_major','grade'])
        if data is None:return error('资料格式不正确')
        errors,profile=profile_fields(data)
        if errors:return error('请检查填写内容',fields=errors)
        with db.get_conn() as conn:conn.execute('UPDATE user_profiles SET nickname=?,major_id=?,other_major=?,grade=? WHERE user_id=?',(profile['nickname'],profile['major_id'],profile['other_major'],profile['grade'],g.current_user['id']))
        return jsonify(ok=True,user=profile_for(db,g.current_user['id']))

    @app.post('/api/account/password')
    def account_password():
        denied=require_user()
        if denied:return denied
        data=data_object(['current_password','password','confirm_password','revoke_others'])
        if data is None:return error('密码信息格式不正确')
        if limited('reauth',g.current_user['id']):return error('验证尝试较多，请稍后再试',429,'rate_limited')
        with db.get_conn() as conn:row=conn.execute('SELECT password_hash FROM users WHERE id=?',(g.current_user['id'],)).fetchone()
        if not row or not valid_password(data.get('current_password')) or not check_password_hash(row['password_hash'],data['current_password']):return error('当前密码不正确',401,'invalid_credentials')
        errors=passwords(data)
        if errors:return error('请检查新密码',fields=errors)
        if not isinstance(data.get('revoke_others',True),bool):return error('会话撤销选项格式不正确')
        hashed=generate_password_hash(data['password'],method='scrypt')
        # Recheck the verified credential, rotate it and issue/revoke sessions atomically.
        return new_session(g.current_user['id'],jsonify(ok=True),expected_hash=row['password_hash'],
                           new_password_hash=hashed,revoke_all=data.get('revoke_others',True))

    @app.post('/api/account/claim-guests')
    def account_claim():
        denied=require_user()
        if denied:return denied
        if data_object([]) is None:return error('无需提供记录标识，请使用迁移按钮')
        with db.get_conn() as conn:
            conn.execute('BEGIN IMMEDIATE')
            result=conn.execute('UPDATE interviews SET owner_user_id=? WHERE owner_user_id IS NULL AND id IN (SELECT interview_id FROM trial_owners WHERE owner_hash=?)',(g.current_user['id'],guest_hash()))
            conn.execute('UPDATE start_requests SET owner_user_id=? WHERE interview_id IN (SELECT id FROM interviews WHERE owner_user_id=?)',(g.current_user['id'],g.current_user['id']))
        return jsonify(ok=True,migrated=result.rowcount)

    @app.delete('/api/account')
    def account_delete():
        denied=require_user()
        if denied:return denied
        data=data_object(['password','confirmation'])
        if data is None or data.get('confirmation')!='注销账户':return error('请填写密码并输入“注销账户”确认')
        if limited('reauth',g.current_user['id']):return error('验证尝试较多，请稍后再试',429,'rate_limited')
        with db.get_conn() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row=conn.execute('SELECT password_hash FROM users WHERE id=?',(g.current_user['id'],)).fetchone()
            password=data.get('password')
            if not row or not valid_password(password) or not check_password_hash(row['password_hash'],password):return error('密码不正确',401,'invalid_credentials')
            ids=[r[0] for r in conn.execute('SELECT id FROM interviews WHERE owner_user_id=?',(g.current_user['id'],))]
            from deletion_journal import record
            record(db,ids,g.current_user['id'])
            conn.execute('DELETE FROM users WHERE id=?',(g.current_user['id'],))
        from speech_temp import cleanup
        cleanup(db,ids)
        for sid in ids:server.SESSIONS.pop(sid,None)
        response=jsonify(ok=True);response.delete_cookie(COOKIE,path='/');return response

    @app.get('/account')
    def account_page():return render_template('account.html')

    @app.get('/privacy')
    def privacy_page():return render_template('privacy.html')

    original_history=app.view_functions['api_interviews']
    def history():
        if g.get('security_bypass') and not app.extensions.get('public_trial_installed'):return original_history()
        try:limit=max(1,min(int(request.args.get('limit',50)),200))
        except (TypeError,ValueError):limit=50
        user=g.get('current_user')
        where='i.owner_user_id=?' if user else 'i.owner_user_id IS NULL AND o.owner_hash=?'
        identity=user['id'] if user else guest_hash()
        with db.get_conn() as conn:
            rows=conn.execute('SELECT i.*,r.overall_score,r.id AS report_id,r.detail AS report_detail,(SELECT count(*) FROM messages m WHERE m.interview_id=i.id AND m.role=\'user\') answered_count FROM interviews i LEFT JOIN trial_owners o ON o.interview_id=i.id LEFT JOIN reports r ON r.interview_id=i.id WHERE '+where+' ORDER BY interview_timestamp(i.started_at) DESC LIMIT ?',(identity,limit)).fetchall()
        items=[]
        for row in rows:
            item=normalize_interview(row);item.pop('owner_user_id',None)
            detail=json.loads(item.pop('report_detail') or '{}');has_report=item.pop('report_id') is not None
            if detail.get('unassessed'):item['overall_score']=None
            item.update(selection=db.get_selection(item['id']),has_report=has_report,can_view_report=item['status'] in ('ended','finished') and item['answered_count']>0)
            items.append(item)
        return jsonify(total=len(items),items=items)
    app.view_functions['api_interviews']=history
    app.extensions['account_history']=history
