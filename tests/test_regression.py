import json
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).parent))
import test_speech42 as env
from score_fixture import with_evidence

client = env.server.app.test_client()
def deepseek(messages, max_tokens=10000):
    if 'knowledge_score' in messages[-1]['content']:
        return json.dumps(with_evidence({'knowledge_score':80,'completeness_score':70,'expression_score':90,'job_relevance_score':60,'weaknesses':[{'topic':'示例','score':50,'explanation':'测试'}],'suggestions':['建议'],'overall_comment':'测试报告'},messages))
    if len(messages) == 2: return '请介绍自己'
    return json.dumps({'comment':'测试点评','next_question':'请介绍下一项技能'})

try:
    with patch.object(env.server, 'call_deepseek', side_effect=deepseek):
        start = client.post('/api/interview/start', json={'job':'Java 后端','level':'校招标准'})
        assert start.status_code == 200
        sid = start.json['session_id']
        for i in range(6):
            r = client.post('/api/interview/answer', json={'session_id':sid,'answer':'测试回答'})
            assert r.status_code == 200, r.json
            assert r.json['finished'] == (i == 5)
        report = client.get('/api/report/' + sid)
        assert report.status_code == 200 and report.json['available']
        assert report.json['scores']['overall'] == 77
        before = report.json['scores']
        env.server.SESSIONS.clear()
        assert client.get('/api/report/' + sid).json['scores'] == before
        assert client.get('/api/interviews').json['total'] == 1
        assert client.post('/api/interview/answer', json={'session_id':sid,'answer':'重复'}).status_code == 409
        assert client.delete('/api/interview/' + sid).status_code == 200
        assert client.get('/api/interviews').json['total'] == 0
        print('PASS isolated SQLite / 3 main + 3 follow-ups / unchanged weighted report / reload / history / delete')
        print('DeepSeek responses mocked; no paid cloud call or production database writes')
finally:
    env.tearDownModule()
