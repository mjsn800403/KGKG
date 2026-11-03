import test from 'node:test';
import assert from 'node:assert/strict';

import { createClient } from '../client.js';

function res(status, body, headers = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: (k) => headers[k] ?? null },
    json: async () => body,
  };
}
function client(handler) {
  const calls = [];
  const c = createClient({
    base: '/kg-api/',
    fetch: async (url, init) => { calls.push({ url, init }); return handler(url, init); },
  });
  return { c, calls };
}
const TOKEN = 't'.repeat(43);

test('create posts the body without any token header and never throws', async () => {
  const { c, calls } = client(() => res(201, { thread_id: 'x', mode: 'async', message: { id: 1 } }));
  const r = await c.create({ token: TOKEN, message: 'hi', clientId: 'c1', intent: 'sales', page: '/', turnstileToken: 'ts' });
  assert.equal(r.ok, true);
  assert.equal(calls[0].url, '/kg-api/api/support-chat/threads/');
  const body = JSON.parse(calls[0].init.body);
  assert.deepEqual([body.token, body.client_id, body.turnstile_token], [TOKEN, 'c1', 'ts']);
  assert.equal(calls[0].init.headers['X-Support-Chat-Token'], undefined);
});

test('poll and send carry the thread token in the header, never in the URL', async () => {
  const { c, calls } = client(() => res(200, {}));
  await c.poll('abc', TOKEN, 5);
  await c.send('abc', TOKEN, { message: 'x', clientId: 'c2' });
  for (const call of calls) {
    assert.equal(call.init.headers['X-Support-Chat-Token'], TOKEN);
    assert.ok(!call.url.includes(TOKEN));
  }
  assert.equal(calls[0].url, '/kg-api/api/support-chat/threads/abc/messages/?after=5');
});

test('error kinds are typed', async () => {
  const cases = [
    [429, { error: 'x' }, { 'Retry-After': '12' }, { kind: 'rate_limited', retryAfter: 12 }],
    [404, {}, {}, { kind: 'not_found' }],
    [409, { code: 'closed', can_reopen: true }, {}, { kind: 'closed', canReopen: true }],
    [409, { code: 'reopen_window_expired' }, {}, { kind: 'conflict', code: 'reopen_window_expired' }],
    [400, { error: 'پیام خالی است' }, {}, { kind: 'invalid', message: 'پیام خالی است' }],
    [502, {}, {}, { kind: 'server' }],
  ];
  for (const [status, body, headers, want] of cases) {
    const { c } = client(() => res(status, body, headers));
    const r = await c.send('t', TOKEN, { message: 'x', clientId: 'c' });
    assert.equal(r.ok, false);
    for (const [k, v] of Object.entries(want)) assert.equal(r[k], v, `${status} ${k}`);
  }
});

test('429 without a Retry-After header defaults to a safe wait', async () => {
  const { c } = client(() => res(429, {}));
  assert.equal((await c.poll('t', TOKEN, 0)).retryAfter, 30);
});

test('a network failure resolves to kind network instead of throwing', async () => {
  const c = createClient({ fetch: async () => { throw new TypeError('Failed to fetch'); } });
  const r = await c.status();
  assert.deepEqual([r.ok, r.kind], [false, 'network']);
});

test('a non-JSON error body is tolerated', async () => {
  const bad = { ok: false, status: 400, headers: { get: () => null }, json: async () => { throw new Error('x'); } };
  const { c } = client(() => bad);
  const r = await c.status();
  assert.deepEqual([r.ok, r.kind, r.message], [false, 'invalid', '']);
});

test('thread ids are URL-encoded', async () => {
  const { c, calls } = client(() => res(200, {}));
  await c.reopen('a/b', TOKEN);
  assert.ok(calls[0].url.includes('a%2Fb'));
});
