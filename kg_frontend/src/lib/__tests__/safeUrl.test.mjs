// Guards behind three CodeQL findings: js/request-forgery (a client-sent session
// id used as a path segment on the Metis API), js/xss-through-dom (an assistant
// link whose href is rendered) and js/insecure-randomness (the browser user id).
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { isInternalHref, isSafeSessionId, metisPath, newClientId } from '../safeUrl.js';

describe('isInternalHref', () => {
  test('accepts in-app paths, including percent-encoded and Persian ones', () => {
    for (const h of ['/', '/Toyota/2023/Corolla', '/a/b?x=1#y', '/parts/Engine%20Parts', '/موتور/سیستم']) {
      assert.equal(isInternalHref(h), true, h);
    }
  });

  test('refuses anything that is not a single-slash path', () => {
    for (const h of ['//evil.com', '/\\evil.com', 'https://evil.com', 'javascript:alert(1)',
      'data:text/html,x', 'evil.com', '', null, undefined, 42]) {
      assert.equal(isInternalHref(h), false, String(h));
    }
  });

  test('refuses control characters browsers strip from URLs ("/\\t/evil.com" becomes "//evil.com")', () => {
    for (const h of ['/\t/evil.com', '/\n/evil.com', '/\r/evil.com', '/a\u0000b', '/\u0007']) {
      assert.equal(isInternalHref(h), false, JSON.stringify(h));
    }
  });
});

describe('isSafeSessionId / metisPath', () => {
  test('ordinary session ids pass', () => {
    for (const id of ['abc123', '3f2b1c9e-7d11-4f0e-9a55-0c8f2d6b1a77', 'a_b-c.d', 'x'.repeat(128)]) {
      assert.equal(isSafeSessionId(id), true, id);
    }
  });

  test('path tricks do not', () => {
    for (const id of ['..', '.', '../x', 'a/b', 'a?b', 'a#b', 'a%2Fb', 'a b', '', 'x'.repeat(129), null, undefined, 7, {}]) {
      assert.equal(isSafeSessionId(id), false, String(id));
    }
  });

  test('metisPath only builds the two endpoints the route uses', () => {
    assert.equal(metisPath('session'), 'session');
    assert.equal(metisPath('session', 'abc-1'), 'session/abc-1/message');
    assert.throws(() => metisPath('session', '../chats'));
    assert.throws(() => metisPath('session', 'a/b'));
    assert.equal(metisPath('session', 12345), 'session/12345/message');
    assert.throws(() => metisPath('admin'));
  });
});

describe('newClientId', () => {
  test('is prefixed, unpredictable and different each call', () => {
    const ids = new Set(Array.from({ length: 50 }, () => newClientId()));
    assert.equal(ids.size, 50);
    for (const id of ids) assert.match(id, /^web-[0-9a-f-]{16,}$/);
  });

  test('does not rely on Math.random', () => {
    const real = Math.random;
    Math.random = () => { throw new Error('Math.random used'); };
    try { newClientId(); } finally { Math.random = real; }
  });
});
