import sys
import threading
from pathlib import Path
from playwright.sync_api import sync_playwright
sys.path.insert(0, str(Path(__file__).parent))
import test_speech42 as env
from unittest.mock import patch
import json
from test_speech_integration import review_response
from werkzeug.serving import make_server

env.speech.MODEL_NAME = str(next((Path.home() / '.cache/huggingface/hub/models--Systran--faster-whisper-base/snapshots').iterdir()))
env.database.create_interview('isolated-asr','Java 后端','标准')
env.database.add_message('isolated-asr','assistant','请介绍自己','main_question',1)

def cloud_test_double(messages,max_tokens=10000):
    if '"reviews"' in messages[0]['content']:return review_response(messages,max_tokens)
    if 'knowledge_score' in messages[-1]['content']:return json.dumps({'knowledge_score':80,'completeness_score':70,'expression_score':90,'job_relevance_score':60,'weaknesses':[],'suggestions':['测试建议'],'overall_comment':'测试报告'})
    return json.dumps({'comment':'测试点评','next_question':'请介绍项目细节'})

mock_ai=patch.object(env.server,'call_deepseek',side_effect=cloud_test_double)
mock_ai.start()
server = make_server('127.0.0.1', 5009, env.server.app, threaded=True)
threading.Thread(target=server.serve_forever, daemon=True).start()
try:
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True, args=[
            '--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream',
            '--use-file-for-fake-audio-capture=' + str(Path(__file__).parent / 'chinese-fixture.wav')])
        page = browser.new_page()
        page.add_init_script("localStorage.setItem('iv-session', JSON.stringify({session_id:'isolated-asr',job:'Java',level:'标准',question:'请介绍自己',progress:{main:1,total:3}}));")
        answers = []
        page.on('request', lambda r: answers.append(r.url) if '/api/interview/answer' in r.url else None)
        page.goto('http://127.0.0.1:5009/interview')
        page.locator('#micBtn').click()
        page.wait_for_function("document.querySelector('#voiceHint').textContent.includes('正在录音')")
        page.wait_for_timeout(12500)
        page.locator('#micBtn').click()
        page.wait_for_function("document.querySelector('#answerInput').value.length > 0 || document.querySelector('#transcribeStatus').classList.contains('is-error')", timeout=180000)
        text = page.locator('#answerInput').input_value()
        if not text: raise AssertionError(page.locator('#transcribeStatus').inner_text())
        assert '学生' in text or '计算机' in text or '软件' in text, text
        assert not answers
        assert page.locator('#voicePlayer').get_attribute('src').startswith('blob:')
        print('PASS real Edge MediaRecorder -> multipart -> Flask -> faster-whisper CPU -> editable text / no submit')
        assert page.locator('#audioAnalysis').is_visible()
        assert '基频' in page.locator('#audioAnalysisMetrics').inner_text()
        page.locator('#answerInput').fill(text+'（人工编辑测试）')
        page.locator('#submitAnswerBtn').click()
        page.wait_for_function("document.querySelector('#questionText').textContent === '请介绍项目细节'")
        assert len(answers)==1
        entries=env.database.list_speech_analyses('isolated-asr')
        assert len(entries)==1 and entries[0]['message_id']
        assert page.locator('#audioAnalysis').is_hidden()
        page.evaluate('window.scrollTo(0,0)')
        page.locator('#endBtn').click();page.locator('#confirmEndBtn').click()
        page.wait_for_url('**/report?*',timeout=20000)
        page.wait_for_function("document.querySelector('#speechReport').textContent.includes('综合改进建议')")
        assert '修改' in page.locator('#speechReport').inner_text()
        assert '音调变化' in page.locator('#speechReport').inner_text()
        assert '实验性语音情绪模型预测' not in page.locator('#speechReport').inner_text()
        env.server.SESSIONS.clear();page.reload()
        page.wait_for_function("document.querySelector('#speechReport').textContent.includes('综合改进建议')")
        page.wait_for_function("document.querySelector('#scoreNum').textContent === '77'")
        page.screenshot(path=str(Path(__file__).resolve().parents[1]/'docs/speech-report-preview.png'),full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
        print('PASS actual audio metrics -> one-use ID -> edited manual answer -> SQLite -> AI review (mocked) -> persisted report / mobile layout')
        browser.close()
finally:
    mock_ai.stop()
    server.shutdown()
    env.tearDownModule()
