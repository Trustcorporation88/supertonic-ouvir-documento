"""No Supertonic install or model downloads: controlled boundary stubs."""
import asyncio
import importlib.util
import io
from pathlib import Path
import sys
import threading
import time
import types

import numpy as np
import pytest
import soundfile as sf
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request


def load_server():
    # Stub ONLY external model package, exercise real server/textnorm/resources.
    modules = {}
    for name in ('supertonic', 'supertonic.server', 'supertonic.server.app',
                 'supertonic.server.audio', 'supertonic.server.routes'):
        modules[name] = types.ModuleType(name)
    def create_app(**kwargs):
        app = FastAPI()
        app.state.server_state = types.SimpleNamespace(tts=types.SimpleNamespace(
            sample_rate=8000, voice_style_names=['F1']), custom_styles={}, is_ready=True)
        return app
    modules['supertonic.server.app'].create_app = create_app
    audio = modules['supertonic.server.audio']
    audio.SUPPORTED_FORMATS = ('wav', 'ogg', 'flac')
    audio.format_to_mime = lambda fmt: 'audio/' + fmt
    def encode(wav, sr, fmt):
        out = io.BytesIO()
        sf.write(out, wav.squeeze(), sr, format=fmt.upper())
        return out.getvalue()
    audio.encode_audio = encode
    routes = modules['supertonic.server.routes']
    routes.UnknownVoice = type('UnknownVoice', (Exception,), {})
    routes._do_synthesize = lambda *a, **k: (np.ones((1, 800), dtype=np.float32) * .1, .1)
    previous = {name: sys.modules.get(name) for name in modules}
    sys.modules.update(modules)
    try:
        spec = importlib.util.spec_from_file_location('tested_server', Path(__file__).with_name('server.py'))
        server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(server)
        return server
    finally:
        for name, value in previous.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value


s = load_server()


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    for name in ('JOBS_DIR', 'CACHE_DIR', 'SHARE_DIR'):
        directory = tmp_path / name
        directory.mkdir()
        monkeypatch.setattr(s, name, directory)
    monkeypatch.setattr(s, 'QUEUE', asyncio.Queue(maxsize=2))
    monkeypatch.setattr(s, 'JOBS', {})
    monkeypatch.setattr(s, 'QUEUE_POS', {})
    monkeypatch.setattr(s, '_HITS', {})
    monkeypatch.setattr(s, 'RATE_LIMIT_PER_HOUR', 0)
    monkeypatch.setattr(s, 'ALLOW_REMOTE_DOWNLOADS', False)


def state():
    return s.app.state.server_state


@pytest.mark.parametrize('spec,total,result', [('1-999999999999', 3, [0, 1, 2]),
    ('3-1; 2', 3, [0, 1, 2]), ('', 3, None)])
def test_pages_clamped(spec, total, result):
    assert s.parse_pages(spec, total) == result


@pytest.mark.parametrize('spec', ['1' * 3000, '1-99999999999999999', 'x', '0', '100-200'])
def test_pages_bad(spec):
    with pytest.raises(s.UsarError):
        s.parse_pages(spec, 3)


def test_remote_disabled_before_any_download(monkeypatch):
    monkeypatch.setattr(s.subprocess, 'run', lambda *a, **k: pytest.fail('network invoked'))
    with pytest.raises(s.UsarError) as error:
        s._download_media('http://127.0.0.1/private', '/tmp', lambda *a: None)
    assert error.value.code == 'remote_download_disabled'


@pytest.mark.parametrize('trusted,expected', [('', '10.1.2.3'), ('10.0.0.0/8', '1.2.3.4')])
def test_proxy_trust(monkeypatch, trusted, expected):
    monkeypatch.setattr(s, 'TRUSTED_PROXIES', trusted)
    req = Request({'type': 'http', 'client': ('10.1.2.3', 8), 'headers': [(b'x-forwarded-for', b'1.2.3.4')]})
    assert s._client_ip(req) == expected


class Upload:
    filename = 'test.txt'
    def __init__(self, size):
        self.remaining, self.closed, self.read_sizes = size, False, []
    async def read(self, size):
        assert 0 < size <= 65536
        self.read_sizes.append(size)
        n = min(size, self.remaining)
        self.remaining -= n
        return b'x' * n
    async def close(self):
        self.closed = True


def test_disk_upload_and_cleanup(tmp_path):
    async def run():
        good = Upload(100000)
        path = await s.save_upload(good, tmp_path, 100000)
        assert path.stat().st_size == 100000 and good.closed
        path.unlink()
        for size in (0, 100001):
            bad = Upload(size)
            with pytest.raises(s.ResourceError):
                await s.save_upload(bad, tmp_path, 100000)
            assert bad.closed and not list(tmp_path.glob("upload-*"))
    asyncio.run(run())


@pytest.mark.parametrize('fmt', ['wav', 'flac', 'ogg'])
def test_streamed_audio_and_cache(fmt, monkeypatch):
    monkeypatch.setattr(s, 'split_chunks', lambda text: ['one', 'two'])
    monkeypatch.setattr(s, 'encode_audio', lambda *a: pytest.fail('whole audio encoded'))
    monkeypatch.setattr(s.np, 'concatenate', lambda *a: pytest.fail('audio arrays accumulated'))
    job = s.Job(text='one two', format=fmt)
    s._run_job_sync(job, state())
    assert job.status == 'done' and job.chunks_ready == 2
    data, sr = sf.read(job.final)
    assert sr == 8000 and len(data) == 3600
    cached = s.Job(text='one two', format=fmt)
    s._run_job_sync(cached, state())
    assert cached.cached and cached.status == 'done'
    assert not list(s.CACHE_DIR.glob('.publish-*'))


def test_cache_model_config(monkeypatch):
    job = s.Job(text='test')
    job.text = 'test'
    before = s._cache_key(job)
    monkeypatch.setattr(s, 'MODEL', 'other-model')
    assert s._cache_key(job) != before
    other = s._cache_key(job)
    monkeypatch.setattr(s, 'MP3_BITRATE', '128k')
    assert s._cache_key(job) != other


def test_cancellation_between_chunks(monkeypatch):
    monkeypatch.setattr(s, 'split_chunks', lambda text: ['one', 'two'])
    job = s.Job(text='hello')
    def synth(*a, **k):
        job.cancel_event.set()
        return np.zeros((1, 80)), .01
    monkeypatch.setattr(s, '_do_synthesize', synth)
    with pytest.raises(s.Cancelled):
        s._run_job_sync(job, state())
    assert job.final is None and not list(s.CACHE_DIR.iterdir())


def test_queued_cancel_and_worker_cleanup():
    async def run():
        job = s.Job(text='hello')
        job.cancel_event.set()
        s.JOBS[job.id] = job
        s.QUEUE.put_nowait(job)
        worker = asyncio.create_task(s._worker(state()))
        await asyncio.wait_for(job.completion.wait(), 2)
        assert job.status == 'cancelled' and job.finished and not job.dir.exists()
        await asyncio.wait_for(s.QUEUE.join(), 1)
        worker.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker
    asyncio.run(run())


def test_routes_and_legacy_upload(monkeypatch):
    with TestClient(s.build_app()) as client:
        for endpoint in ('/api/jobs', '/usar'):
            response = client.post(endpoint, data={'url': 'http://localhost/secret'})
            assert response.status_code == 403
        response = client.post('/usar', files={'file': ('test.txt', b'Hello world')}, data={'response_format': 'wav'})
        assert response.status_code == 200, response.text
        assert response.content[:4] == b'RIFF' and 'x-texto' in response.headers
        assert not list(s.JOBS_DIR.glob('upload-*'))
        response = client.post('/api/jobs', data={'text': 'Hello', 'response_format': 'wav'})
        assert response.status_code == 202
        job_id = response.json()['id']
        for _ in range(100):
            result = client.get('/api/jobs/' + job_id).json()
            if result['status'] == 'done':
                break
            time.sleep(.01)
        assert result['status'] == 'done'
        assert client.get(result['audio_url']).status_code == 200
        assert client.get(result['chunk_urls'][0]).status_code == 200


def test_bounded_queue_returns_429_and_cleans_upload(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = s._do_synthesize
    def slow(*a, **k):
        entered.set()
        assert release.wait(3)
        return original(*a, **k)
    monkeypatch.setattr(s, '_do_synthesize', slow)
    with TestClient(s.build_app()) as client:
        try:
            assert client.post('/api/jobs', data={'text': 'running', 'response_format': 'wav'}).status_code == 202
            assert entered.wait(1)
            for text in ('queued1', 'queued2'):
                assert client.post('/api/jobs', data={'text': text}).status_code == 202
            response = client.post('/api/jobs', files={'file': ('test.txt', b'overflow')})
            assert response.status_code == 429
            assert response.json()['error']['code'] == 'queue_full'
            assert not list(s.JOBS_DIR.glob('upload-*'))
        finally:
            release.set()
            time.sleep(.2)


def test_raw_body_limit_without_content_length():
    from backend_resources import BodyLimitMiddleware
    async def run():
        app = FastAPI()
        from fastapi import File, UploadFile
        @app.post('/')
        async def upload(file: UploadFile = File(...)):
            pytest.fail('oversized multipart reached endpoint')
        app = BodyLimitMiddleware(app, max_bytes=32)
        chunks = iter([b'--boundary\r\n', b'x' * 100])
        messages = []
        async def receive():
            block = next(chunks, b'')
            return {'type': 'http.request', 'body': block, 'more_body': bool(block)}
        async def send(message):
            messages.append(message)
        await app({'type':'http', 'method':'POST', 'path':'/', 'raw_path':b'/', 'query_string':b'',
                   'headers':[(b'content-type',b'multipart/form-data; boundary=boundary')],
                   'scheme':'http', 'server':('test',80), 'client':('test',1)}, receive, send)
        assert messages[0]['status'] == 413
    asyncio.run(run())


def test_janitor_only_terminal(monkeypatch):
    async def run():
        active, terminal = s.Job(text='active'), s.Job(text='terminal')
        active.created = terminal.created = 0
        terminal.status, terminal.finished = 'done', 1
        s.JOBS.update({j.id: j for j in (active, terminal)})
        calls = 0
        async def tick(*a):
            nonlocal calls
            calls += 1
            if calls > 1:
                raise asyncio.CancelledError()
        monkeypatch.setattr(s.asyncio, 'sleep', tick)
        with pytest.raises(asyncio.CancelledError):
            await s._janitor()
        assert active.dir.exists() and active.id in s.JOBS
        assert not terminal.dir.exists() and terminal.id not in s.JOBS
    asyncio.run(run())


@pytest.mark.parametrize('endpoint', ['/api/jobs', '/usar'])
def test_http_upload_limit(endpoint, monkeypatch):
    monkeypatch.setattr(s, 'MAX_UPLOAD_MB', 0)
    with TestClient(s.build_app()) as client:
        response = client.post(endpoint, files={'file': ('test.txt', b'x')})
        assert response.status_code == 413
        assert response.json()['error']['code'] == 'file_too_large'
        assert not list(s.JOBS_DIR.glob('upload-*'))


def test_active_cancel_does_not_delete_running_files(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = s._do_synthesize
    def slow(*a, **k):
        entered.set()
        assert release.wait(3)
        return original(*a, **k)
    monkeypatch.setattr(s, '_do_synthesize', slow)
    with TestClient(s.build_app()) as client:
        try:
            response = client.post('/api/jobs', files={'file': ('test.txt', b'active')}, data={'response_format':'wav'})
            job_id = response.json()['id']
            assert entered.wait(1)
            job = s.JOBS[job_id]
            uploaded = job.input['file'][1]
            response = client.delete('/api/jobs/' + job_id)
            assert response.status_code == 200
            assert job.dir.exists() and uploaded.exists()
            assert job.status == 'running' and job.cancel_event.is_set()
        finally:
            release.set()
        for _ in range(100):
            if job.finished:
                break
            time.sleep(.01)
        assert job.status == 'cancelled' and job.final is None
        assert not uploaded.exists() and not job.dir.exists()
        assert not list(s.CACHE_DIR.iterdir())


def test_cache_concurrent_publication_and_custom_voice(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    job = s.Job(text='hello', format='wav')
    s._run_job_sync(job, state())
    key = s._cache_key(job)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: s._save_to_cache(job, key), range(8)))
    assert (s.CACHE_DIR / key / 'meta.json').is_file()
    assert not list(s.CACHE_DIR.glob('.publish-*'))
    custom = types.SimpleNamespace(tts=state().tts, custom_styles={'custom':Path('voice.json')})
    monkeypatch.setattr(s, '_restore_from_cache', lambda *a: pytest.fail('custom voice cache reused'))
    monkeypatch.setattr(s, '_save_to_cache', lambda *a: pytest.fail('custom voice cached'))
    s._run_job_sync(s.Job(text='hello', voice='custom', format='wav'), custom)


def test_untrusted_xff_prefix_ignored(monkeypatch):
    monkeypatch.setattr(s, 'TRUSTED_PROXIES', '10.0.0.0/8')
    req = Request({'type':'http', 'client':('10.0.0.1',8),
                   'headers':[(b'x-forwarded-for',b'6.6.6.6, 1.2.3.4')]})
    assert s._client_ip(req) == '1.2.3.4'


def test_mp3_encoder_process_cancelled(tmp_path):
    from backend_resources import run_process, Cancelled
    started = time.monotonic()
    def cancel():
        raise Cancelled()
    with pytest.raises(Cancelled):
        run_process([sys.executable, '-c', 'import time; time.sleep(30)'], cancel)
    assert time.monotonic() - started < 2


def test_transcribe_cancel_not_swallowed(monkeypatch):
    def cancel(*a, **k):
        raise s.Cancelled()
    monkeypatch.setattr(s, '_to_compact_audio', cancel)
    monkeypatch.setattr(s, '_transcribe_local', lambda *a: pytest.fail('cancelled transcription started'))
    with pytest.raises(s.Cancelled):
        s._transcribe('/unused', 'pt', lambda *a: None)


def test_legacy_remote_transcription_contract_when_opted_in(monkeypatch):
    monkeypatch.setattr(s, 'ALLOW_REMOTE_DOWNLOADS', True)
    monkeypatch.setattr(s, '_download_media', lambda *a: '/stub')
    monkeypatch.setattr(s, '_transcribe', lambda *a: 'transcribed text')
    monkeypatch.setattr(s, '_do_synthesize', lambda *a, **k: pytest.fail('legacy URL synthesized'))
    with TestClient(s.build_app()) as client:
        response = client.post('/usar', data={'url':'https://example.com/media'})
        assert response.status_code == 200
        assert response.json() == {'text':'transcribed text', 'truncated':False}


def test_epub_dispatch_integrated(tmp_path):
    import zipfile
    path = tmp_path / 'book.epub'
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('mimetype', 'application/epub+zip')
        z.writestr('META-INF/container.xml', '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
        z.writestr('content.opf', '<package xmlns="http://www.idpf.org/2007/opf" version="3.0"><metadata/><manifest><item id="c" href="chapter.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="c"/></spine></package>')
        z.writestr('chapter.xhtml', '<html xmlns="http://www.w3.org/1999/xhtml"><body><h1>Capítulo um</h1><p>Texto para ouvir.</p></body></html>')
    text = s._extract_from_upload('book.epub', path, 'pt', lambda *a: None)
    assert 'Texto para ouvir.' in text


def test_invalid_epub_returns_client_error(tmp_path):
    path = tmp_path / 'bad.epub'
    path.write_bytes(b'not a zip')
    with pytest.raises(s.UsarError) as error:
        s._extract_from_upload('bad.epub', path, 'pt', lambda *a: None)
    assert error.value.status == 422


@pytest.mark.parametrize('url,ok', [
    ('https://www.youtube.com/watch?v=GVEPQ5vddv0', True),
    ('https://youtu.be/GVEPQ5vddv0', True),
    ('https://m.youtube.com/watch?v=x', True),
    ('https://vimeo.com/123', True),
    ('http://127.0.0.1/private', False),
    ('http://localhost/secret', False),
    ('https://youtube.com.evil.com/x', False),
    ('https://evil.com/?u=youtube.com', False),
    ('https://user:pw@youtube.com/x', False),
    ('https://youtube.com:8080/x', False),
    ('file:///etc/passwd', False),
])
def test_video_platform_allowlist(url, ok):
    assert s.is_video_platform_url(url) is ok


def test_youtube_link_uses_ytdlp_without_generic_extractor(monkeypatch, tmp_path):
    monkeypatch.setattr(s, 'ALLOW_REMOTE_DOWNLOADS', False)
    monkeypatch.setattr(s, 'ALLOW_VIDEO_PLATFORMS', True)
    monkeypatch.setattr(s.shutil, 'which', lambda name: '/usr/bin/yt-dlp' if name == 'yt-dlp' else None)
    seen = {}
    def fake_run(cmd, **kw):
        seen['cmd'] = cmd
        (tmp_path / 'media.m4a').write_bytes(b'x')
        return s.subprocess.CompletedProcess(cmd, 0, '', '')
    monkeypatch.setattr(s.subprocess, 'run', fake_run)
    out = s._download_media('https://www.youtube.com/watch?v=GVEPQ5vddv0', str(tmp_path), lambda *a: None)
    assert out.endswith('media.m4a')
    assert '--use-extractors' in seen['cmd'] and 'default,-generic' in seen['cmd']


COOKIE_LINE = '.youtube.com\tTRUE\t/\tTRUE\t1999999999\tSID\tabc123'


def test_ytdlp_proxy_validation(monkeypatch):
    for value, ok in [('http://u:p@proxy.example:8080', True), ('socks5h://1.2.3.4:1080', True),
                      ('ftp://x', False), ('not a url', False), ('', False)]:
        monkeypatch.setenv('YTDLP_PROXY', value)
        assert bool(s.ytdlp_proxy()) is ok, value


def test_ytdlp_cookies_raw_escaped_and_b64(monkeypatch):
    import base64
    monkeypatch.delenv('YTDLP_COOKIES_B64', raising=False)
    monkeypatch.setenv('YTDLP_COOKIES', '# Netscape HTTP Cookie File\\n' + COOKIE_LINE.replace('\t', '\\t'))
    assert COOKIE_LINE in s.ytdlp_cookies_text()
    monkeypatch.delenv('YTDLP_COOKIES')
    monkeypatch.setenv('YTDLP_COOKIES_B64', base64.b64encode(COOKIE_LINE.encode()).decode())
    text = s.ytdlp_cookies_text()
    assert text.startswith('# Netscape') and COOKIE_LINE in text
    monkeypatch.setenv('YTDLP_COOKIES_B64', '%%%nope')
    assert s.ytdlp_cookies_text() is None
    monkeypatch.delenv('YTDLP_COOKIES_B64')
    monkeypatch.setenv('YTDLP_COOKIES', 'garbage without tabs')
    assert s.ytdlp_cookies_text() is None


def test_ytdlp_gets_proxy_and_private_cookie_file(monkeypatch, tmp_path):
    import stat
    monkeypatch.setattr(s, 'ALLOW_REMOTE_DOWNLOADS', False)
    monkeypatch.setattr(s.shutil, 'which', lambda name: '/usr/bin/yt-dlp' if name == 'yt-dlp' else None)
    monkeypatch.setenv('YTDLP_PROXY', 'http://u:p@proxy.example:8080')
    monkeypatch.setenv('YTDLP_COOKIES', COOKIE_LINE)
    seen = {}
    def fake_run(cmd, **kw):
        seen['cmd'] = cmd
        seen['mode'] = stat.S_IMODE((tmp_path / 'cookies.txt').stat().st_mode)
        (tmp_path / 'media.webm').write_bytes(b'x')
        return s.subprocess.CompletedProcess(cmd, 0, '', '')
    monkeypatch.setattr(s.subprocess, 'run', fake_run)
    s._download_media('https://youtu.be/GVEPQ5vddv0', str(tmp_path), lambda *a: None)
    cmd = seen['cmd']
    assert cmd[cmd.index('--proxy') + 1] == 'http://u:p@proxy.example:8080'
    assert cmd[cmd.index('--cookies') + 1] == str(tmp_path / 'cookies.txt')
    assert seen['mode'] == 0o600


def test_youtube_403_gives_actionable_message(monkeypatch, tmp_path):
    monkeypatch.setattr(s, 'ALLOW_REMOTE_DOWNLOADS', False)
    monkeypatch.delenv('YTDLP_PROXY', raising=False)
    monkeypatch.delenv('YTDLP_COOKIES', raising=False)
    monkeypatch.delenv('YTDLP_COOKIES_B64', raising=False)
    monkeypatch.setattr(s.shutil, 'which', lambda name: '/usr/bin/yt-dlp' if name == 'yt-dlp' else None)
    monkeypatch.setattr(s.subprocess, 'run', lambda cmd, **kw: s.subprocess.CompletedProcess(
        cmd, 1, '', 'ERROR: unable to download video data: HTTP Error 403: Forbidden'))
    with pytest.raises(s.UsarError) as e:
        s._download_media('https://www.youtube.com/watch?v=x', str(tmp_path), lambda *a: None)
    assert e.value.code == 'youtube_blocked' and 'YTDLP_PROXY' in e.value.message


def test_youtube_retries_other_clients_then_succeeds(monkeypatch, tmp_path):
    monkeypatch.setattr(s, 'ALLOW_REMOTE_DOWNLOADS', False)
    monkeypatch.setenv('YTDLP_COOKIES', COOKIE_LINE)
    monkeypatch.delenv('YTDLP_PROXY', raising=False)
    monkeypatch.setattr(s.shutil, 'which', lambda name: '/usr/bin/yt-dlp' if name == 'yt-dlp' else None)
    calls = []
    def fake_run(cmd, **kw):
        calls.append(cmd)
        if len(calls) < 3:
            return s.subprocess.CompletedProcess(cmd, 1, '', "ERROR: [youtube] x: Sign in to confirm you're not a bot. Use --cookies for auth")
        (tmp_path / 'media.m4a').write_bytes(b'x')
        return s.subprocess.CompletedProcess(cmd, 0, '', '')
    monkeypatch.setattr(s.subprocess, 'run', fake_run)
    assert s._download_media('https://www.youtube.com/watch?v=x', str(tmp_path), lambda *a: None).endswith('media.m4a')
    assert len(calls) == 3 and 'youtube:player_client=web_safari' in calls[2]


def test_youtube_all_clients_blocked_reports_redacted_detail(monkeypatch, tmp_path):
    monkeypatch.setattr(s, 'ALLOW_REMOTE_DOWNLOADS', False)
    monkeypatch.setenv('YTDLP_COOKIES', COOKIE_LINE)
    monkeypatch.setenv('YTDLP_PROXY', 'http://user:secret@proxy.example:8080')
    monkeypatch.setattr(s.shutil, 'which', lambda name: '/usr/bin/yt-dlp' if name == 'yt-dlp' else None)
    err = "ERROR: unable to download via http://user:secret@proxy.example:8080 HTTP Error 403: Forbidden See  https://github.com/x"
    monkeypatch.setattr(s.subprocess, 'run', lambda cmd, **kw: s.subprocess.CompletedProcess(cmd, 1, '', err))
    with pytest.raises(s.UsarError) as e:
        s._download_media('https://youtu.be/x', str(tmp_path), lambda *a: None)
    assert e.value.code == 'youtube_blocked' and '5 métodos' in e.value.message
    assert 'secret' not in e.value.message and '403' in e.value.message


def test_cookie_summary_never_exposes_values(monkeypatch):
    monkeypatch.delenv('YTDLP_COOKIES_B64', raising=False)
    monkeypatch.setenv('YTDLP_COOKIES', COOKIE_LINE + '\n.youtube.com\tTRUE\t/\tTRUE\t1000\tOLD\tzzz')
    info = s.ytdlp_cookie_summary()
    assert info['loaded'] and info['count'] == 2 and info['expired'] == 1 and info['login_cookies'] == ['SID']
    assert 'abc123' not in str(info) and 'zzz' not in str(info)


def test_transcribe_empty_openai_result_is_no_speech(monkeypatch, tmp_path):
    media = tmp_path / 'm.webm'; media.write_bytes(b'x')
    monkeypatch.setattr(s, 'OPENAI_KEY', 'sk-test')
    monkeypatch.setattr(s, '_to_compact_audio', lambda p, *a, **k: p)
    monkeypatch.setattr(s, '_transcribe_openai', lambda *a: '')
    monkeypatch.setattr(s, '_transcribe_local', lambda *a: pytest.fail('local fallback'))
    with pytest.raises(s.UsarError) as e:
        s._transcribe(str(media), 'pt', lambda *a: None)
    assert e.value.code == 'no_speech'


def test_transcribe_openai_failure_without_local_reports_reason(monkeypatch, tmp_path):
    media = tmp_path / 'm.webm'; media.write_bytes(b'x')
    monkeypatch.setattr(s, 'OPENAI_KEY', 'sk-test')
    monkeypatch.setattr(s, '_to_compact_audio', lambda p, *a, **k: p)
    def boom(*a):
        raise RuntimeError('OpenAI 401: Incorrect API key provided: sk-proj-abc123')
    monkeypatch.setattr(s, '_transcribe_openai', boom)
    monkeypatch.setattr(s, '_has', lambda name: False)
    with pytest.raises(s.UsarError) as e:
        s._transcribe(str(media), 'pt', lambda *a: None)
    assert e.value.code == 'transcription_failed' and '401' in e.value.message and 'abc123' not in e.value.message
