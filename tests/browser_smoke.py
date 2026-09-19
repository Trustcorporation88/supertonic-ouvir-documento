"""Mocked HTTP browser smoke tests; no model or live backend required.
Run: FRONTEND_ROOT=/path/to/repository python3 tests/browser_smoke.py
Requires: pip install playwright; Chromium at CHROMIUM_PATH (default /usr/bin/chromium).
Tests visibility deterministically by overriding document.hidden and dispatching
visibilitychange; actual OS background throttling and screen readers are not covered.
"""
import io
import json
import os
import re
from pathlib import Path
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import wave
from playwright.sync_api import sync_playwright

ROOT = Path(os.environ.get('FRONTEND_ROOT', Path(__file__).resolve().parents[1])).resolve()
class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)
    def do_GET(self):
        if self.path == '/': self.path = '/static/index.html'
        return super().do_GET()
    def log_message(self, *_): pass

buf = io.BytesIO()
with wave.open(buf, 'wb') as wav:
    wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(8000)
    wav.writeframes(b'\x00\x00' * 800)
AUDIO = buf.getvalue()
BASE = dict(id='one', status='running', stage='tts', percent=50, message='Gerando voz…', text='Texto de teste.', chunks=['Texto de teste.'], chunk_urls=[], chunks_ready=0, queue_position=0, duration=.1, audio_url=None, format='wav', voice='F1', truncated=False)
server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
url = f'http://127.0.0.1:{server.server_port}'
results = []

def setup(browser, states=None, audio_retry=False, delete_error=False):
    page = browser.new_page(viewport={'width': 400, 'height': 900})
    errors, counts = [], dict(post=0, state=0, audio=0, delete=0)
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.route('**/health', lambda route: route.fulfill(json={'status':'ok','mp3':True}))
    page.route('**/api/voices', lambda route: route.fulfill(json={'voices':['F1','M1']}))
    def api(route):
        path = route.request.url.split(url)[-1]
        if path == '/api/jobs' and route.request.method == 'POST':
            counts['post'] += 1; route.fulfill(status=202, json={'id':'one'}); return
        if path == '/api/jobs/one' and route.request.method == 'DELETE':
            counts['delete'] += 1
            route.fulfill(status=503 if delete_error else 200, json={'ok': not delete_error}); return
        if path == '/api/jobs/one':
            counts['state'] += 1
            state = (states or [BASE])[min(counts['state']-1, len(states or [BASE])-1)]
            if isinstance(state, int): route.fulfill(status=state, json={'error':{'message':f'Erro {state}'}})
            else: route.fulfill(json=state)
            return
        if path == '/api/jobs/one/audio':
            counts['audio'] += 1
            if audio_retry and counts['audio'] == 1: route.fulfill(status=503, json={})
            else: route.fulfill(body=AUDIO, content_type='audio/wav')
            return
        if '/chunks/' in path: route.fulfill(body=AUDIO, content_type='audio/wav'); return
        route.fulfill(status=404, json={})
    page.route(re.compile(r'.*/api/jobs(?:/.*)?$'), api)
    page.goto(url)
    page.wait_for_function('document.querySelector("#health-text").textContent === "pronto"')
    return page, counts, errors

def start(page):
    page.click('#tab-text'); page.fill('#text', 'Texto de teste.'); page.click('#go')

def hidden(page, value):
    page.evaluate('''value => {
      Object.defineProperty(document, 'hidden', { configurable: true, value });
      document.dispatchEvent(new Event('visibilitychange'));
    }''', value)

def passed(name, errors):
    assert not errors, errors
    results.append(name); print('PASS:', name)

try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH','/usr/bin/chromium'), headless=True, args=['--no-sandbox'])
        page, counts, errors = setup(browser)
        assert not page.locator('#cancel-help').is_visible()
        page.click('#go')
        assert page.locator('#error-status').inner_text() == 'Escolha um arquivo.'
        page.locator('#file').set_input_files({'name':'doc.pdf','mimeType':'application/pdf','buffer':b'fake pdf'})
        page.fill('#pages', '2-3')
        page.locator('#file').set_input_files({'name':'livro.EPUB','mimeType':'application/epub+zip','buffer':b'fake epub'})
        assert not page.locator('#pages-field').is_visible()
        assert page.locator('#pages').input_value() == ''
        assert 'livro.EPUB' in page.locator('#fname-text').inner_text()
        assert '.epub' in page.locator('#file').get_attribute('accept')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.locator('#fclear').focus(); page.keyboard.press('Enter')
        assert not page.locator('#fname').is_visible()
        passed('EPUB UI, PDF page reset, keyboard removal, mobile layout and validation alert', errors)
        page.close()

        page, counts, errors = setup(browser)
        start(page)
        page.wait_for_function('document.querySelector("#progress-bar").getAttribute("aria-valuenow") === "50"')
        assert page.locator('#steps [aria-current="step"]').get_attribute('data-step') == 'tts'
        page.evaluate('''() => { window.statusMutations = 0;
          new MutationObserver(() => window.statusMutations++).observe(document.querySelector('#status'), {childList:true,subtree:true,characterData:true});
        }''')
        page.wait_for_timeout(1200)
        assert page.evaluate('window.statusMutations') == 0
        hidden(page, True); state_count = counts['state']; page.wait_for_timeout(2500)
        assert counts['state'] == state_count
        hidden(page, False); page.wait_for_timeout(300)
        assert counts['state'] > state_count
        page.click('#cancel-job')
        page.wait_for_function('!document.querySelector("#go").disabled')
        assert counts['delete'] == 1 and counts['post'] == 1
        assert 'Cancelamento solicitado' in page.locator('#status').inner_text()
        assert page.locator('#go').evaluate('(el) => document.activeElement === el')
        assert not page.locator('#player').get_attribute('src')
        state_count = counts['state']; page.wait_for_timeout(1600); assert counts['state'] == state_count
        passed('Adaptive polling pauses hidden, resumes once, avoids duplicate announcements, cancels and restores focus', errors)
        page.close()

        done = dict(BASE, status='done', stage='done', percent=100, message='Pronto', audio_url='/api/jobs/one/audio')
        page, counts, errors = setup(browser, [503, BASE, done], audio_retry=True)
        start(page)
        page.wait_for_function('document.querySelector("#error-status").textContent.includes("Conexão instável")')
        page.wait_for_function('!document.querySelector("#go").disabled', timeout=10000)
        assert counts == {'post':1, 'state':3, 'audio':2, 'delete':0}, counts
        assert page.locator('#down').get_attribute('href').startswith('blob:')
        assert page.locator('#progress-bar').get_attribute('aria-valuenow') == '100'
        assert 'Pronto' in page.locator('#status').inner_text()
        assert not page.locator('#error-status').is_visible()
        assert page.locator('#history li').count() == 1
        page.set_viewport_size({'width':1280,'height':960})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        if os.environ.get('SCREENSHOT_PATH'):
            page.screenshot(path=os.environ['SCREENSHOT_PATH'], full_page=True)
        passed('503 state/audio recovery, one POST, no extra state downloads after done, download/history and desktop rendering', errors)
        page.close()

        page, counts, errors = setup(browser, [404]); start(page)
        page.wait_for_function('!document.querySelector("#go").disabled')
        assert 'Erro 404' in page.locator('#error-status').inner_text()
        page.wait_for_timeout(1200); assert counts['state'] == 1 and counts['post'] == 1
        passed('Permanent errors terminate without retries or duplicate submission', errors)
        page.close()

        page, counts, errors = setup(browser, [dict(BASE, status='cancelled')]); start(page)
        page.wait_for_function('!document.querySelector("#go").disabled')
        assert page.locator('#status').inner_text() == 'Pedido cancelado no servidor.'
        assert not page.locator('#player').get_attribute('src')
        assert counts['state'] == 1
        passed('Remote cancelled state terminates cleanly without looping', errors)
        page.close()

        page, counts, errors = setup(browser, delete_error=True); start(page)
        page.wait_for_selector('#cancel-job', state='visible'); page.click('#cancel-job')
        page.wait_for_function('!document.querySelector("#go").disabled')
        assert 'não foi possível confirmar' in page.locator('#error-status').inner_text()
        assert counts['delete'] == 1
        passed('Unconfirmed DELETE reports uncertainty instead of claiming cancellation', errors)
        page.close()
        browser.close()
finally:
    server.shutdown(); server.server_close()
print(json.dumps({'passed': len(results), 'tests': results}, ensure_ascii=False, indent=2))
