"""Real HTTPS/browser/cloud smoke. Uses a synthetic microphone fixture, then deletes its own trial."""
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
state=json.loads((ROOT/'.public-test/processes.json').read_text(encoding='utf-8-sig'))
BASE=state['public_url']
sid=None
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
        headless=True,args=['--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream',
        '--use-file-for-fake-audio-capture='+str(ROOT/'tests/chinese-fixture.wav')])
    context=browser.new_context(viewport={'width':1280,'height':900})
    page=context.new_page()
    page.set_default_timeout(60000)
    errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    try:
        page.goto(BASE,wait_until='domcontentloaded')
        assert page.evaluate('window.isSecureContext && !!navigator.mediaDevices.getUserMedia')
        page.locator('.entry-mode[data-mode="direct"]').click()
        page.locator('.job-card[data-job="Java 后端"]').click()
        page.locator('.seg[data-level="校招标准"]').click()
        with page.expect_response('**/api/interview/start',timeout=90000) as started:
            page.locator('#startBtn').click()
        start=started.value
        assert start.status==200, 'Public start failed: '+str(start.status)
        page.wait_for_url('**/interview',timeout=90000)
        sid=page.evaluate('JSON.parse(localStorage.getItem("iv-session")).session_id')
        page.locator('#micBtn').click()
        page.wait_for_function("document.querySelector('#voiceHint').textContent.includes('正在录音')")
        page.wait_for_timeout(6500)
        page.locator('#micBtn').click()
        page.wait_for_function("document.querySelector('#answerInput').value.length>0 || document.querySelector('#transcribeStatus').classList.contains('is-error')",timeout=180000)
        assert page.locator('#answerInput').input_value(),page.locator('#transcribeStatus').inner_text()
        assert page.locator('#audioAnalysis').is_visible()
        assert page.locator('#voicePlayer').get_attribute('src').startswith('blob:')
        other=browser.new_context()
        assert other.request.get(BASE+'/api/report/'+sid).status==404
        assert other.request.get(BASE+'/api/interviews').json()['total']==0
        other.close()
        with page.expect_response('**/api/interview/answer',timeout=90000) as answered:
            page.locator('#submitAnswerBtn').click()
        assert answered.value.status==200,'Public answer failed: '+str(answered.value.status)
        page.wait_for_function("!document.querySelector('#submitAnswerBtn').disabled")
        page.evaluate('window.scrollTo(0,0)')
        page.locator('#endBtn').click();page.locator('#confirmEndBtn').click()
        page.wait_for_url('**/report?*',timeout=180000)
        page.wait_for_function("!document.querySelector('#reportBody').classList.contains('is-hidden')",timeout=180000)
        page.wait_for_function("document.querySelector('#speechReport').textContent.includes('有效语音')")
        page.wait_for_function("!document.querySelector('#speechReviewBtn').disabled",timeout=90000)
        report=context.request.get(BASE+'/api/report/'+sid,timeout=180000).json()
        assert report['available'] and len(report['speech_analyses'])==1
        assert not errors,errors
        page.screenshot(path=str(ROOT/'docs/public-trial-preview.png'),full_page=True)
        print('PASS public HTTPS + secure microphone + real DeepSeek start/answer + real WebM ASR/metrics + isolated history + saved report',flush=True)
        print('Speech advice status:',report['speech_analyses'][0].get('feedback',{}).get('status'),flush=True)
        print('No JavaScript page errors',flush=True)
    finally:
        if sid:
            deleted=context.request.delete(BASE+'/api/interview/'+sid,headers={'Origin':BASE},timeout=30000)
            print('Synthetic trial cleanup:',deleted.status,flush=True)
        browser.close()
