"""Coverage/evidence contracts; fictional cases are not model accuracy measurements."""
import copy,json,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parent))
import test_accounts as account
from score_fixture import with_evidence
env=account.env;app=env.server.app
BASE=account.BASE

class CoverageTests(unittest.TestCase):
 def setUp(self):
  with env.database.get_conn() as c:c.execute('DELETE FROM interviews');c.execute('DELETE FROM start_requests')
  env.server.SESSIONS.clear();self.client=app.test_client()
 def seed(self,answers):
  with patch.object(env.server,'call_deepseek',return_value='如何保证事务与重试可靠？'):
   sid=account.send(self.client,'/api/interview/start',dict(job='Java 后端',level='校招标准')).json['session_id']
  for i,answer in enumerate(answers):
   if i:env.database.add_message(sid,'assistant','虚构问题'+str(i),'main_question' if i%2==0 else 'followup',2*i+1)
   env.database.add_message(sid,'user',answer,'answer',2*i+2)
  env.database.finish_interview(sid)
  return sid
 def payload(self):return dict(knowledge_score=80,completeness_score=70,expression_score=90,job_relevance_score=60,weaknesses=[],suggestions=['虚构训练建议'],overall_comment='虚构反馈')
 def report(self,sid,data):
  token=account.session(self.client)['csrf_token']
  with patch.object(env.server,'call_deepseek',return_value=json.dumps(data,ensure_ascii=False)):
   response=self.client.get('/api/report/'+sid,base_url=BASE,headers={'X-CSRF-Token':token})
  self.assertEqual(response.status_code,200,response.json);return response.json
 def test_one_real_answer_and_five_skips_do_not_claim_complete_coverage(self):
  sid=self.seed(['先验证输入，再保存结果']+['（候选人选择跳过此题）']*5)
  result=self.report(sid,with_evidence(self.payload(),answer='先验证输入，再保存结果'))
  self.assertIn('1次有效回答',result['confidence_note']);self.assertIn('5次跳过',result['confidence_note']);self.assertIn('1/3',result['confidence_note'])
  coverage=env.database.get_report(sid)['detail']['coverage']
  self.assertEqual(coverage,dict(attempts=6,effective_answers=1,skipped=5,main_topics_covered=1))
 def test_missing_evidence_is_unassessed_in_report_and_history(self):
  sid=self.seed(['先验证输入，再保存结果'])
  data=self.payload();data['overall_comment']='虚构的无依据断言：你已经精通所有岗位知识'
  result=self.report(sid,data)
  self.assertTrue(all(value is None for value in result['scores'].values()))
  self.assertNotIn('精通所有岗位',result['overall_comment'])
  self.assertTrue(all(d['score'] is None for d in result['radar_dimensions']))
  item=self.client.get('/api/interviews',base_url=BASE).json['items'][0]
  self.assertIsNone(item['overall_score']);self.assertTrue(item['has_report'])
 def test_partial_observations_do_not_rescale_weights_or_invent_a_total(self):
  sid=self.seed(['先验证输入，再保存结果'])
  data=with_evidence(self.payload(),answer='先验证输入，再保存结果')
  data['radar_dimensions']=data['radar_dimensions'][:1]
  result=self.report(sid,data)
  self.assertEqual(result['scores']['knowledge'],80);self.assertIsNone(result['scores']['expression']);self.assertIsNone(result['scores']['overall'])
 def test_skip_placeholder_cannot_support_a_low_ability_claim(self):
  sid=self.seed(['先验证输入，再保存结果','（候选人选择跳过此题）'])
  data=self.payload();data['radar_dimensions']=[dict(key='knowledge',score=80,answer_sequence=4,evidence='候选人选择跳过此题',reason='虚构不支持的理由')]
  result=self.report(sid,data);self.assertIsNone(result['scores']['knowledge']);self.assertIsNone(result['scores']['overall'])
 def test_skip_keeps_learning_reference_without_unsupported_ability_feedback(self):
  sid=self.seed(['先验证输入，再保存结果','（候选人选择跳过此题）'])
  data=self.payload();data['answer_reviews']=[dict(answer_sequence=4,evidence='候选人选择跳过此题',
   strength='虚构的能力断言',gap='虚构的低能力判断',reference_answer='先说明原子性，再说明回滚边界。')]
  result=self.report(sid,data)
  review=next(r for r in result['answer_reviews'] if r['answer_sequence']==4)
  self.assertIn('原子性',review['reference_answer']);self.assertNotIn('低能力',review['gap']);self.assertIn('未评估',review['gap'])
 def test_live_skip_feedback_is_neutral_even_if_model_uses_an_unsupported_claim(self):
  sid=self.seed([])
  # Seed left this synthetic record ended; create a fresh active record for the API turn.
  with patch.object(env.server,'call_deepseek',return_value='虚构首题'):
   sid=account.send(self.client,'/api/interview/start',dict(job='Java 后端',level='校招标准')).json['session_id']
  with patch.object(env.server,'call_deepseek',return_value=json.dumps(dict(comment='虚构的低能力判断',next_step='虚构的能力问题',next_question='请解释下一点'))):
   response=account.send(self.client,'/api/interview/answer',dict(session_id=sid,answer='（候选人选择跳过此题）'))
  self.assertEqual(response.status_code,200);self.assertNotIn('低能力',response.json['comment']);self.assertNotIn('能力问题',response.json['comment'])
 def test_all_skips_and_empty_legacy_answers_do_not_call_ai(self):
  for answer in ('（候选人选择跳过此题）','   '):
   sid=self.seed([answer])
   token=account.session(self.client)['csrf_token']
   with patch.object(env.server,'call_deepseek') as ai:
    response=self.client.get('/api/report/'+sid,base_url=BASE,headers={'X-CSRF-Token':token});ai.assert_not_called()
   self.assertEqual(response.status_code,200);self.assertIsNone(response.json['scores']['overall'])
 def test_explicit_null_is_a_supported_unobserved_core_field(self):
  sid=self.seed(['先验证输入，再保存结果'])
  data=with_evidence(self.payload(),answer='先验证输入，再保存结果');data['knowledge_score']=None
  data['radar_dimensions']=[d for d in data['radar_dimensions'] if d['key']!='knowledge']
  result=self.report(sid,data);self.assertIsNone(result['scores']['knowledge']);self.assertEqual(result['scores']['expression'],90)
 def test_fixed_answer_categories_preserve_the_input_without_claiming_accuracy(self):
  cases=json.loads((Path(__file__).parent/'scoring_cases.json').read_text(encoding='utf-8'))
  self.assertEqual(len(cases),9)
  for case in cases:
   with self.subTest(category=case['name']):
    sid=self.seed([case['answer']])
    stored=env.database.get_messages(sid)[1]['content'];self.assertEqual(stored,case['answer'])
    if not stored.strip():continue
    # Missing model evidence must remain unassessed for every answer category.
    result=self.report(sid,self.payload());self.assertIsNone(result['scores']['overall'])

if __name__=='__main__':
 try:unittest.main(verbosity=2)
 finally:env.tearDownModule()
