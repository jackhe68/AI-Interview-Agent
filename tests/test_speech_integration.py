import copy
import hashlib
import io
import json
import sqlite3
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parent))
import test_speech42 as env
import audio_analysis as audio
import speech_review

def sample_analysis():
    from faster_whisper.vad import get_vad_model
    get_vad_model()
    result=audio.analyze_audio(Path(__file__).parent/'chinese-fixture.wav','你好世界')
    assert result['status'] in ('ok','partial'),result
    return result

def review_response(messages,max_tokens=10000):
    data=json.loads(messages[-1]['content'])
    return json.dumps({'reviews':[dict(id=item['id'],
        content={key:{'comment':'表达可进一步结合具体示例。','evidence':item['answer'][:4]} for key in speech_review.CONTENT_KEYS},
        voice_observations=[{'metric':'pause_count','comment':'结合问题结构检查停顿位置，不必完全消除停顿。'}],
        suggestions=['先概括观点，再展开技术细节。']) for item in data['answers']]})

class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.analysis=sample_analysis()

    def setUp(self):
        self.client=env.server.app.test_client()
        env.server.SESSIONS.clear()
        # This test module always uses the isolated DB selected before app import.
        assert env.database.DB_PATH != str(env.ROOT/'interviews.db')
        with env.database.get_conn() as conn: conn.execute('DELETE FROM interviews')
        for sid in ['session-one','session-two']:
            env.database.create_interview(sid,'Java 后端','标准')
            env.database.add_message(sid,'assistant','请介绍自己','main_question',1)

    def upload(self, sid='session-one'):
        with patch.object(env.speech,'transcribe',return_value=('你好世界',10)),patch.object(audio,'analyze_audio',return_value=copy.deepcopy(self.analysis)):
            return self.client.post('/api/speech/transcribe',data={
                'audio':(io.BytesIO(b'fake-container'),'recording.webm'),
                'include_analysis':'true','session_id':sid,'question':'请介绍自己'})

    def answer(self, aid, sid='session-one', text='你好世界'):
        with patch.object(env.server,'ask_next',return_value=('点评','请说明项目细节')):
            return self.client.post('/api/interview/answer',json={'session_id':sid,'answer':text,'analysis_id':aid,
                                                                 'analysis':{'metrics':{'pause_count':99999}}})

    def test_secure_single_use_edited_answer_history(self):
        result=self.upload();self.assertEqual(result.status_code,200)
        aid=result.json['analysis_id']
        self.assertTrue(env.database.get_pending_speech(aid,'session-one'))
        self.assertIsNone(env.database.get_pending_speech(aid,'session-two'))
        self.assertEqual(self.answer(aid,'session-two').status_code,409)
        self.assertEqual(self.answer(aid,text='手动编辑后的回答').status_code,200)
        entries=env.database.list_speech_analyses('session-one')
        self.assertEqual(len(entries),1)
        self.assertEqual(entries[0]['answer'],'手动编辑后的回答')
        self.assertEqual(entries[0]['analysis']['metrics']['pause_count'],self.analysis['metrics']['pause_count'])
        self.assertEqual(self.answer(aid).status_code,409)
        self.assertTrue(speech_review.report_entries(entries)[0]['answer_edited_after_asr'])
        self.assertEqual(env.database.list_speech_analyses('session-two'),[])

    def test_ai_failure_rolls_back_and_analysis_can_retry(self):
        aid=self.upload().json['analysis_id']
        before=len(env.database.get_messages('session-one'))
        with patch.object(env.server,'ask_next',side_effect=env.server.APIError(502,'服务暂不可用')):
            response=self.client.post('/api/interview/answer',json={'session_id':'session-one','answer':'你好世界','analysis_id':aid})
        self.assertEqual(response.status_code,502)
        self.assertEqual(len(env.database.get_messages('session-one')),before)
        self.assertTrue(env.database.get_pending_speech(aid,'session-one'))
        self.assertEqual(self.answer(aid).status_code,200)

    def test_expiry_and_changed_question(self):
        aid=self.upload().json['analysis_id']
        with env.database.get_conn() as conn:
            conn.execute('UPDATE speech_analyses SET expires_at=? WHERE id=?',(time.time()-1,aid))
        self.assertEqual(self.answer(aid).status_code,409)
        aid=self.upload().json['analysis_id']
        env.database.add_message('session-one','assistant','不同的新问题','main_question',2)
        self.assertEqual(self.answer(aid).status_code,409)
        self.assertEqual(self.upload().status_code,409)

    def test_analysis_failure_keeps_transcript_and_cleanup(self):
        paths=[]
        def transcribe(path): paths.append(path);return '文字成功',1
        with patch.object(env.speech,'transcribe',side_effect=transcribe),patch.object(audio,'analyze_audio',side_effect=RuntimeError('PRIVATE_CONFIG')):
            result=self.client.post('/api/speech/transcribe',data={'audio':(io.BytesIO(b'audio'),'rec.webm'),'include_analysis':'true'})
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json['text'],'文字成功')
        self.assertEqual(result.json['analysis']['status'],'unavailable')
        self.assertNotIn('PRIVATE_CONFIG',result.get_data(as_text=True))
        self.assertFalse(Path(paths[0]).exists())

    def test_review_persistence_retry_and_cascade(self):
        aid=self.upload().json['analysis_id'];self.answer(aid)
        env.database.finish_interview('session-one','ended')
        with patch.object(env.server,'call_deepseek',side_effect=review_response):
            result=self.client.post('/api/report/session-one/speech-review')
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json['speech_analyses'][0]['feedback']['status'],'ok')
        env.server.SESSIONS.clear()
        with patch.object(env.server,'call_deepseek',side_effect=AssertionError('must reuse review')):
            self.assertEqual(self.client.post('/api/report/session-one/speech-review').status_code,200)
        self.assertTrue(env.database.list_speech_analyses('session-one')[0]['feedback'])
        self.client.delete('/api/interview/session-one')
        with env.database.get_conn() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM speech_analyses WHERE id=?',(aid,)).fetchone()[0],0)

    def test_review_rejects_fabricated_numbers_and_missing_values(self):
        entry={'id':'x','answer':'你好世界','question':'问题','analysis':copy.deepcopy(self.analysis)}
        base=json.loads(review_response([{'content':json.dumps({'answers':[entry]})}]))['reviews'][0]
        base['voice_observations'][0]['comment']='你的停顿是999秒'
        with self.assertRaises(ValueError):speech_review.validate_review(base,entry)
        base['voice_observations']=[{'metric':'f0_hz_median','comment':'音高可以参考。'}]
        entry['analysis']['metrics']['f0_hz_median']=None
        with self.assertRaises(ValueError):speech_review.validate_review(base,entry)

    def test_migration_is_additive_and_repeatable(self):
        before={name:[tuple(row) for row in env.database.get_conn().execute('SELECT * FROM '+name)] for name in ['interviews','messages','reports']}
        env.database.init_db();env.database.init_db()
        for name,rows in before.items():
            with env.database.get_conn() as conn:self.assertEqual([tuple(row) for row in conn.execute('SELECT * FROM '+name)],rows)

if __name__=='__main__':
    try:unittest.main(verbosity=2)
    finally:env.tearDownModule()
