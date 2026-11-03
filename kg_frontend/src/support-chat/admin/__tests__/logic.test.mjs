import test from 'node:test';
import assert from 'node:assert/strict';

import {
  buildQuery, isActive, tabTitle, isChatEvent, eventThreadId, mergeMessages, heartbeatBody,
} from '../logic.js';

test('buildQuery drops empty values and encodes the rest', () => {
  assert.equal(buildQuery({}), '');
  assert.equal(buildQuery({ q: '', status: 'active', unread: null, intent: undefined }), '?status=active');
  assert.equal(buildQuery({ q: 'علی & co' }), '?q=%D8%B9%D9%84%DB%8C+%26+co');
});

test('isActive is true only within the away window of real input', () => {
  const now = 1_000_000;
  assert.equal(isActive(now - 1000, now), true);
  assert.equal(isActive(now - 10 * 60 * 1000, now), false);
  assert.equal(isActive(undefined, now), false);
  assert.equal(isActive(null, now), false);
  assert.equal(isActive(now - 5000, now, 1000), false);
});

test('an open tab with no input is reported as not active', () => {
  assert.deepEqual(heartbeatBody({ signedIn: true, lastInputAt: 0, now: 99_999_999 }), { active: false });
  assert.deepEqual(heartbeatBody({ signedIn: true, lastInputAt: 99_999_000, now: 99_999_999 }), { active: true });
  assert.equal(heartbeatBody({ signedIn: false, lastInputAt: 1, now: 2 }), null);
});

test('tabTitle prefixes the unread count only when there is one', () => {
  assert.equal(tabTitle('میز پشتیبانی', 0), 'میز پشتیبانی');
  assert.equal(tabTitle('میز پشتیبانی', 3), '(3) میز پشتیبانی');
});

test('event helpers recognise only support chat events and ids', () => {
  assert.equal(isChatEvent({ type: 'support_chat.message' }), true);
  assert.equal(isChatEvent({ type: 'ticket.message' }), false);
  assert.equal(isChatEvent(null), false);
  assert.equal(eventThreadId({ payload: { thread_id: 'abc' } }), 'abc');
  assert.equal(eventThreadId({ payload: { thread_id: 5 } }), null);
  assert.equal(eventThreadId({}), null);
});

test('mergeMessages is ordered, de-duplicated and lets newer data win', () => {
  const a = [{ id: 1, body: 'a' }, { id: 3, body: 'c' }];
  const b = [{ id: 2, body: 'b' }, { id: 3, body: 'c2' }];
  assert.deepEqual(mergeMessages(a, b).map((m) => m.body), ['a', 'b', 'c2']);
});
