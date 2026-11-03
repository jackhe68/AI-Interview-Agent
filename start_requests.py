"""Owner-scoped start receipts. An interrupted dispatch is never silently retried."""
import hashlib,json,re,time,uuid
from flask import g
from accounts import guest_hash,owns

RUNNER_ID=uuid.uuid4().hex

class StartRequestError(Exception):
    def __init__(self,status,message,code):
        super().__init__(message)
        self.status,self.message,self.code=status,message,code

def reserve(db,key,payload):
    if key is None:return None,None
    if not isinstance(key,str) or not re.fullmatch('[0-9a-f]{32}',key):
        raise StartRequestError(400,'启动请求标识格式不正确，请刷新后重试','invalid_start_request')
    user=g.get('current_user')
    owner='account:'+user['id'] if user else 'guest:'+guest_hash()
    scope=hashlib.sha256(owner.encode()).hexdigest()
    signature=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    reservation=dict(scope=scope,key=key,token=uuid.uuid4().hex)
    conflict=None
    with db.get_conn() as conn:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute("DELETE FROM start_requests WHERE interview_id IS NULL AND created_at<?",(time.time()-7*86400,))
        row=conn.execute('SELECT * FROM start_requests WHERE scope_hash=? AND request_id=?',(scope,key)).fetchone()
        if row:
            if row['request_hash']!=signature:
                raise StartRequestError(409,'同一启动标识不能用于不同配置，请核对后新建一场','start_conflict')
            if row['state']=='complete':
                if not owns(db,row['interview_id']):raise StartRequestError(404,'这场面试已不属于当前身份，请从对应账户的历史查看','not_found')
                return None,(json.loads(row['response_json']),200)
            if row['state']=='failed':return None,(json.loads(row['response_json']),row['error_status'])
            if row['state']=='deleted':raise StartRequestError(410,'原练习已删除，不能通过重试恢复，请核对后新建一场','start_deleted')
            if row['state']=='processing' and row['runner_id']==RUNNER_ID:
                conflict=StartRequestError(409,'首题仍在处理中，请稍后重试同一次请求，勿重复新建','start_in_progress')
            else:
                conn.execute("UPDATE start_requests SET state='uncertain' WHERE scope_hash=? AND request_id=?",(scope,key))
                conflict=StartRequestError(409,'上次启动结果尚未确认，请先核对历史；不会自动再次调用AI','start_uncertain')
        else:
            conn.execute("INSERT INTO start_requests(scope_hash,request_id,request_hash,state,runner_id,token,owner_user_id,created_at) VALUES (?,?,?,'processing',?,?,?,?)",
                         (scope,key,signature,RUNNER_ID,reservation['token'],user['id'] if user else None,time.time()))
    if conflict:raise conflict
    return reservation,None

def complete(conn,reservation,sid,response):
    if not reservation:return
    result=conn.execute("UPDATE start_requests SET state='complete',interview_id=?,response_json=? WHERE scope_hash=? AND request_id=? AND token=? AND state='processing'",
                        (sid,json.dumps(response,ensure_ascii=False),reservation['scope'],reservation['key'],reservation['token']))
    if result.rowcount!=1:raise ValueError('Start reservation changed')

def failed(db,reservation,status,message,uncertain=False):
    if not reservation:return
    response=dict(error=message,code='start_uncertain' if uncertain else 'start_failed')
    with db.get_conn() as conn:
        conn.execute("UPDATE start_requests SET state=?,response_json=?,error_status=? WHERE scope_hash=? AND request_id=? AND token=? AND state='processing'",
                     ('uncertain' if uncertain else 'failed',json.dumps(response,ensure_ascii=False),status,
                      reservation['scope'],reservation['key'],reservation['token']))
