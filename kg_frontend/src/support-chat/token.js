// The visitor's thread token: 32 random bytes as 43 base64url characters,
// generated in the browser so creating a thread is idempotent (a retry carries
// the same token). The server stores only its SHA-256.

const ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';

/** `randomBytes(n)` must return n cryptographically random bytes (Uint8Array). */
export function makeToken(randomBytes) {
  const bytes = randomBytes(32);
  if (!bytes || bytes.length !== 32) throw new Error('need 32 random bytes');
  let out = '';
  let bits = 0;
  let acc = 0;
  for (const b of bytes) {
    acc = (acc << 8) | b;
    bits += 8;
    while (bits >= 6) {
      bits -= 6;
      out += ALPHABET[(acc >> bits) & 63];
    }
    acc &= (1 << bits) - 1;
  }
  if (bits > 0) out += ALPHABET[(acc << (6 - bits)) & 63];
  return out;
}

export function browserRandomBytes(n) {
  const out = new Uint8Array(n);
  globalThis.crypto.getRandomValues(out);
  return out;
}

/** Same shape the server accepts: 43 chars of [A-Za-z0-9_-]. */
export const isToken = (s) => typeof s === 'string' && /^[A-Za-z0-9_-]{43}$/.test(s);

/** A short id for one outgoing message; the retry of that message reuses it. */
export function makeClientId(randomBytes = browserRandomBytes) {
  return 'c' + makeToken(randomBytes).slice(0, 20);
}
