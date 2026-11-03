import test from 'node:test';
import assert from 'node:assert/strict';

import { makeToken, isToken, makeClientId } from '../token.js';
import { createStore, QUEUE_MAX, QUEUE_TTL_MS, THREAD_KEY, QUEUE_KEY, DRAFT_KEY, DRAFT_MAX } from '../storage.js';

const bytes = (fill) => () => new Uint8Array(32).fill(fill);

test('makeToken is 43 chars of base64url and matches the server format', () => {
  for (const f of [0, 1, 127, 255]) {
    const t = makeToken(bytes(f));
    assert.equal(t.length, 43);
    assert.match(t, /^[A-Za-z0-9_-]{43}$/);
    assert.ok(isToken(t));
  }
});

test('makeToken is deterministic for the same bytes and differs for different bytes', () => {
  assert.equal(makeToken(bytes(7)), makeToken(bytes(7)));
  assert.notEqual(makeToken(bytes(7)), makeToken(bytes(8)));
});

test('makeToken matches Node base64url for the same bytes', () => {
  const raw = Uint8Array.from({ length: 32 }, (_, i) => (i * 37 + 11) % 256);
  const expected = Buffer.from(raw).toString('base64url');
  assert.equal(makeToken(() => raw), expected);
});

test('makeToken refuses a short entropy source', () => {
  assert.throws(() => makeToken(() => new Uint8Array(8)));
});

test('isToken rejects malformed values', () => {
  for (const bad of ['', 'short', 'x'.repeat(44), null, undefined, 5, 'a'.repeat(42) + '!']) {
    assert.equal(isToken(bad), false);
  }
});

test('makeClientId is short, safe and distinct per call', () => {
  let n = 0;
  const rb = () => Uint8Array.from({ length: 32 }, (_, i) => (i + (n++)) % 256);
  const a = makeClientId(rb);
  const b = makeClientId(rb);
  assert.notEqual(a, b);
  assert.match(a, /^c[A-Za-z0-9_-]{20}$/);
});

function fakeStorage() {
  const m = new Map();
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => m.set(k, String(v)),
    removeItem: (k) => m.delete(k),
    raw: m,
  };
}
const throwing = () => ({
  getItem() { throw new Error('blocked'); },
  setItem() { throw new Error('quota'); },
  removeItem() { throw new Error('blocked'); },
});

test('thread is saved to localStorage and restored', () => {
  const local = fakeStorage();
  const s = createStore({ local, session: fakeStorage() });
  assert.equal(s.thread(), null);
  s.saveThread({ threadId: 't1', token: 'k'.repeat(43), intent: 'sales' });
  assert.equal(s.thread().threadId, 't1');
  assert.equal(JSON.parse(local.raw.get(THREAD_KEY)).intent, 'sales');
});

test('message text never reaches localStorage', () => {
  const local = fakeStorage();
  const s = createStore({ local, session: fakeStorage() });
  s.saveThread({ threadId: 't1', token: 'k'.repeat(43) });
  s.enqueue({ clientId: 'c1', body: 'سلام این یک متن خصوصی است' });
  assert.ok(![...local.raw.values()].some((v) => v.includes('خصوصی')));
});

test('the unsent queue lives in sessionStorage, is bounded, de-duplicated and expires', () => {
  const session = fakeStorage();
  let t = 1_000_000;
  const s = createStore({ local: fakeStorage(), session, now: () => t });
  assert.equal(s.enqueue({ clientId: 'a', body: 'one' }), true);
  assert.equal(s.enqueue({ clientId: 'a', body: 'one' }), true);
  assert.equal(s.queue().length, 1);
  for (let i = 0; i < QUEUE_MAX - 1; i++) s.enqueue({ clientId: `x${i}`, body: 'b' });
  assert.equal(s.queue().length, QUEUE_MAX);
  assert.equal(s.enqueue({ clientId: 'overflow', body: 'b' }), false);
  assert.ok(session.raw.has(QUEUE_KEY));
  t += QUEUE_TTL_MS + 1;
  assert.deepEqual(s.queue(), []);
});

test('dequeue removes one entry', () => {
  const s = createStore({ local: fakeStorage(), session: fakeStorage() });
  s.enqueue({ clientId: 'a', body: '1' });
  s.enqueue({ clientId: 'b', body: '2' });
  s.dequeue('a');
  assert.deepEqual(s.queue().map((m) => m.clientId), ['b']);
});

test('forget clears the thread and the queue', () => {
  const s = createStore({ local: fakeStorage(), session: fakeStorage() });
  s.saveThread({ threadId: 't1', token: 'k'.repeat(43) });
  s.enqueue({ clientId: 'a', body: '1' });
  s.forget();
  assert.equal(s.thread(), null);
  assert.deepEqual(s.queue(), []);
});

test('unavailable or throwing storage degrades to memory without throwing', () => {
  for (const backing of [throwing(), undefined]) {
    const s = createStore({ local: backing, session: backing });
    s.saveThread({ threadId: 't1', token: 'k'.repeat(43) });
    assert.equal(s.thread().threadId, 't1');
    assert.equal(s.enqueue({ clientId: 'a', body: 'x' }), true);
    assert.equal(s.queue().length, 1);
    s.forget();
    assert.equal(s.thread(), null);
  }
});

test('corrupt stored JSON is ignored', () => {
  const local = fakeStorage();
  local.setItem(THREAD_KEY, '{not json');
  const session = fakeStorage();
  session.setItem(QUEUE_KEY, 'null');
  const s = createStore({ local, session });
  assert.equal(s.thread(), null);
  assert.deepEqual(s.queue(), []);
});

test('onChange fires on save, enqueue and forget and can be unsubscribed', () => {
  const s = createStore({ local: fakeStorage(), session: fakeStorage() });
  let n = 0;
  const off = s.onChange(() => { n++; });
  s.saveThread({ threadId: 't', token: 'k'.repeat(43) });
  s.enqueue({ clientId: 'a', body: 'x' });
  s.forget();
  assert.equal(n, 3);
  off();
  s.saveThread({ threadId: 't', token: 'k'.repeat(43) });
  assert.equal(n, 3);
});

test('a half-typed draft survives a reload in this tab only, never in localStorage', () => {
  const local = fakeStorage();
  const session = fakeStorage();
  const s = createStore({ local, session });
  s.saveDraft('قیمت اشتراک سالانه چند است');
  assert.equal(createStore({ local, session }).draft(), 'قیمت اشتراک سالانه چند است');
  assert.ok(![...local.raw.values()].some((v) => v.includes('اشتراک')));
  assert.ok(session.raw.has(DRAFT_KEY));
});

test('an empty or whitespace draft clears the stored one; the draft is capped', () => {
  const session = fakeStorage();
  const s = createStore({ local: fakeStorage(), session });
  s.saveDraft('x'.repeat(DRAFT_MAX + 50));
  assert.equal(s.draft().length, DRAFT_MAX);
  s.saveDraft('   ');
  assert.equal(s.draft(), '');
  assert.equal(session.raw.has(DRAFT_KEY), false);
  s.saveDraft(undefined);
  assert.equal(s.draft(), '');
});

test('a draft expires after a day and forget() removes it', () => {
  let t = 1000;
  const s = createStore({ local: fakeStorage(), session: fakeStorage(), now: () => t });
  s.saveDraft('hello');
  t += QUEUE_TTL_MS - 1;
  assert.equal(s.draft(), 'hello');
  t += 2;
  assert.equal(s.draft(), '');
  s.saveDraft('again');
  s.forget();
  assert.equal(s.draft(), '');
});

test('storage that throws never breaks draft saving or reading', () => {
  const s = createStore({ local: throwing(), session: throwing() });
  assert.doesNotThrow(() => s.saveDraft('still typing'));
  assert.equal(s.draft(), 'still typing');
});
