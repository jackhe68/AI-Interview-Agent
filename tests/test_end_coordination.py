"""End and answer transitions cannot discard an in-flight answer across tabs."""
import json,sys,threading,unittest,uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parent))
import test_accounts as account
env=account.env;app=env.server.app

class EndTests(unittest.TestCase):
 def setUp(self):
  with env.database.get_conn() as c:c.execute('DELETE FROM interviews');c.execute('DELETE FROM start_requests')
  env.server.SESSIONS.clear();self.a=app.test_client();self.b=app.test_client()
  with patch.object(env.server,'call_deepseek',return_value='虚构首题'):
   self.sid=account.send(self.a,'/api/interview/start',dict(job='Java 后端',level='校招标准')).json['session_id']
  cookie=self.a.get_cookie(app.config['SESSION_COOKIE_NAME'],domain='accounts.test')
  self.b.set_cookie(app.config['SESSION_COOKIE_NAME'],cookie.value,domain='accounts.test')
 def answer(self,client=None):
  return account.send(client or self.a,'/api/interview/answer',dict(session_id=self.sid,answer='虚构回答',request_id=uuid.uuid4().hex,question_sequence=1))
 def end(self,client=None):return account.send(client or self.b,'/api/interview/end',dict(session_id=self.sid))
 def test_other_tab_cannot_end_until_inflight_answer_is_saved(self):
  entered=threading.Event();release=threading.Event()
  def provider(*args,**kwargs):entered.set();self.assertTrue(release.wait(8));return json.dumps(dict(comment='虚构点评',next_question='虚构追问'))
  with patch.object(env.server,'call_deepseek',side_effect=provider) as ai:
   with ThreadPoolExecutor(max_workers=1) as pool:
    future=pool.submit(self.answer)
    try:
     self.assertTrue(entered.wait(5));ended=self.end()
     self.assertEqual(ended.status_code,409);self.assertEqual(ended.json['code'],'answer_in_progress')
     self.assertEqual(env.database.get_interview(self.sid)['status'],'active')
    finally:release.set()
    self.assertEqual(future.result(10).status_code,200)
   self.assertEqual(ai.call_count,1)
  self.assertEqual(sum(m['role']=='user' for m in env.database.get_messages(self.sid)),1)
  self.assertEqual(self.end().status_code,200);self.assertEqual(env.database.get_interview(self.sid)['status'],'ended')
 def test_end_first_blocks_new_answer_without_ai_dispatch(self):
  self.assertEqual(self.end().status_code,200)
  with patch.object(env.server,'call_deepseek') as ai:
   self.assertEqual(self.answer().status_code,409);ai.assert_not_called()
 def test_repeated_end_after_memory_reset_preserves_original_end_time(self):
  self.assertEqual(self.end().status_code,200)
  first=env.database.get_interview(self.sid)['ended_at'];env.server.SESSIONS.clear()
  with patch.object(env.database,'finish_interview') as finish:
   self.assertEqual(self.end().status_code,200);finish.assert_not_called()
  self.assertEqual(env.database.get_interview(self.sid)['ended_at'],first)
 def test_failed_end_keeps_the_interview_open_for_a_retry_or_answer(self):
  with patch.object(env.database,'finish_interview',side_effect=OSError('fictional write failure')):
   self.assertEqual(self.end().status_code,503)
  self.assertFalse(env.server.SESSIONS[self.sid]['finished'])
  with patch.object(env.server,'call_deepseek',return_value=json.dumps(dict(comment='虚构点评',next_question='虚构追问'))):
   self.assertEqual(self.answer().status_code,200)
  self.assertEqual(self.end().status_code,200)

if __name__=='__main__':
 try:unittest.main(verbosity=2)
 finally:env.tearDownModule()
