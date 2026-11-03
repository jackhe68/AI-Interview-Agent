"""Report contracts are validated with fictional model outputs, not accuracy claims."""
import copy,json,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parent))
import test_speech42 as env
from practice_feedback import normalize_practice,report_practice

class ScoreTests(unittest.TestCase):
 def setUp(self):
  with env.database.get_conn() as c:c.execute('DELETE FROM interviews')
  env.server.SESSIONS.clear();self.sid='fictional-score-contract'
  env.database.create_interview(self.sid,'Java 后端','校招标准')
  env.database.add_message(self.sid,'assistant','如何处理虚构输入？','main_question',1)
  env.database.add_message(self.sid,'user','先验证输入，再保存结果。','answer',2)
  env.database.finish_interview(self.sid)
  self.messages=env.database.get_messages(self.sid)
  self.data=dict(knowledge_score=80,completeness_score=70,expression_score=90,job_relevance_score=60,
   weaknesses=[],suggestions=['虚构改进建议'],overall_comment='虚构契约测试',
   radar_dimensions=[dict(key=key,score=value,answer_sequence=2,evidence='先验证输入',reason='虚构评分理由')
                     for key,value in [('knowledge',80),('completeness',70),('expression',90),('job_relevance',60)]])
 def generate(self,data):
  with patch.object(env.server,'call_deepseek',return_value=json.dumps(data,ensure_ascii=False)):
   return env.server.generate_report(self.sid)
 def test_conflicting_scores_reject_the_report_without_changing_answers(self):
  self.data['radar_dimensions'][0]['score']=10
  with self.assertRaises(env.server.APIError) as raised:self.generate(self.data)
  self.assertEqual(raised.exception.code,502);self.assertIsNone(env.database.get_report(self.sid))
  self.assertEqual(env.database.get_messages(self.sid),self.messages)
 def test_duplicate_observed_dimension_is_not_silently_overwritten(self):
  self.data['radar_dimensions'].append(copy.deepcopy(self.data['radar_dimensions'][0]))
  with self.assertRaises(env.server.APIError):self.generate(self.data)
  self.assertIsNone(env.database.get_report(self.sid))
 def test_consistent_report_retains_existing_weighted_total_and_version(self):
  result=self.generate(self.data)
  self.assertEqual(result['overall_score'],77)
  self.assertEqual(result['detail']['scoring_version'],'practice-v4-evidence')
  shown=report_practice(result,self.messages)['radar_dimensions'][0]
  self.assertEqual(shown['score'],80);self.assertEqual(shown['reason'],'虚构评分理由')
 def test_invalid_core_scores_cannot_be_saved(self):
  for value in (True,None,-1,101,float('inf'),float('nan'),'80'):
   with self.subTest(value=repr(value)):
    data=copy.deepcopy(self.data);data['knowledge_score']=value
    with self.assertRaises(env.server.APIError):self.generate(data)
  self.assertIsNone(env.database.get_report(self.sid))
 def test_observed_zero_and_hundred_are_not_treated_as_missing(self):
  for value in (0,100):
   data=copy.deepcopy(self.data);data['knowledge_score']=value;data['radar_dimensions'][0]['score']=value
   detail=normalize_practice(data,self.messages)
   self.assertEqual(detail['radar_dimensions']['knowledge']['score'],value)
 def test_old_contradictory_reason_is_disclosed_without_rewriting_saved_report(self):
  result=self.generate(self.data)
  result['detail']['scoring_version']='legacy-fixture'
  result['detail']['radar_dimensions']['knowledge']['score']=10
  env.database.save_report(result)
  before=env.database.get_report(self.sid)
  shown=env.server.report_to_json(self.sid,allow_generate=False)[0]
  self.assertEqual(shown['scores']['knowledge'],80)
  self.assertIn('历史维度说明',shown['radar_dimensions'][0]['reason'])
  self.assertEqual(env.database.get_report(self.sid),before)

if __name__=='__main__':
 try:unittest.main(verbosity=2)
 finally:env.tearDownModule()
