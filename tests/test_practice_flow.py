"""Real queue, mocked provider, isolated database; no external AI traffic."""
import hashlib
import json
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parent))
import test_speech42 as env
from api_guard import install as guard_install, RELAXED_TRIAL_LIMITS
from public_test import install
from report_jobs import ReportJobs

app=env.server.app
app.config.update(SECRET_KEY='isolated-flow-tests', REPORT_JOBS_INLINE=False)
install(app,env.database,daily_starts=None)
calls=[]
provider=lambda *a,**k: None
def fake_ai(*args,**kwargs):
    calls.append(1)
    return provider(*args,**kwargs)
env.server.call_deepseek=fake_ai
guard_install(env.server,env.database,limits=RELAXED_TRIAL_LIMITS)
GRADE=json.dumps(dict(knowledge_score=80,completeness_score=70,expression_score=90,job_relevance_score=60,weaknesses=[],suggestions=['结合案例'],overall_comment='隔离测试报告'))

class FlowTests(unittest.TestCase):
    def setUp(self):
        global provider
        calls.clear();provider=lambda *a,**k:GRADE
        with env.database.get_conn() as conn:conn.execute('DELETE FROM interviews')
        self.client=app.test_client()
        with self.client.session_transaction() as session:session['trial_browser']='owner-test'
        self.seed('flow')

    def seed(self,sid,finish=True):
        db=env.database
        db.create_interview(sid,'Java 后端','校招标准')
        db.add_message(sid,'assistant','请介绍你的项目','main_question',1)
        db.add_message(sid,'user','我负责订单接口','answer',2)
        if finish:db.finish_interview(sid)
        with db.get_conn() as conn:conn.execute('INSERT INTO trial_owners VALUES (?,?)',(sid,hashlib.sha256(b'owner-test').hexdigest()))

    def read(self,sid='flow'):return self.client.get('/api/report/'+sid)
    def wait_status(self,status):
        end=time.monotonic()+6
        while time.monotonic()<end:
            r=self.read()
            if r.status_code==status:return r
            time.sleep(.05)
        self.fail('queue did not reach '+str(status))

    def test_background_survives_page_leave_and_deduplicates(self):
        global provider
        entered=threading.Event();release=threading.Event()
        def slow(*a,**k):entered.set();release.wait(5);return GRADE
        provider=slow
        start=time.monotonic();r=self.read()
        self.assertEqual(r.status_code,202);self.assertLess(time.monotonic()-start,.8)
        self.assertTrue(entered.wait(3))
        for _ in range(3):self.assertEqual(self.read().status_code,202)
        self.assertEqual(len(calls),1)
        release.set()
        # No browser reads are needed for the queued task to finish.
        end=time.monotonic()+5
        while not env.database.get_report('flow') and time.monotonic()<end:time.sleep(.05)
        self.assertIsNotNone(env.database.get_report('flow'))
        self.assertEqual(self.read().status_code,200);self.assertEqual(len(calls),1)

    def test_failure_needs_explicit_retry(self):
        global provider
        def fail(*a,**k):raise env.server.APIError(504,'AI 响应超时，请稍后重试')
        provider=fail
        self.read();self.wait_status(503)
        for _ in range(3):self.assertEqual(self.read().json['reason'],'failed')
        self.assertEqual(len(calls),1)
        provider=lambda *a,**k:GRADE
        r=self.client.post('/api/report/flow/generate',base_url='https://localhost',headers={'Origin':'https://localhost'})
        self.assertIn(r.status_code,(200,202));self.wait_status(200)
        self.assertEqual(len(calls),2)

    def test_lease_recovery_and_claim_are_persistent(self):
        service=ReportJobs(env.database,app,lambda sid:None)
        with env.database.get_conn() as conn:
            conn.execute("INSERT INTO report_jobs(interview_id,state,token,lease_until,updated_at) VALUES ('flow','running','old',0,0)")
        job=service.claim();self.assertEqual(job[0]['interview_id'],'flow')
        second=ReportJobs(env.database,app,lambda sid:None)
        self.assertIsNone(second.claim())
        with env.database.get_conn() as conn:conn.execute("UPDATE report_jobs SET lease_until=0")
        self.assertIsNotNone(second.claim())

    def test_owner_isolation_and_cascade(self):
        other=app.test_client()
        self.assertEqual(other.get('/api/interview/flow/state').status_code,404)
        self.assertEqual(other.get('/api/report/flow').status_code,404)
        self.assertEqual(other.post('/api/report/flow/generate',base_url='https://localhost',headers={'Origin':'https://localhost'}).status_code,404)
        service=ReportJobs(env.database,app,lambda sid:None)
        with env.database.get_conn() as conn:conn.execute("INSERT INTO report_jobs(interview_id,state,updated_at) VALUES ('flow','pending',0)")
        env.database.delete_interview('flow')
        service=ReportJobs(env.database,app,lambda sid:None)
        self.assertIsNone(service.status('flow'))

    def test_active_interview_never_generates_report(self):
        self.seed('active',False)
        self.assertEqual(self.read('active').json['reason'],'not_finished')
        self.assertEqual(self.client.post('/api/report/active/generate',base_url='https://localhost',headers={'Origin':'https://localhost'}).status_code,409)
        self.assertEqual(calls,[])

if __name__=='__main__':unittest.main()
