// When the feature-discovery strip shows, and what it says.
//
// These are the rules worth pinning: a strip that appears when there is
// nothing to say, or stays after someone dismissed it, is a nag — and a nag
// gets ignored along with everything else the product tries to tell you.
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { shouldShowStrip, nextItem, progressLabel } from '../onboarding.js';

const payload = (items, dismissed = false) => ({
  items, dismissed,
  done: items.filter((i) => i.done).length,
  total: items.length,
});
const ITEM = (id, done, href = '/x') => ({ id, title: `t-${id}`, why: 'w', href, done });

describe('shouldShowStrip', () => {
  test('shows while an entitled item is outstanding', () => {
    assert.equal(shouldShowStrip(payload([ITEM('a', true), ITEM('b', false)])), true);
  });

  test('hides when every entitled item is done', () => {
    assert.equal(shouldShowStrip(payload([ITEM('a', true)])), false);
  });

  test('hides for a seat with no entitled items at all', () => {
    // A freshly invited seat with nothing assigned. The server really does
    // return this now: before the 2026-10-30 review `ask_support` was
    // entitled unconditionally, so this state was unreachable and this test
    // was pinning a fiction while the real screen showed a strip.
    assert.equal(shouldShowStrip(payload([])), false);
  });

  test('hides when dismissed, even with items outstanding', () => {
    assert.equal(shouldShowStrip(payload([ITEM('a', false)], true)), false);
  });

  test('hides on a missing or malformed payload rather than throwing', () => {
    for (const bad of [null, undefined, {}, { items: null }]) {
      assert.equal(shouldShowStrip(bad), false);
    }
  });
});

describe('nextItem', () => {
  test('returns the first item that is not done', () => {
    assert.equal(nextItem(payload([ITEM('a', true), ITEM('b', false), ITEM('c', false)])).id, 'b');
  });

  test('returns null when none remain', () => {
    assert.equal(nextItem(payload([ITEM('a', true)])), null);
  });

  test('returns null on a malformed payload', () => {
    assert.equal(nextItem(null), null);
    assert.equal(nextItem({}), null);
  });
});

describe('progressLabel', () => {
  test('reads as a fraction in Persian digits', () => {
    assert.equal(progressLabel(2, 5), '۲ از ۵ قدم');
  });

  test('zero done is still a fraction, not an empty string', () => {
    assert.equal(progressLabel(0, 3), '۰ از ۳ قدم');
  });
});

describe('items that are not links', () => {
  test('an item with no href is still returned by nextItem', () => {
    // Search, parts and the CSV exports live inside a vehicle, so they carry
    // href: null rather than pointing back at the page the strip is on. They
    // are still the next thing worth doing.
    const n = nextItem(payload([ITEM('a', true), ITEM('use_search', false, null)]));
    assert.equal(n.id, 'use_search');
    assert.equal(n.href, null);
  });
});
