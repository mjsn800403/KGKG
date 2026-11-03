import test from 'node:test';
import assert from 'node:assert/strict';

import { createSharedEventStream, CLOSE_GRACE_MS } from '../sharedEventStream.js';

function rig() {
  const opened = [];
  const timers = [];
  const hub = createSharedEventStream({
    open: (o) => { const c = { o, closed: false }; opened.push(c); return () => { c.closed = true; }; },
    setTimer: (fn, ms) => { const t = { fn, ms, cleared: false }; timers.push(t); return t; },
    clearTimer: (t) => { t.cleared = true; },
  });
  const flush = () => timers.filter((t) => !t.cleared).forEach((t) => { t.cleared = true; t.fn(); });
  return { hub, opened, timers, flush };
}

test('many subscribers share one connection', () => {
  const { hub, opened } = rig();
  const offs = [1, 2, 3, 4, 5].map(() => hub.subscribe(true, {}));
  assert.equal(opened.length, 1);
  assert.deepEqual(hub.stats().admin, { subscribers: 5, open: true, status: 'connecting' });
  offs.forEach((off) => off());
});

test('admin and portal audiences are separate connections', () => {
  const { hub, opened } = rig();
  hub.subscribe(true, {});
  hub.subscribe(false, {});
  assert.equal(opened.length, 2);
  assert.deepEqual(opened.map((c) => c.o.admin), [true, false]);
});

test('every subscriber gets every event and a throwing one does not block the rest', () => {
  const { hub, opened } = rig();
  const a = []; const b = [];
  hub.subscribe(true, { onEvent: () => { throw new Error('boom'); } });
  hub.subscribe(true, { onEvent: (e) => a.push(e.id) });
  hub.subscribe(true, { onEvent: (e) => b.push(e.id) });
  opened[0].o.onEvent({ id: 1 });
  opened[0].o.onEvent({ id: 2 });
  assert.deepEqual(a, [1, 2]);
  assert.deepEqual(b, [1, 2]);
});

test('status reaches everyone and a late joiner is told the current status at once', () => {
  const { hub, opened } = rig();
  const seen = [];
  hub.subscribe(true, { onStatus: (s) => seen.push(['a', s]) });
  opened[0].o.onStatus('open');
  const late = [];
  hub.subscribe(true, { onStatus: (s) => late.push(s) });
  assert.deepEqual(seen, [['a', 'open']]);
  assert.deepEqual(late, ['open']);
});

test('the connection closes only after the last subscriber leaves and the grace period', () => {
  const { hub, opened, timers, flush } = rig();
  const off1 = hub.subscribe(true, {});
  const off2 = hub.subscribe(true, {});
  off1();
  flush();
  assert.equal(opened[0].closed, false);        // one subscriber remains
  off2();
  assert.equal(opened[0].closed, false);        // grace period not elapsed
  assert.equal(timers.at(-1).ms, CLOSE_GRACE_MS);
  flush();
  assert.equal(opened[0].closed, true);
  assert.deepEqual(hub.stats().admin, { subscribers: 0, open: false, status: 'idle' });
});

test('a tab switch (leave then join inside the grace period) keeps the same connection', () => {
  const { hub, opened, flush } = rig();
  const off = hub.subscribe(true, {});
  off();
  hub.subscribe(true, {});                      // the next tab mounts straight away
  flush();
  assert.equal(opened.length, 1);
  assert.equal(opened[0].closed, false);
});

test('after a full close a new subscriber opens a fresh connection', () => {
  const { hub, opened, flush } = rig();
  hub.subscribe(true, {})();
  flush();
  hub.subscribe(true, {});
  assert.equal(opened.length, 2);
  assert.equal(opened[0].closed, true);
  assert.equal(opened[1].closed, false);
});

test('unauthorized reaches subscribers, stops the connector and the next subscriber reconnects fresh', () => {
  const { hub, opened } = rig();
  const seen = [];
  hub.subscribe(true, { onStatus: (s) => seen.push(s) });
  opened[0].o.onStatus('unauthorized');
  assert.deepEqual(seen.slice(-1), ['unauthorized']);
  assert.equal(opened[0].closed, true);
  assert.equal(hub.stats().admin.open, false);
  hub.subscribe(true, {});                         // after signing in again
  assert.equal(opened.length, 2);
  assert.equal(opened[1].closed, false);
});

test('unauthorized reported synchronously by the connector (no token) leaves no stale connection', () => {
  const calls = [];
  const hub = createSharedEventStream({
    open: ({ onStatus }) => { onStatus('unauthorized'); calls.push('open'); return () => calls.push('close'); },
    setTimer: () => ({}), clearTimer: () => {},
  });
  hub.subscribe(true, {});
  assert.equal(hub.stats().admin.open, false);
  hub.subscribe(true, {});
  assert.deepEqual(calls.filter((c) => c === 'open').length, 2);   // retried, not stuck
});

test('calling unsubscribe twice is harmless', () => {
  const { hub, opened, flush } = rig();
  const keep = hub.subscribe(true, {});
  const off = hub.subscribe(true, {});
  off(); off();
  flush();
  assert.equal(opened[0].closed, false);
  assert.equal(hub.stats().admin.subscribers, 1);
  keep();
});
