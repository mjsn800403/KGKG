import test from 'node:test';
import assert from 'node:assert/strict';

import {
  topicLabel, groupByDay, firstUnreadIndex, activityState, rowSubtitle,
} from '../support.js';

const msg = (at, kind, body = 'x') => ({
  id: at, created_at: at, body, author: { kind, name: kind },
});

test('topicLabel names the uncategorised case rather than returning empty', () => {
  assert.equal(topicLabel(''), 'دسته‌بندی‌نشده');
  assert.equal(topicLabel(null), 'دسته‌بندی‌نشده');
});

test('topicLabel translates a known topic', () => {
  assert.notEqual(topicLabel('billing'), 'دسته‌بندی‌نشده');
  assert.ok(topicLabel('billing').length > 0);
});

test('topicLabel falls back to the raw value for an unknown topic', () => {
  assert.equal(topicLabel('from_the_future'), 'from_the_future');
});

test('firstUnreadIndex points at the first message the viewer has not seen', () => {
  const messages = [msg('2026-10-30T10:00:00Z', 'user'),
                    msg('2026-10-31T09:00:00Z', 'admin'),
                    msg('2026-10-31T10:00:00Z', 'admin')];
  assert.equal(firstUnreadIndex(messages, 2), 1);
});

test('firstUnreadIndex is -1 when nothing is unread', () => {
  const messages = [msg('2026-10-30T10:00:00Z', 'user')];
  assert.equal(firstUnreadIndex(messages, 0), -1);
  assert.equal(firstUnreadIndex(messages, null), -1);
});

test('firstUnreadIndex clamps an unread count larger than the thread', () => {
  const messages = [msg('2026-10-30T10:00:00Z', 'admin')];
  assert.equal(firstUnreadIndex(messages, 99), 0);
});

test('firstUnreadIndex is -1 for an empty thread', () => {
  assert.equal(firstUnreadIndex([], 3), -1);
});

test('groupByDay keeps order and splits on the day boundary', () => {
  const messages = [msg('2026-10-30T10:00:00Z', 'user'),
                    msg('2026-10-30T18:00:00Z', 'admin'),
                    msg('2026-10-31T09:00:00Z', 'admin')];
  const groups = groupByDay(messages);
  assert.equal(groups.length, 2);
  assert.equal(groups[0].messages.length, 2);
  assert.equal(groups[1].messages.length, 1);
  assert.ok(groups[0].day);
});

test('groupByDay of an empty thread is an empty list', () => {
  assert.deepEqual(groupByDay([]), []);
});

test('activityState prefers unread over awaiting', () => {
  assert.equal(activityState({ status: 'pending', unread_count: 2, awaiting_reply: true }),
               'unread');
});

test('activityState reports awaiting_us when read but unanswered', () => {
  assert.equal(activityState({ status: 'pending', unread_count: 0, awaiting_reply: true }),
               'awaiting_us');
});

test('activityState reports awaiting_them when we answered last', () => {
  assert.equal(activityState({ status: 'in_progress', unread_count: 0, awaiting_reply: false }),
               'awaiting_them');
});

test('activityState of a closed ticket is closed even with unread messages', () => {
  assert.equal(activityState({ status: 'completed', unread_count: 3, awaiting_reply: false }),
               'closed');
  assert.equal(activityState({ status: 'rejected', unread_count: 0, awaiting_reply: false }),
               'closed');
});

test('activityState tolerates a missing unread count', () => {
  assert.equal(activityState({ status: 'pending', awaiting_reply: true }), 'awaiting_us');
});

test('rowSubtitle names the topic and the vehicle when both are known', () => {
  const line = rowSubtitle({ topic: 'billing', topic_label: 'مالی و اشتراک',
                             car: { id: 1, name: 'Toyota Corolla Cross 2024' },
                             kind_label: 'پشتیبانی' });
  assert.ok(line.includes('مالی و اشتراک'));
  assert.ok(line.includes('Corolla Cross'));
});

test('rowSubtitle falls back to the kind when nothing is categorised', () => {
  assert.equal(rowSubtitle({ kind_label: 'پشتیبانی' }), 'پشتیبانی');
});
