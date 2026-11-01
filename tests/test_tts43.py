import sys
import threading
from pathlib import Path
from playwright.sync_api import sync_playwright
sys.path.insert(0, str(Path(__file__).parent))
import test_speech42 as env
from browser_fixture_state import stub_browser_state
from werkzeug.serving import make_server

MOCK = r'''(() => {
const synth = new EventTarget();
window.ttsCalls = []; window.cancelCalls = 0; window.voiceList = [];
synth.getVoices = () => window.voiceList;
synth.cancel = () => window.cancelCalls++;
synth.speak = u => {window.ttsCalls.push(u); if (window.ttsThrow) throw Error('unavailable');};
Object.defineProperty(window, 'speechSynthesis', {value: synth, configurable:true});
window.SpeechSynthesisUtterance = class {constructor(text) {this.text = text;}};
})();'''

def run():
    http = make_server('127.0.0.1', 5009, env.server.app, threaded=True)
    threading.Thread(target=http.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)
            page = browser.new_page()
            stub_browser_state(page)
            page.add_init_script("localStorage.setItem('iv-session', JSON.stringify({session_id:'test',job:'Java',level:'标准',question:'请介绍自己',progress:{main:1,total:3}}));")
            page.add_init_script(MOCK)
            errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto('http://127.0.0.1:5009/interview')
            assert '中文音色' in page.locator('#ttsHint').inner_text()
            page.locator('#replayBtn').click()
            assert page.evaluate('ttsCalls.length') == 0
            page.evaluate("voiceList = [{lang:'en-US'}, {lang:'zh-TW'}, {lang:'zh-CN'}]; speechSynthesis.dispatchEvent(new Event('voiceschanged'))")
            assert '点击' in page.locator('#ttsHint').inner_text()
            page.locator('#replayBtn').click()
            assert page.evaluate("ttsCalls.length === 1 && ttsCalls[0].text === '请介绍自己' && ttsCalls[0].voice.lang === 'zh-CN'")
            page.evaluate('ttsCalls[0].onstart()')
            assert page.locator('#submitAnswerBtn').is_enabled()
            page.locator('#replayBtn').click()
            assert page.locator('#replayBtn').get_attribute('aria-pressed') == 'false'
            page.locator('#replayBtn').click()
            page.evaluate('ttsCalls[0].onerror()')
            assert page.locator('#replayBtn').get_attribute('aria-pressed') == 'true', 'stale callback must be ignored'
            page.evaluate('ttsCalls[1].onerror()')
            assert '失败' in page.locator('#ttsHint').inner_text()
            assert page.locator('#submitAnswerBtn').is_enabled()
            page.evaluate('window.ttsThrow = true')
            page.locator('#replayBtn').click()
            assert '不可用' in page.locator('#ttsHint').inner_text()
            assert page.locator('#submitAnswerBtn').is_enabled()
            page.evaluate("Object.defineProperty(window,'speechSynthesis',{value:undefined,configurable:true})")
            # Reload with an additional script to simulate unsupported browsers.
            page.add_init_script("Object.defineProperty(window,'speechSynthesis',{value:undefined,configurable:true})")
            page.reload(wait_until='networkidle')
            assert page.locator('#replayBtn').is_disabled()
            assert page.locator('#submitAnswerBtn').is_enabled()
            assert not errors, errors
            print('PASS TTS unavailable / asynchronous Chinese voices / zh-CN preference / play-stop / stale events / errors isolated')
            browser.close()
    finally:
        http.shutdown()
        env.tearDownModule()

if __name__ == '__main__': run()
