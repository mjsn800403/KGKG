import test from 'node:test';
import assert from 'node:assert/strict';

import { nextPollDelay, LIVE_MS, ASYNC_RECENT_MS, ASYNC_IDLE_MS, AWAITING_CLOSED_MS, BACKOFF_MAX_MS } from '../schedule.js';
import { initialState, reduce, deliveryOf, awaitingReply, shouldFallBack } from '../state.js';

const mid = () => 0.5;     // jitter factor exactly 1.0
const base = { hasThread: true, closed: false, hidden: false, panelOpen: true, mode: 'live',
  awaitingReply: true, msSinceSend: 1000, errors: 0 };

test('no thread, closed thread or hidden tab means no polling', () => {
  assert.equal(nextPollDelay({ ...base, hasThread: false }, mid), null);
  assert.equal(nextPollDelay({ ...base, closed: true }, mid), null);
  assert.equal(nextPollDelay({ ...base, hidden: true }, mid), null);
});

test('open panel: live 3 s; async 10 s shortly after a send then 20 s', () => {
  assert.equal(nextPollDelay(base, mid), LIVE_MS);
  assert.equal(nextPollDelay({ ...base, mode: 'async' }, mid), ASYNC_RECENT_MS);
  assert.equal(nextPollDelay({ ...base, mode: 'async', msSinceSend: 5 * 60 * 1000 }, mid), ASYNC_IDLE_MS);
});

test('closed panel polls slowly only while a reply is owed', () => {
  assert.equal(nextPollDelay({ ...base, panelOpen: false }, mid), AWAITING_CLOSED_MS);
  assert.equal(nextPollDelay({ ...base, panelOpen: false, awaitingReply: false }, mid), null);
});

test('jitter stays within plus or minus 20 percent', () => {
  assert.equal(nextPollDelay(base, () => 0), Math.round(LIVE_MS * 0.8));
  assert.equal(nextPollDelay(base, () => 0.999999), Math.round(LIVE_MS * 1.2));
});

test('errors back off to at most 60 s and 429 Retry-After is honoured', () => {
  assert.ok(nextPollDelay({ ...base, errors: 1 }, mid) >= 5000);
  assert.equal(nextPollDelay({ ...base, errors: 20 }, mid), BACKOFF_MAX_MS);
  assert.equal(nextPollDelay({ ...base, retryAfter: 45 }, mid), 45000);
});

test('the live interval stays under the server per-thread poll limit of 30 a minute', () => {
  const worst = Math.round(LIVE_MS * 0.8);
  assert.ok(60000 / worst <= 30);
});

const m = (id, author_kind, body, created_at = `2026-11-03T10:0${id}:00Z`) => ({ id, author_kind, body, created_at });

test('a poll merges server messages in id order without duplicates', () => {
  let s = initialState();
  s = reduce(s, { type: 'restore', threadId: 't' });
  s = reduce(s, { type: 'poll', messages: [m(2, 'admin', 'b'), m(1, 'visitor', 'a')], status: 'waiting_customer', mode: 'live' });
  s = reduce(s, { type: 'poll', messages: [m(2, 'admin', 'b'), m(3, 'admin', 'c')], status: 'waiting_customer', mode: 'live' });
  assert.deepEqual(s.messages.map((x) => x.body), ['a', 'b', 'c']);
  assert.equal(s.lastId, 3);
});

test('staff is displayed as staff, system as system, never with a name', () => {
  let s = reduce(initialState(), { type: 'poll', messages: [m(1, 'admin', 'x'), m(2, 'system', 'y')], status: 'open' });
  assert.deepEqual(s.messages.map((x) => x.kind), ['staff', 'system']);
  assert.ok(s.messages.every((x) => !('name' in x) && !('author' in x)));
});

test('an optimistic message is confirmed in place and a late poll duplicate does not double it', () => {
  let s = reduce(initialState(), { type: 'send_start', clientId: 'c1', body: 'hello', at: '2026-11-03T10:00:00Z' });
  assert.equal(s.messages[0].delivery, 'sending');
  s = reduce(s, { type: 'send_ok', clientId: 'c1', threadId: 't', message: m(1, 'visitor', 'hello') });
  s = reduce(s, { type: 'poll', messages: [m(1, 'visitor', 'hello')], status: 'waiting_staff' });
  assert.equal(s.messages.length, 1);
  assert.equal(s.messages[0].delivery, 'sent');
  assert.equal(s.phase, 'chat');
});

test('a poll that returns the visitor message before send_ok arrives still shows one bubble', () => {
  let s = reduce(initialState(), { type: 'send_start', clientId: 'c1', body: 'hello', at: 'x' });
  s = reduce(s, { type: 'poll', messages: [m(1, 'visitor', 'hello')], status: 'waiting_staff' });
  assert.equal(s.messages.length, 1);
});

test('failure marks the bubble failed and a retry reuses the same client id', () => {
  let s = reduce(initialState(), { type: 'send_start', clientId: 'c1', body: 'hello', at: 'x' });
  s = reduce(s, { type: 'send_fail', clientId: 'c1' });
  assert.equal(s.messages[0].delivery, 'failed');
  s = reduce(s, { type: 'send_start', clientId: 'c1', body: 'hello', at: 'x' });
  assert.equal(s.messages.length, 1);
  assert.equal(s.messages[0].delivery, 'sending');
});

test('read receipt follows staffSeenAt', () => {
  const msg = { kind: 'visitor', at: '2026-11-03T10:00:00Z', delivery: 'sent' };
  assert.equal(deliveryOf(msg, null), 'sent');
  assert.equal(deliveryOf(msg, '2026-11-03T09:59:59Z'), 'sent');
  assert.equal(deliveryOf(msg, '2026-11-03T10:00:00Z'), 'read');
  assert.equal(deliveryOf({ ...msg, delivery: 'failed' }, '2026-11-03T11:00:00Z'), 'failed');
  assert.equal(deliveryOf({ kind: 'staff' }, null), undefined);
});

test('unread counts staff replies only while the panel is closed', () => {
  let s = reduce(initialState(), { type: 'restore', threadId: 't' });
  s = reduce(s, { type: 'poll', messages: [m(1, 'admin', 'hi'), m(2, 'system', 'sys')], status: 'waiting_customer' });
  assert.equal(s.unread, 1);
  s = reduce(s, { type: 'panel', open: true });
  assert.equal(s.unread, 0);
  s = reduce(s, { type: 'poll', messages: [m(3, 'admin', 'again')], status: 'waiting_customer' });
  assert.equal(s.unread, 0);
});

test('a closed status moves to the closed phase and reopening returns to chat', () => {
  let s = reduce(initialState(), { type: 'restore', threadId: 't' });
  s = reduce(s, { type: 'poll', messages: [], status: 'closed', canReopen: true });
  assert.deepEqual([s.phase, s.canReopen], ['closed', true]);
  s = reduce(s, { type: 'reopened' });
  assert.equal(s.phase, 'chat');
});

test('gone clears the conversation but keeps the panel open', () => {
  let s = reduce(initialState(), { type: 'panel', open: true });
  s = reduce(s, { type: 'send_start', clientId: 'c', body: 'x', at: 'y' });
  s = reduce(s, { type: 'gone' });
  assert.deepEqual([s.phase, s.messages.length, s.threadId, s.panelOpen], ['gone', 0, null, true]);
});

test('awaitingReply is true only when the visitor spoke last', () => {
  let s = reduce(initialState(), { type: 'poll', messages: [m(1, 'visitor', 'a')], status: 'waiting_staff' });
  assert.equal(awaitingReply(s), true);
  s = reduce(s, { type: 'poll', messages: [m(2, 'admin', 'b'), m(3, 'system', 'sys')], status: 'waiting_customer' });
  assert.equal(awaitingReply(s), false);
});

test('fallback to async: only live, only unanswered, only after the delay, only once', () => {
  const args = { mode: 'live', messages: [{ kind: 'visitor' }], firstSentAt: 1000, now: 1000 + 90000, afterSeconds: 90, fellBack: false };
  assert.equal(shouldFallBack(args), true);
  assert.equal(shouldFallBack({ ...args, now: 1000 + 89999 }), false);
  assert.equal(shouldFallBack({ ...args, mode: 'async' }), false);
  assert.equal(shouldFallBack({ ...args, fellBack: true }), false);
  assert.equal(shouldFallBack({ ...args, messages: [{ kind: 'visitor' }, { kind: 'staff' }] }), false);
  assert.equal(shouldFallBack({ ...args, firstSentAt: null }), false);
});

test('availability is asked for the chosen intent only after the visitor chose one', () => {
  let st = initialState();
  assert.equal(st.intentChosen, false);
  st = reduce(st, { type: 'intent', intent: 'technical' });
  assert.deepEqual([st.intent, st.intentChosen], ['technical', true]);
  st = reduce(st, { type: 'reset' });
  assert.equal(st.intentChosen, false);                  // a new conversation asks about any intent again
  st = reduce(initialState(), { type: 'restore', threadId: 't', intent: 'sales' });
  assert.deepEqual([st.intent, st.intentChosen], ['sales', true]);
  st = reduce(initialState(), { type: 'restore', threadId: 't' });
  assert.equal(st.intentChosen, false);
});
