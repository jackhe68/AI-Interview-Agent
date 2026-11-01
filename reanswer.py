"""Saved re-answer practice, no new AI call or numerical re-scoring."""
import json,re,uuid
from flask import request,jsonify
from practice_feedback import answered_questions

def install(app,db):
    @app.route('/api/interview/<session_id>/reanswers',methods=['GET','POST'])
    def reanswers(session_id):
        if request.method=='GET':
            with db.get_conn() as conn:rows=[dict(r) for r in conn.execute('SELECT * FROM reanswers WHERE interview_id=? ORDER BY created_at,id',(session_id,))]
            return jsonify(items=rows,questions=answered_questions(db.get_messages(session_id)),rescored=False,ai_called=False)
        data=request.get_json(silent=True)
        if not isinstance(data,dict) or set(data)-{'answer_sequence','answer','request_id'}:return jsonify(error='练习信息格式不正确'),400
        seq=data.get('answer_sequence');answer=data.get('answer');key=data.get('request_id')
        pairs=answered_questions(db.get_messages(session_id))
        if not isinstance(seq,int) or isinstance(seq,bool) or seq not in [p['answer_sequence'] for p in pairs]:return jsonify(error='请选择本场已回答的问题'),400
        from accounts import valid_text
        if not isinstance(answer,str) or not 1<=len(answer.strip())<=4000 or not valid_text(answer.replace('\n','').replace('\r','').replace('\t','')):return jsonify(error='重答内容须为1至4000字'),400
        if not isinstance(key,str) or not re.fullmatch('[0-9a-f]{32}',key):return jsonify(error='提交标识不正确，请重试'),400
        report=db.get_report(session_id) or {}
        detail=report.get('detail') or {};detail=json.loads(detail) if isinstance(detail,str) else detail
        version=detail.get('scoring_version','legacy-unversioned')
        with db.get_conn() as conn:
            conn.execute('BEGIN IMMEDIATE')
            old=conn.execute('SELECT * FROM reanswers WHERE interview_id=? AND request_id=?',(session_id,key)).fetchone()
            if old:
                if old['answer_sequence']!=seq or old['answer']!=answer.strip():return jsonify(error='该提交标识已用于其他内容'),409
                return jsonify(ok=True,item=dict(old),rescored=False,ai_called=False)
            item=dict(id=uuid.uuid4().hex,interview_id=session_id,answer_sequence=seq,answer=answer.strip(),request_id=key,created_at=db._now(),scoring_version=version)
            conn.execute('INSERT INTO reanswers VALUES (:id,:interview_id,:answer_sequence,:answer,:request_id,:created_at,:scoring_version)',item)
        return jsonify(ok=True,item=item,rescored=False,ai_called=False)
