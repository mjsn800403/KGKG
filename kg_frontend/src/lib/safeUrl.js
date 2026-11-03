// Small guards for values that reach a URL or an identifier. Kept here, free of
// React and of the Next runtime, so they can be unit tested with `node --test`.

// A link the assistant cites may only point inside the app: one leading slash,
// not "//host", not "/\host", and no control characters (browsers drop tab,
// CR and LF inside a URL, so "/\t/evil.com" would otherwise become "//evil.com").
// eslint-disable-next-line no-control-regex
const CONTROL = /[\u0000-\u001f\u007f]/;

export function isInternalHref(href) {
  return typeof href === 'string'
    && href.startsWith('/')
    && !href.startsWith('//')
    && !href.startsWith('/\\')
    && !CONTROL.test(href);
}

// A Metis session id becomes one path segment of a request carrying our API key.
// Whatever the browser sends must not be able to add segments or climb out.
const SESSION_ID = /^(?!\.+$)[\w.~-]{1,128}$/;

export function isSafeSessionId(id) {
  return typeof id === 'string' && SESSION_ID.test(id);
}

// The only two Metis endpoints the chat route calls. Anything else is a bug (or an
// attack) and throws before a request is made.
export function metisPath(kind, sessionId) {
  const id = Number.isInteger(sessionId) ? String(sessionId) : sessionId;   // numeric ids stay valid
  if (kind === 'session' && id === undefined) return 'session';
  if (kind === 'session' && isSafeSessionId(id)) return `session/${id}/message`;
  throw new Error('refusing to build a Metis path from an unexpected value');
}

// Per-browser id sent as the assistant's userId and used to keep a conversation's
// context: it must not be guessable, so no Math.random.
export function newClientId() {
  const c = globalThis.crypto;
  if (c && typeof c.randomUUID === 'function') return `web-${c.randomUUID()}`;
  if (c && typeof c.getRandomValues === 'function') {
    const b = c.getRandomValues(new Uint8Array(16));
    return `web-${Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('')}`;
  }
  throw new Error('no secure random source available');
}
