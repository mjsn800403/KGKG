// friendlyError: backend/transport errors -> one Persian sentence for the UI.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { friendlyError } from '../friendlyError.js';

const DEFAULT = 'بارگذاری اطلاعات ناموفق بود.';
const NETWORK = 'ارتباط با سامانه برقرار نشد. اتصال اینترنت را بررسی کنید و دوباره تلاش کنید.';

test('empty / missing error yields the fallback', () => {
  for (const e of [undefined, null, '', '   ', new Error('')]) assert.equal(friendlyError(e), DEFAULT);
  assert.equal(friendlyError(null, 'سفارشی'), 'سفارشی');
});

test('transport failures map to the network sentence (Error or string, any case)', () => {
  for (const m of ['fetch failed', 'TypeError: Failed to fetch', 'NetworkError when attempting',
    'connect ECONNREFUSED 127.0.0.1:8000', 'read ECONNRESET', 'ETIMEDOUT', 'socket hang up',
    'Network request failed', 'Request Timeout']) {
    assert.equal(friendlyError(new Error(m)), NETWORK, m);
    assert.equal(friendlyError(m), NETWORK, m);
  }
});

test('English developer strings never reach the user', () => {
  assert.equal(friendlyError(new Error('Unexpected token < in JSON at position 0')), DEFAULT);
  assert.equal(friendlyError('500 Internal Server Error', 'خطا'), 'خطا');
});

test('Persian backend messages pass through, trimmed', () => {
  assert.equal(friendlyError(new Error('  اشتراک شما منقضی شده است.  ')), 'اشتراک شما منقضی شده است.');
  assert.equal(friendlyError('کد تأیید نادرست است (401)'), 'کد تأیید نادرست است (401)');
});
