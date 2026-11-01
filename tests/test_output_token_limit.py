import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parent))
import test_speech42 as env
from ai_limits import MAX_OUTPUT_TOKENS
from speech_review import generate_reviews, CONTENT_KEYS

class TokenTests(unittest.TestCase):
    def setUp(self):
        self.calls=[];self.finish='stop'
        with env.database.get_conn() as conn:conn.execute('DELETE FROM interviews')
        env.server.SESSIONS.clear()
        self.client=env.server.app.test_client()
        def create(**kwargs):
            self.calls.append(kwargs)
            messages=kwargs['messages']
            if '"reviews"' in messages[0]['content']:
                entry=json.loads(messages[-1]['content'])['answers'][0]
                content=json.dumps({'reviews':[dict(id=entry['id'],content={k:{'comment':'表达清楚','evidence':'测试回答'} for k in CONTENT_KEYS},voice_observations=[],suggestions=['可以进一步结合案例。'])]})
            elif 'knowledge_score' in messages[-1]['content']:
                content=json.dumps({'knowledge_score':80,'completeness_score':70,'expression_score':90,'job_relevance_score':60,'weaknesses':[],'suggestions':['建议'],'overall_comment':'总结'})
            elif len(messages)==2:content='请介绍自己'
            else:content=json.dumps({'comment':'点评','next_question':'请介绍项目'})
            return SimpleNamespace(choices=[SimpleNamespace(finish_reason=self.finish,message=SimpleNamespace(content=content))])
        fake=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        self.patch=patch.object(env.server,'client',fake);self.patch.start()

    def tearDown(self):self.patch.stop()

    def test_all_dispatches_use_10000(self):
        self.assertEqual(MAX_OUTPUT_TOKENS,10000)
        sid=self.client.post('/api/interview/start',json={'job':'Java 后端','level':'校招标准'}).json['session_id']
        self.assertEqual(self.client.post('/api/interview/answer',json={'session_id':sid,'answer':'测试回答'}).status_code,200)
        self.assertEqual(self.client.post('/api/interview/end',json={'session_id':sid}).status_code,200)
        self.assertTrue(self.client.get('/api/report/'+sid).json['available'])
        entry={'id':'test','question':'问题','answer':'测试回答','analysis':{'metrics':{},'quality':{}},'feedback':None}
        result=generate_reviews({'job':'Java 后端','difficulty':'校招标准'},[entry],[],env.server.call_deepseek)
        self.assertEqual(result['test']['status'],'ok')
        self.assertEqual(len(self.calls),4)
        self.assertTrue(all(call['max_tokens']==10000 for call in self.calls))

    def test_truncated_reply_does_not_end_interview(self):
        sid=self.client.post('/api/interview/start',json={'job':'Java 后端','level':'校招标准'}).json['session_id']
        self.finish='length'
        result=self.client.post('/api/interview/answer',json={'session_id':sid,'answer':'测试回答'})
        self.assertEqual(result.status_code,502)
        self.assertIn('长度上限',result.json['error'])
        self.assertFalse(env.server.SESSIONS[sid]['finished'])
        self.assertEqual(len(env.database.get_messages(sid)),1)

if __name__=='__main__':
    try:unittest.main(verbosity=2)
    finally:env.tearDownModule()
