from browser_fixture_state import stub_browser_state
import sys
import threading
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright
sys.path.insert(0, str(Path(__file__).parent))
import test_speech42 as env
from werkzeug.serving import make_server

MOCK = r'''(() => {
window.recorders = []; window.stoppedTracks = 0;
navigator.mediaDevices.getUserMedia = async () => {
 if (window.permissionError) throw {name: window.permissionError};
 if (window.delayPermission) await new Promise(r => window.grantPermission = r);
 return {getTracks: () => [{stop: () => window.stoppedTracks++}]};
};
window.MediaRecorder = class {
 static isTypeSupported() { return true; }
 constructor() { this.mimeType = 'audio/webm'; this.state = 'inactive'; window.recorders.push(this); }
 start() { this.state = 'recording'; }
 stop() { this.state = 'inactive'; setTimeout(() => {
   this.ondataavailable({data: new Blob([window.emptyAudio ? '' : 'FINAL_AUDIO'], {type: this.mimeType})});
   this.onstop();
 }, 100); }
};
})();'''

def run():
    http = make_server('127.0.0.1', 5009, env.server.app, threaded=True)
    threading.Thread(target=http.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)
            page = browser.new_page()
            stub_browser_state(page)
            page.add_init_script("localStorage.setItem('iv-session', JSON.stringify({session_id:'test-session',job:'Java',level:'标准',question:'请介绍自己',progress:{main:1,total:3}}));")
            page.add_init_script(MOCK)
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            uploads = []
            pending = []
            mode = ['success']
            answers = []
            def speech(route):
                uploads.append(route.request.post_data_buffer)
                if mode[0] == 'pending': pending.append(route); return
                if mode[0] == 'network': route.abort(); return
                if mode[0] == 'null': route.fulfill(status=200, body='null', content_type='application/json'); return
                route.fulfill(status=422 if mode[0] == 'silence' else 200, json={'success': mode[0] != 'silence', 'text': '语音回答', 'error': '未识别到语音内容'})
            page.route('**/api/speech/transcribe', speech)
            def answer(route):
                answers.append(route.request.post_data_json)
                route.fulfill(status=502 if mode[0] == 'answerfail' else 200, json={'error':'测试失败', 'comment':'点评', 'next_question':'下一题', 'progress':{'main':2,'total':3}})
            page.route('**/api/interview/answer', answer)
            page.goto('http://127.0.0.1:5009/interview')
            def recording():
                page.locator('#micBtn').click()
                page.wait_for_function("recorders.length && recorders[recorders.length-1].state === 'recording'")
            def stop():
                page.locator('#micBtn').click()
            recording(); stop()
            assert len(uploads) == 0, 'must await final blob'
            page.wait_for_function("document.querySelector('#answerInput').value === '语音回答'")
            assert len(uploads) == 1 and b'FINAL_AUDIO' in uploads[0] and not answers
            assert page.evaluate("Object.keys(localStorage).filter(k=>k.startsWith('iv-answer-draft-v1:')).some(k=>JSON.parse(localStorage.getItem(k)).text==='语音回答')"), 'ASR text must be saved as a draft'
            assert page.locator('#voicePlayer').get_attribute('src').startswith('blob:')
            print('PASS final blob / auto ASR / playback / no auto submit')
            mode[0] = 'pending'
            page.locator('#transcribeBtn').click()
            page.wait_for_function("document.querySelector('#submitAnswerBtn').disabled")
            page.locator('#answerInput').fill('手动编辑')
            page.locator('#answerInput').press('Control+Enter')
            assert len(uploads) == 2 and not answers
            # 重新录音可中止旧识别；旧响应不得覆盖新草稿。
            page.locator('#redoBtn').click()
            page.wait_for_function("recorders[recorders.length-1].state === 'recording'")
            try: pending.pop().fulfill(json={'success':True,'text':'旧结果'})
            except Exception: pass
            assert page.locator('#answerInput').input_value() == '手动编辑'
            mode[0] = 'success'; stop()
            page.wait_for_function("document.querySelector('#answerInput').value === '手动编辑\\n语音回答'")
            print('PASS single upload / guarded submit / redo cancellation / draft preservation')
            mode[0] = 'network'; page.locator('#transcribeBtn').click()
            page.wait_for_function("document.querySelector('#transcribeStatus').classList.contains('is-error')")
            assert page.locator('#submitAnswerBtn').is_enabled()
            assert page.locator('#voicePlayer').get_attribute('src')
            mode[0] = 'silence'; page.locator('#transcribeBtn').click()
            page.wait_for_function("document.querySelector('#transcribeStatus').textContent.includes('未识别')")
            mode[0] = 'null'; page.locator('#transcribeBtn').click()
            page.wait_for_function("document.querySelector('#transcribeStatus').textContent.includes('识别失败')")
            assert page.locator('#submitAnswerBtn').is_enabled()
            print('PASS network / silence failure and retry retain audio and text')
            mode[0] = 'answerfail'
            page.locator('#submitAnswerBtn').click()
            page.wait_for_function("!document.querySelector('#submitAnswerBtn').disabled")
            assert page.locator('#answerInput').input_value() == '手动编辑\n语音回答'
            mode[0] = 'success'
            page.locator('#submitAnswerBtn').click()
            page.wait_for_function("document.querySelector('#questionText').textContent === '下一题'")
            assert len(answers) == 2 and page.locator('#answerInput').input_value() == ''
            print('PASS answer failure preserves text / successful manual submit advances once')
            page.evaluate("window.emptyAudio = true")
            before = len(uploads); recording(); stop()
            page.wait_for_function("document.querySelector('#voiceHint').textContent.includes('录音为空')")
            assert len(uploads) == before
            page.evaluate("window.emptyAudio = false; window.permissionError = 'NotAllowedError'")
            page.locator('#micBtn').click()
            page.wait_for_function("document.querySelector('#voiceHint').textContent.includes('权限被拒绝')")
            assert page.locator('#submitAnswerBtn').is_enabled()
            page.evaluate("window.permissionError = ''; window.delayPermission = true")
            page.locator('#micBtn').click()
            page.wait_for_function("!!window.grantPermission")
            assert page.locator('#micBtn').is_disabled()
            page.evaluate('window.grantPermission()')
            page.wait_for_function("recorders[recorders.length-1].state === 'recording'")
            assert not errors, errors
            print('PASS empty blob / denied permission / pending permission guards / no JS errors')
            browser.close()
    finally:
        http.shutdown()
        env.tearDownModule()

if __name__ == '__main__': run()
