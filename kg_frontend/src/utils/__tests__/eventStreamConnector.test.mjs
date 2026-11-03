import test from 'node:test';
import assert from 'node:assert/strict';

import { connectEventStream, STALL_MS } from '../eventStreamConnector.js';

// ---- harness: fake clock + scripted fetch -----------------------------------
function clock() {
  let now = 0;
  let seq = 0;
  const timers = new Map();
  return {
    setTimer(fn, ms) { const id = ++seq; timers.set(id, { at: now + ms, fn }); return id; },
    clearTimer(id) { timers.delete(id); },
    async advance(ms) {
      const end = now + ms;
      for (;;) {
        const due = [...timers].filter(([, t]) => t.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
        if (!due) break;
        now = due[1].at;
        timers.delete(due[0]);
        due[1].fn();
        await tick();
      }
      now = end;
      await tick();
    },
    pending: () => timers.size,
  };
}
const tick = () => new Promise((r) => setImmediate(r));

/** A response whose body is fed by hand; read() rejects on abort like the real thing. */
function liveResponse(signal) {
  const queue = [];
  let wake = null;
  let ended = false;
  let failed = null;
  const enc = new TextEncoder();
  const settle = () => { if (wake) { const w = wake; wake = null; w(); } };
  signal?.addEventListener('abort', () => { failed = new DOMException('aborted', 'AbortError'); settle(); });
  return {
    ok: true,
    status: 200,
    body: {
      getReader: () => ({
        async read() {
          for (;;) {
            if (failed) throw failed;
            if (queue.length) return { value: queue.shift(), done: false };
            if (ended) return { value: undefined, done: true };
            await new Promise((r) => { wake = r; });
          }
        },
      }),
    },
    push(text) { queue.push(enc.encode(text)); settle(); },
    end() { ended = true; settle(); },
    drop() { failed = new TypeError('network error'); settle(); },
  };
}

function setup(script, extra = {}) {
  const c = clock();
  const calls = [];
  const statuses = [];
  const events = [];
  const target = new EventTarget();
  const fetchFn = async (url, init) => {
    calls.push({ url, init });
    const step = script.shift();
    if (!step) throw new TypeError('no more scripted responses');
    return typeof step === 'function' ? step(init.signal) : step;
  };
  const close = connectEventStream({
    url: '/stream', fetchFn, setTimer: c.setTimer, clearTimer: c.clearTimer, random: () => 0.5, target,
    onStatus: (s) => statuses.push(s), onEvent: (e) => events.push(e), ...extra,
  });
  return { c, calls, statuses, events, close, target };
}

// ---- tests -------------------------------------------------------------------
test('delivers events and resumes from the last id after a clean server recycle', async () => {
  const a = liveResponse();
  const b = liveResponse();
  const t = setup([() => a, () => b]);
  await tick();
  a.push(': connected\nretry: 3000\n\nid: 7\nevent: support_chat.message\ndata: {"thread_id":"x"}\n\n');
  await tick();
  assert.deepEqual(t.events, [{ type: 'support_chat.message', thread_id: 'x' }]);
  a.push('event: reconnect\ndata: {}\n\n');
  a.end();
  await tick();
  assert.deepEqual(t.statuses.slice(-1), ['reconnecting']);
  await t.c.advance(3000);
  assert.equal(t.calls.length, 2);
  assert.equal(t.calls[1].init.headers['Last-Event-ID'], '7');
  assert.equal(t.statuses.at(-1), 'open');
  t.close();
});

test('a connection dropped mid-stream reconnects and resumes from the cursor', async () => {
  const a = liveResponse();
  const b = liveResponse();
  const t = setup([() => a, () => b]);
  await tick();
  a.push('id: 41\nevent: e\ndata: {"n":1}\n\n');
  await tick();
  a.drop();
  await tick();
  assert.equal(t.statuses.at(-1), 'reconnecting');
  await t.c.advance(4000);
  assert.equal(t.calls[1].init.headers['Last-Event-ID'], '41');
  b.push('id: 42\nevent: e\ndata: {"n":2}\n\n');
  await tick();
  assert.deepEqual(t.events.map((e) => e.n), [1, 2]);
  t.close();
});

test('a silent stall is detected after STALL_MS and the stream is reopened', async () => {
  const b = liveResponse();
  const t = setup([(sig) => liveResponse(sig), () => b]);
  await tick();
  assert.equal(t.statuses.at(-1), 'open');
  await t.c.advance(STALL_MS - 1000);
  assert.equal(t.calls.length, 1, 'still waiting just before the deadline');
  await t.c.advance(2000);
  assert.equal(t.statuses.includes('reconnecting'), true);
  await t.c.advance(4000);
  assert.equal(t.calls.length, 2);
  t.close();
});

test('heartbeats keep a quiet but healthy stream alive past STALL_MS', async () => {
  let live;
  const t = setup([(sig) => (live = liveResponse(sig))]);
  await tick();
  for (let i = 0; i < 6; i++) {
    await t.c.advance(15000);
    live.push(': ping\n\n');
    await tick();
  }
  assert.equal(t.calls.length, 1);
  assert.equal(t.statuses.at(-1), 'open');
  t.close();
});

test('failed attempts back off 3 s, 6 s, 12 s and then stay at the cap', async () => {
  const err = () => { throw new TypeError('down'); };
  const t = setup([err, err, err, err, err], { maxRetryMs: 20000 });
  await tick();
  let seen = t.calls.length;
  for (const d of [3000, 6000, 12000, 20000]) {
    await t.c.advance(d - 1);
    assert.equal(t.calls.length, seen, `no retry before ${d} ms`);
    await t.c.advance(1);
    assert.equal(t.calls.length, seen + 1, `retry at ${d} ms`);
    seen += 1;
  }
  t.close();
});

test('after a stream that opened, the next retry is back at the base delay', async () => {
  const err = () => { throw new TypeError('down'); };
  let live;
  const t = setup([err, err, (sig) => (live = liveResponse(sig)), err]);
  await tick();
  await t.c.advance(3000);          // 2nd attempt fails, next wait is 6 s
  await t.c.advance(6000);          // 3rd attempt opens
  assert.equal(t.statuses.at(-1), 'open');
  live.drop();
  await tick();
  const before = t.calls.length;
  await t.c.advance(2999);
  assert.equal(t.calls.length, before);
  await t.c.advance(1);
  assert.equal(t.calls.length, before + 1);
  t.close();
});

test('the browser coming back online reconnects at once', async () => {
  const err = () => { throw new TypeError('offline'); };
  let live;
  const t = setup([err, err, (sig) => (live = liveResponse(sig))]);
  await tick();
  await t.c.advance(3000);
  assert.equal(t.calls.length, 2);
  t.target.dispatchEvent(new Event('online'));
  await tick();
  assert.equal(t.calls.length, 3);
  assert.equal(t.statuses.at(-1), 'open');
  live.end();
  t.close();
});

test('a 401 reports unauthorized once and never retries', async () => {
  const t = setup([{ ok: false, status: 401, body: null }]);
  await tick();
  await t.c.advance(120000);
  assert.deepEqual(t.statuses, ['connecting', 'unauthorized']);
  assert.equal(t.calls.length, 1);
  assert.equal(t.c.pending(), 0);
});

test('a 503 is treated as an outage: reconnecting with backoff, not unauthorized', async () => {
  const t = setup([{ ok: false, status: 503, body: null }, { ok: false, status: 503, body: null }]);
  await tick();
  assert.equal(t.statuses.at(-1), 'reconnecting');
  await t.c.advance(3000);
  await tick();
  assert.equal(t.calls.length, 2);
  assert.equal(t.statuses.includes('unauthorized'), false);
  t.close();
});

test('close() stops everything: no timers, no further requests, listener removed', async () => {
  const t = setup([() => liveResponse()]);
  await tick();
  t.close();
  await tick();
  t.target.dispatchEvent(new Event('online'));
  await t.c.advance(300000);
  assert.equal(t.calls.length, 1);
  assert.equal(t.c.pending(), 0);
});

test('the headers are read on every attempt so a new sign-in is picked up', async () => {
  let token = 'old';
  const err = () => { throw new TypeError('x'); };
  const t = setup([err, (sig) => liveResponse(sig)], { headers: () => ({ Authorization: `Bearer ${token}` }) });
  await tick();
  token = 'new';
  await t.c.advance(3000);
  assert.equal(t.calls[0].init.headers.Authorization, 'Bearer old');
  assert.equal(t.calls[1].init.headers.Authorization, 'Bearer new');
  t.close();
});

test('malformed frames and a throwing consumer do not break the stream', async () => {
  const a = liveResponse();
  const t = setup([() => a], { onEvent: (e) => { if (e.n === 1) throw new Error('consumer bug'); } });
  await tick();
  a.push('event: e\ndata: {not json}\n\nevent: e\ndata: {"n":2}\n\n');
  await tick();
  assert.equal(t.statuses.at(-1), 'open');
  t.close();
});
