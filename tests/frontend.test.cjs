/* Run from the delivery/repository root: node --test tests/frontend.test.cjs
 * No dependencies. Exercises the actual helpers from static/app.js in a VM;
 * no test-only globals or exports are added to production code.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = process.env.FRONTEND_ROOT || path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'static/app.js'), 'utf8');
const start = source.indexOf('  async function api(path, opts)');
const end = source.indexOf('  cancelBtn.onclick =', start);
assert.ok(start >= 0 && end > start, 'Locate existing production helper boundaries');
const helperCode = source.slice(start, end);

class Target {
  constructor() { this.listeners = new Map(); }
  addEventListener(type, fn) {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type).add(fn);
  }
  removeEventListener(type, fn) { this.listeners.get(type)?.delete(fn); }
  dispatch(type) { for (const fn of [...(this.listeners.get(type) || [])]) fn(); }
  get count() { return [...this.listeners.values()].reduce((n, fns) => n + fns.size, 0); }
}
const flush = async () => { for (let i = 0; i < 30; i++) await Promise.resolve(); };
function harness(fetcher = async () => new Response('{}')) {
  let now = 0, nextId = 0;
  const timers = new Map(), document = new Target(), window = new Target();
  document.hidden = false;
  const navigator = { onLine: true }, messages = [], calls = [];
  const context = vm.createContext({
    document, window, navigator, AbortController, DOMException,
    Date: { now: () => now, parse: Date.parse },
    setTimeout: (fn, ms) => { const id = ++nextId; timers.set(id, { fn, at: now + ms }); return id; },
    clearTimeout: (id) => timers.delete(id),
    fetch: async (...args) => { calls.push(args); return fetcher(...args); },
    say: (...args) => messages.push(args),
  });
  vm.runInContext(helperCode + '\nthis.helpers = { api, retryDelay, retryable, nextPollDelay, waitToPoll, readResponse, readWithRetry };', context);
  return {
    ...context.helpers, document, window, navigator, timers, calls, messages,
    hide(value) { document.hidden = value; document.dispatch('visibilitychange'); },
    online(value) { navigator.onLine = value; window.dispatch(value ? 'online' : 'offline'); },
    async tick(ms) {
      const target = now + ms;
      for (;;) {
        await flush();
        const due = [...timers].filter(([, t]) => t.at <= target).sort((a,b) => a[1].at - b[1].at)[0];
        if (!due) break;
        now = due[1].at; timers.delete(due[0]); due[1].fn();
      }
      now = target; await flush();
    },
    clean() { assert.equal(document.count + window.count, 0); assert.equal(timers.size, 0); },
  };
}

test('adaptive interval resets on progress and caps unchanged/queued jobs', () => {
  const h = harness();
  assert.equal(h.nextPollDelay(5000, true, {status:'running'}), 700);
  assert.equal(h.nextPollDelay(700, true, {status:'queued'}), 2000);
  assert.equal(h.nextPollDelay(700, false, {status:'running'}), 1050);
  assert.equal(h.nextPollDelay(5000, false, {status:'running'}), 5000);
  assert.equal(h.nextPollDelay(10000, false, {status:'queued'}), 10000);
});
test('exponential backoff is bounded, but respects server Retry-After', () => {
  const h = harness();
  assert.deepEqual([1,2,3,4,5,6,20].map(n => h.retryDelay(n)), [1000,2000,4000,8000,16000,30000,30000]);
  assert.equal(h.retryDelay(1, 90000), 90000);
});
test('hidden tab schedules no polling timer; return resumes once', async () => {
  const h = harness(); h.hide(true);
  let finished = 0;
  const p = h.waitToPoll(700).then(() => finished++);
  await h.tick(60000); assert.equal(finished, 0); assert.equal(h.timers.size, 0);
  h.hide(false); await p; assert.equal(finished, 1); h.clean();
});
test('hiding during delay clears timer and retains minimum deadline', async () => {
  const h = harness(); let done = false;
  const p = h.waitToPoll(2000).then(() => done = true);
  await h.tick(500); h.hide(true); assert.equal(h.timers.size, 0);
  await h.tick(500); h.hide(false); await h.tick(999); assert.equal(done, false);
  await h.tick(1); await p; h.clean();
});
test('offline polling waits for online event without spin loops', async () => {
  const h = harness(); h.online(false); let done = false;
  const p = h.waitToPoll(0).then(() => done = true);
  await h.tick(60000); assert.equal(done, false); assert.equal(h.timers.size, 0);
  h.online(true); await p; h.clean();
});
test('cancelling hidden wait removes listeners and timers', async () => {
  const h = harness(); const c = new AbortController(); h.hide(true);
  const p = h.waitToPoll(5000, c.signal);
  c.abort(); await assert.rejects(p, { name: 'AbortError' }); h.clean();
});
test('readResponse will not start a GET while hidden', async () => {
  const h = harness(); h.hide(true);
  await assert.rejects(h.readResponse('/api/jobs/a', 'json'), { name: 'AbortError' });
  assert.equal(h.calls.length, 0); h.clean();
});
test('hiding aborts in-flight state fetch and cleans resources', async () => {
  const h = harness((url, opts) => new Promise((resolve, reject) => {
    opts.signal.addEventListener('abort', () => reject(new DOMException('hidden', 'AbortError')));
  }));
  const p = h.readResponse('/api/jobs/a', 'json');
  h.hide(true);
  await assert.rejects(p, { name: 'AbortError' });
  assert.equal(h.calls.length, 1); assert.equal(h.calls[0][1].cache, 'no-store'); h.clean();
});
test('timeout covers stalled response body, not only response headers', async () => {
  const h = harness((url, opts) => ({ ok: true, json: () => new Promise((resolve, reject) => {
    opts.signal.addEventListener('abort', () => reject(new DOMException('timeout', 'AbortError')));
  }) }));
  const p = h.readResponse('/api/jobs/a', 'json');
  const rejected = assert.rejects(p, { name: 'TimeoutError' });
  await h.tick(15000); await rejected; h.clean();
});
test('503 retries sequentially, respects Retry-After and recovers', async () => {
  let attempt = 0;
  const h = harness(() => ++attempt === 1 ?
    new Response('{"error":{"message":"Busy"}}', { status: 503, headers: { 'Retry-After': '2' } }) :
    new Response('{"status":"running"}'));
  const p = h.readWithRetry('/api/jobs/a', 'json', new AbortController().signal);
  await flush(); assert.equal(attempt, 1);
  await h.tick(1999); assert.equal(attempt, 1);
  await h.tick(1); assert.equal((await p).status, 'running');
  assert.equal(attempt, 2); assert.equal(h.messages.length, 1); h.clean();
});
test('HTTP date Retry-After is interpreted as a deadline', async () => {
  const h = harness(() => new Response('{}', { status: 429, headers: { 'Retry-After': new Date(10000).toUTCString() } }));
  await assert.rejects(h.api('/api/jobs/a'), error => error.status === 429 && error.retryAfter === 10000);
});
test('permanent 404 fails without retrying or re-creating a job', async () => {
  const h = harness(() => new Response('{}', { status: 404 }));
  await assert.rejects(h.readWithRetry('/api/jobs/a', 'json', new AbortController().signal), e => e.status === 404);
  assert.equal(h.calls.length, 1); h.clean();
});
test('backoff does not download state while tab remains hidden', async () => {
  let attempt = 0;
  const h = harness(() => ++attempt === 1 ? new Response('{}', { status: 429 }) : new Response('{"status":"done"}'));
  const p = h.readWithRetry('/api/jobs/a', 'json', new AbortController().signal);
  await flush(); h.hide(true); await h.tick(60000); assert.equal(attempt, 1);
  h.hide(false); assert.equal((await p).status, 'done'); assert.equal(attempt, 2); h.clean();
});
test('cancel during retry backoff prevents late requests', async () => {
  const h = harness(() => new Response('{}', { status: 503 })); const c = new AbortController();
  const p = h.readWithRetry('/api/jobs/a', 'json', c.signal);
  await flush(); c.abort(); await assert.rejects(p, { name: 'AbortError' });
  await h.tick(60000); assert.equal(h.calls.length, 1); h.clean();
});
test('final audio retry only downloads audio, never re-fetches full job', async () => {
  let attempt = 0;
  const h = harness(() => ++attempt === 1 ? new Response('{}', { status: 502 }) : new Response('audio'));
  const p = h.readWithRetry('/api/jobs/a/audio', 'blob', new AbortController().signal);
  await h.tick(1000); assert.equal((await p).size, 5);
  assert.ok(h.calls.every(([url]) => url === '/api/jobs/a/audio')); h.clean();
});
test('EPUB and explicit progress/error semantics are present in HTML', () => {
  const html = fs.readFileSync(path.join(root, 'static/index.html'), 'utf8');
  assert.match(html, /accept="[^"]*\.epub/);
  assert.match(html, /id="progress-bar" role="progressbar"/);
  assert.match(html, /id="error-status" role="alert"/);
  assert.match(html, /id="cancel-job"/);
  assert.doesNotMatch(source, /new EventSource|supabase\.createClient/);
});
test('service worker only removes its own older cache versions', async () => {
  const handlers = {}, deleted = [];
  vm.runInNewContext(fs.readFileSync(path.join(root, 'static/sw.js'), 'utf8'), {
    self: { addEventListener: (name, fn) => handlers[name] = fn, clients: { claim: async () => {} } },
    caches: { keys: async () => ['other-app', 'supertonic-shell-v2', 'supertonic-shell-v3'], delete: async key => deleted.push(key) },
  });
  let pending; handlers.activate({ waitUntil: promise => pending = promise }); await pending;
  assert.deepEqual(deleted, ['supertonic-shell-v2']);
});
test('service worker does not cache API/audio or failed shell responses', async () => {
  const handlers = {}; let put = 0, response;
  vm.runInNewContext(fs.readFileSync(path.join(root, 'static/sw.js'), 'utf8'), {
    self: { addEventListener: (name, fn) => handlers[name] = fn }, URL,
    location: { origin: 'http://localhost' },
    caches: { open: async () => ({ put: async () => put++ }) },
    fetch: async () => new Response('failed', { status: 503 }),
  });
  function event(url) { return { request: { method: 'GET', url }, respondWith: p => response = p, waitUntil() {} }; }
  handlers.fetch(event('http://localhost/api/jobs/a')); assert.equal(response, undefined);
  handlers.fetch(event('http://localhost/api/jobs/a/audio')); assert.equal(response, undefined);
  handlers.fetch(event('http://localhost/static/app.js')); assert.equal((await response).status, 503);
  assert.equal(put, 0);
});
