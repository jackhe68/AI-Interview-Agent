"""Content caching and saved feedback delivery using isolated data, no real AI."""
import hashlib,json,re,sys,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parent))
import test_speech42 as env
from public_test import install
env.server.app.config.update(SECRET_KEY='delivery-test-only',REPORT_JOBS_INLINE=False)
install(env.server.app,env.database,daily_starts=None)
GRADE=json.dumps(dict(knowledge_score=80,completeness_score=70,expression_score=90,job_relevance_score=60,weaknesses=[],suggestions=['结合案例'],overall_comment='隔离报告'))

class DeliveryTests(unittest.TestCase):
 def setUp(self):
  with env.database.get_conn() as conn:conn.execute('DELETE FROM interviews')
  self.client=env.server.app.test_client()
  with self.client.session_transaction() as session:
   session['trial_browser']='delivery-owner';session.permanent=True

 def test_public_assets_use_content_fingerprints_only(self):
  html=self.client.get('/').text
  paths=re.findall(r'(?:src|href)="(/static/[^"?]+\?v=[0-9a-f]{16})"',html)
  self.assertGreaterEqual(len(paths),4)
  for path in paths:
   response=env.server.app.test_client().get(path)
   self.assertEqual(response.headers['Cache-Control'],'public, max-age=31536000, immutable')
   self.assertNotIn('Set-Cookie',response.headers)
   owned=self.client.get(path)
   self.assertNotIn('Set-Cookie',owned.headers)
   wrong=self.client.get(path.split('?')[0]+'?v=old-manual-version')
   self.assertEqual(wrong.headers['Cache-Control'],'no-cache')
   check=self.client.get(path,headers={'If-None-Match':response.headers['ETag']})
   self.assertEqual(check.status_code,304)
   response.close();owned.close();wrong.close();check.close()
  self.assertEqual(self.client.get('/').headers['Cache-Control'],'no-store')
  self.assertEqual(self.client.get('/api/interviews').headers['Cache-Control'],'no-store')

 def test_fingerprint_changes_with_content(self):
  import tempfile
  from flask import Flask
  from asset_delivery import install as assets
  with tempfile.TemporaryDirectory() as folder:
   file=Path(folder)/'sample.css';file.write_text('body{color:red}')
   app=Flask('asset-fixture',static_folder=folder)
   version=assets(app);first=version('sample.css')
   self.assertEqual(first,hashlib.sha256(file.read_bytes()).hexdigest()[:16])
   file.write_text('body{color:blue}')
   self.assertNotEqual(first,version('sample.css'))

 def seed(self):
  db=env.database;db.create_interview('partial','Java 后端','校招标准')
  db.add_message('partial','assistant','请介绍你的项目','main_question',1)
  db.add_message('partial','user','我负责接口 <script>throw 1</script>','answer',2)
  db.add_message('partial','assistant','已保存的点评：请补充职责与结果。','comment',3)
  db.finish_interview('partial')
  with db.get_conn() as conn:conn.execute('INSERT INTO trial_owners VALUES (?,?)',('partial',hashlib.sha256(b'delivery-owner').hexdigest()))

 def test_partial_is_immediate_and_owner_scoped(self):
  self.seed();entered=threading.Event();release=threading.Event()
  def slow(*args,**kwargs):entered.set();release.wait(5);return GRADE
  with patch.object(env.server,'call_deepseek',side_effect=slow) as ai:
   try:
    start=time.monotonic();r=self.client.get('/api/report/partial')
    self.assertEqual(r.status_code,202);self.assertLess(time.monotonic()-start,.8)
    self.assertEqual(r.json['partial'][0]['comment'],'已保存的点评：请补充职责与结果。')
    self.assertTrue(entered.wait(3))
    self.assertEqual(env.server.app.test_client().get('/api/report/partial').status_code,404)
    self.assertEqual(self.client.get('/api/report/partial').json['partial'],r.json['partial'])
   finally:release.set()
   end=time.monotonic()+5
   while not env.database.get_report('partial') and time.monotonic()<end:time.sleep(.05)
   self.assertIsNotNone(env.database.get_report('partial'));self.assertEqual(ai.call_count,1)

 def test_failed_report_keeps_feedback_without_automatic_retry(self):
  self.seed()
  with patch.object(env.server,'call_deepseek',side_effect=env.server.APIError(504,'AI 超时，请稍后重试')) as ai:
   self.client.get('/api/report/partial')
   end=time.monotonic()+5
   while time.monotonic()<end:
    result=self.client.get('/api/report/partial')
    if result.status_code==503:break
    time.sleep(.05)
   self.assertEqual(result.status_code,503)
   self.assertTrue(result.json['partial'][0]['comment'])
   self.client.get('/api/report/partial');self.assertEqual(ai.call_count,1)

if __name__=='__main__':unittest.main()
