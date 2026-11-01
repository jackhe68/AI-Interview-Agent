from browser_fixture_state import stub_browser_state
"""Practice reports, evidence validation and rendered charts; isolated DB, mocked AI."""
import copy
import json
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
import test_speech42 as env
from practice_feedback import DIMENSIONS

ANSWER = '我会先解释索引原理，再用查询计划检查慢查询，通过增加联合索引验证效果，复盘前后耗时。'
GRADE = dict(knowledge_score=80, completeness_score=70, expression_score=90, job_relevance_score=60,
             weaknesses=[dict(topic='索引取舍', score=55, explanation='未说明新增索引对写入的影响')],
             suggestions=['补充索引维护成本，再用读多写少与写多读少两个场景检查取舍'],
             overall_comment='已说明排查与验证过程，优先补齐索引的写入代价。', knowledge_summary='能说明基本排查流程',
             radar_dimensions=[dict(key=key, score=60+i, answer_sequence=2,
                                    evidence='通过增加联合索引验证效果', reason='结合实际回答评估')
                               for i, (key, _) in enumerate(DIMENSIONS)],
             answer_reviews=[dict(answer_sequence=2, evidence='通过增加联合索引验证效果',
                                  strength='说明了验证方法', gap='没有说明新增索引的维护成本',
                                  answer_outline=['定位慢查询', '检查执行计划', '验证索引的收益与写入代价'],
                                  reference_answer='先收集慢查询与执行计划，再根据过滤和排序选择索引，并对比查询耗时及写入代价。',
                                  practice_task='用一分钟重新回答，补上索引对写入的影响。',
                                  checklist=['说明索引收益', '解释写入维护成本'])])


class PracticeValueTests(unittest.TestCase):
    def setUp(self):
        with env.database.get_conn() as conn:
            conn.execute('DELETE FROM interviews')
        env.server.SESSIONS.clear()
        env.database.create_interview('practice-test', 'Java 后端', '校招标准')
        env.database.add_message('practice-test', 'assistant', '如何排查并优化慢查询？', 'main_question', 1)
        env.database.add_message('practice-test', 'user', ANSWER, 'answer', 2)
        env.database.finish_interview('practice-test', 'ended')
        self.client = env.server.app.test_client()

    def report(self, grade=GRADE):
        with patch.object(env.server, 'call_deepseek', return_value=json.dumps(grade, ensure_ascii=False)):
            response = self.client.get('/api/report/practice-test')
        self.assertEqual(response.status_code, 200, response.json)
        return response.json

    def test_report_links_reviews_and_eight_dimensions_to_actual_answers(self):
        result = self.report()
        self.assertEqual(result['scores']['overall'], 77)
        self.assertEqual(len(result['radar_dimensions']), 8)
        self.assertTrue(all(d['score'] is not None for d in result['radar_dimensions']))
        review = result['answer_reviews'][0]
        self.assertEqual(review['answer'], ANSWER)
        self.assertIn(review['evidence'], ANSWER)
        self.assertEqual(len(review['answer_outline']), 3)
        self.assertIn('维护成本', review['checklist'][1])
        env.server.SESSIONS.clear()
        with patch.object(env.server, 'call_deepseek', side_effect=AssertionError('saved reports must be reused')):
            self.assertEqual(self.client.get('/api/report/practice-test').json, result)

    def test_invented_evidence_and_unanswered_questions_are_not_displayed(self):
        grade = copy.deepcopy(GRADE)
        for dimension in grade['radar_dimensions']:
            dimension['evidence'] = '这不是候选人的回答'
        grade['answer_reviews'].append(dict(grade['answer_reviews'][0], answer_sequence=999))
        result = self.report(grade)
        self.assertTrue(all(d['score'] is None for d in result['radar_dimensions'][4:]))
        self.assertEqual(len(result['answer_reviews']), 1)

    def test_zero_is_observed_but_missing_boolean_and_out_of_range_scores_are_not(self):
        grade = copy.deepcopy(GRADE)
        for dimension, value in zip(grade['radar_dimensions'][4:], [0, None, True, 101]):
            dimension['score'] = value
        result = self.report(grade)
        self.assertEqual([d['score'] for d in result['radar_dimensions'][4:]], [0, None, None, None])

    def test_legacy_reports_keep_their_scores_without_fabricated_new_dimensions(self):
        grade = {key: value for key, value in GRADE.items() if key not in ('radar_dimensions', 'answer_reviews')}
        result = self.report(grade)
        self.assertEqual(result['scores']['overall'], 77)
        self.assertEqual([d['score'] for d in result['radar_dimensions'][4:]], [None]*4)
        self.assertNotIn('reference_answer', result['answer_reviews'][0])

    def test_reference_is_deferred_until_followup_is_over(self):
        session = dict(id='practice-test', job='Java 后端', level='校招标准', main_index=0,
                       history=[dict(role='assistant', content='问题'), dict(role='user', content=ANSWER)])
        reply = dict(comment='缺少索引写入成本', next_step='请解释选型取舍', next_question='写入有什么影响？',
                     answer_outline=['解释原理', '说明代价'], reference_answer='索引需要维护，会增加写入开销。')
        with patch.object(env.server, 'call_deepseek', return_value=json.dumps(reply)):
            followup, _ = env.server.ask_next(session, 'followup')
            complete, _ = env.server.ask_next(session, 'next_main')
        self.assertNotIn('参考回答', followup)
        self.assertIn('参考回答', complete)
        self.assertIn('回答思路', complete)

    def test_grading_does_not_treat_ai_reference_solutions_as_candidate_answers(self):
        hint = '参考回答：这是AI生成的完整答案，不是候选人作答。'
        env.database.add_message('practice-test', 'assistant', hint, 'comment', 3)
        with patch.object(env.server, 'call_deepseek', return_value=json.dumps(GRADE)) as ai:
            result = self.client.get('/api/report/practice-test')
        self.assertEqual(result.status_code, 200)
        prompt = ai.call_args.args[0][-1]['content']
        self.assertIn(ANSWER, prompt)
        self.assertNotIn(hint, prompt)

    def test_invalid_ai_response_does_not_commit_answer_or_finish_interview(self):
        env.database.create_interview('active-practice', 'Java 后端', '校招标准')
        env.database.add_message('active-practice', 'assistant', '请介绍索引', 'main_question', 1)
        with patch.object(env.server, 'call_deepseek', return_value='invalid json'):
            result = self.client.post('/api/interview/answer', json=dict(session_id='active-practice', answer=ANSWER))
        self.assertEqual(result.status_code, 502)
        self.assertEqual(len(env.database.get_messages('active-practice')), 1)
        self.assertEqual(env.database.get_interview('active-practice')['status'], 'active')

    def test_browser_radar_labels_survive_animation_and_feedback_stays_visible(self):
        from playwright.sync_api import sync_playwright
        from waitress import create_server
        payload = self.report()
        payload['answer_reviews'][0]['reference_answer'] += '<img src=x onerror=alert(1)>'
        http = create_server(env.server.app, host='127.0.0.1', port=0, threads=4)
        thread = threading.Thread(target=http.run, daemon=True)
        thread.start()
        base = 'http://127.0.0.1:' + str(http.effective_port)
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)
                try:
                    for width in [1280, 390]:
                        page = browser.new_page(viewport=dict(width=width, height=900))
                        stub_browser_state(page)
                        errors = []
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        page.add_init_script('''window.radarLabels=[];
                            const clear=CanvasRenderingContext2D.prototype.clearRect;
                            CanvasRenderingContext2D.prototype.clearRect=function(...a){window.radarLabels=[];return clear.apply(this,a)};
                            const fill=CanvasRenderingContext2D.prototype.fillText;
                            CanvasRenderingContext2D.prototype.fillText=function(t,...a){window.radarLabels.push(t);return fill.call(this,t,...a)};''')
                        page.route('**/api/report/practice-test', lambda route: route.fulfill(status=200, json=payload))
                        page.goto(base+'/report?id=practice-test', wait_until='networkidle')
                        page.wait_for_function("document.querySelector('#scoreNum').textContent === '77'")
                        self.assertEqual(page.locator('.radar-value').count(), 8)
                        for _, label in DIMENSIONS:
                            self.assertIn(label, page.evaluate('window.radarLabels'))
                        # Observe the plotted area itself, beyond labels/DOM text.
                        pixel = page.evaluate('''() => {
                            const c=document.querySelector('#radarChart'), r=c.getBoundingClientRect(), d=window.devicePixelRatio;
                            const radius=Math.min(r.width,r.height)/2-72;
                            return Array.from(c.getContext('2d').getImageData(Math.floor(r.width/2*d),Math.floor((r.height/2-radius*.35)*d),1,1).data);
                        }''')
                        self.assertGreater(pixel[2]-pixel[0], 15, 'Radar must contain a visible data polygon, not just a grid')
                        self.assertEqual(page.locator('.reference-answer img').count(), 0)
                        self.assertIn('一分钟', page.locator('#reviewList').inner_text())
                        self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'))
                        if width == 390:
                            shot = Path(__file__).parents[1] / 'docs' / 'practice-value-mobile-preview.png'
                            page.screenshot(path=str(shot), full_page=True)
                        # Missing observations must be visible as missing, while a genuine zero stays zero.
                        mixed = copy.deepcopy(payload)
                        mixed['radar_dimensions'][4]['score'] = 0
                        mixed['radar_dimensions'][5]['score'] = None
                        page.unroute('**/api/report/practice-test')
                        page.route('**/api/report/practice-test', lambda route: route.fulfill(status=200, json=mixed))
                        page.locator('#refreshBtn').click()
                        page.wait_for_function("document.querySelector('#radarNote').textContent.includes('7/8')")
                        self.assertIn('0 / 100', page.locator('.radar-value').nth(4).inner_text())
                        self.assertIn('未评估', page.locator('.radar-value').nth(5).inner_text())
                        page.evaluate("localStorage.setItem('iv-session',JSON.stringify({session_id:'test',job:'Java 后端',level:'校招标准',question:'如何排查慢查询？',progress:{main:1,total:3,type:'main'}}))")
                        page.route('**/api/interview/answer', lambda route: route.fulfill(status=200, json=dict(comment='先说明排查步骤，再说明验证方式。', next_question='如何验证索引效果？', finished=False, progress=dict(main=1,total=3,type='followup'))))
                        page.goto(base+'/interview', wait_until='networkidle')
                        page.locator('#answerInput').fill(ANSWER)
                        page.locator('#submitAnswerBtn').click()
                        page.wait_for_function("document.querySelector('#questionText').textContent.includes('如何验证索引效果')")
                        self.assertTrue(page.locator('#aiFeedback').is_visible())
                        self.assertFalse(page.locator('#aiFeedback').evaluate('(node)=>node.open'))
                        page.locator('#feedbackSummary').click()
                        self.assertIn('排查步骤', page.locator('#feedbackBody').inner_text())
                        self.assertEqual(errors, [])
                        page.close()
                finally:
                    browser.close()
        finally:
            http.close()
            http.task_dispatcher.shutdown()
            thread.join(timeout=3)


if __name__ == '__main__':
    try:
        unittest.main(verbosity=2)
    finally:
        env.tearDownModule()
