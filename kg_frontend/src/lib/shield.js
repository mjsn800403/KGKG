// Browser half of the content shield (backend: api/shield.py).
//
//  * keys come from /api/shield/key/ (session cookie), per session, rotating
//    every 10 minutes; nothing is stored outside this module's memory;
//  * shieldFetch() signs each content API call (single-use nonce) and opens
//    the sealed {_kg,e,iv,ct} answer, returning a normal Response;
//  * unseal() opens blobs the Next.js server sealed into SSR props.
// When the shield is off the key endpoint says {on:false} and everything
// passes through untouched. The production build obfuscates this file
// (scripts/obfuscate-shield.mjs).
import { SHIELD_BASE as BASE } from './shieldBase';
const AAD = new TextEncoder().encode('kg1');

let current = null;              // { on, e, enc, sig, until }
const encByEpoch = new Map();    // epoch -> CryptoKey (AES-GCM)

const bytes = (b64) => Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
const b64 = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf)));

function nonce() {
  const a = crypto.getRandomValues(new Uint8Array(18));
  return b64(a).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

async function loadKeys(e) {
  const res = await fetch(`${BASE}/api/shield/key/${e != null ? `?e=${e}` : ''}`,
    { cache: 'no-store', credentials: 'same-origin' });
  if (!res.ok) throw new Error(`shield key ${res.status}`);
  const k = await res.json();
  if (!k.on) return { on: false, until: Date.now() + 60000 };
  const enc = await crypto.subtle.importKey('raw', bytes(k.enc), 'AES-GCM', false, ['decrypt']);
  encByEpoch.set(k.e, enc);
  if (encByEpoch.size > 4) encByEpoch.delete(encByEpoch.keys().next().value);
  const sig = await crypto.subtle.importKey('raw', bytes(k.sig), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  return { on: true, e: k.e, enc, sig, until: Date.now() + Math.max(5, k.ttl - 5) * 1000 };
}

async function keysNow(force = false) {
  if (force || !current || Date.now() > current.until) current = await loadKeys();
  return current;
}

async function encKey(e) {
  if (!encByEpoch.has(e)) await loadKeys(e);
  return encByEpoch.get(e);
}

async function open(blob) {
  const key = await encKey(blob.e);
  const pt = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: bytes(blob.iv), additionalData: AAD },
    key, bytes(blob.ct));
  return new TextDecoder().decode(pt);
}

export const isSealed = (v) => !!v && typeof v === 'object' && v._kg === 1;

// SSR-sealed prop -> the original value.
export async function unseal(blob) {
  return isSealed(blob) ? JSON.parse(await open(blob)) : blob;
}

async function signedHeaders(url, method, k) {
  const u = new URL(url, window.location.origin);
  let path = decodeURIComponent(u.pathname);
  if (BASE && path.startsWith(BASE)) path = path.slice(BASE.length) || '/';
  const n = nonce();
  const msg = `${method}\n${path}\n${u.search.replace(/^\?/, '')}\n${k.e}\n${n}`;
  const s = await crypto.subtle.sign('HMAC', k.sig, new TextEncoder().encode(msg));
  return { 'X-KG-E': String(k.e), 'X-KG-N': n, 'X-KG-S': b64(s) };
}

// fetch() for the shielded content APIs. Same contract as fetch.
export async function shieldFetch(url, opts = {}) {
  if (typeof window === 'undefined' || !window.crypto?.subtle) return fetch(url, opts);
  let k;
  try { k = await keysNow(); } catch { return fetch(url, opts); }
  if (!k.on) return fetch(url, opts);
  const method = (opts.method || 'GET').toUpperCase();
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const headers = { ...(opts.headers || {}), ...(await signedHeaders(url, method, k)) };
    const res = await fetch(url, { ...opts, headers });
    if (res.status === 403 && attempt === 0) {
      const body = await res.clone().json().catch(() => ({}));
      if (body?.error === 'shield') { k = await keysNow(true); if (k.on) continue; return fetch(url, opts); }
    }
    if (!res.ok || !(res.headers.get('content-type') || '').includes('json')) return res;
    const data = await res.json();
    const text = isSealed(data) ? await open(data) : JSON.stringify(data);
    return new Response(text, { status: res.status, statusText: res.statusText, headers: res.headers });
  }
  return fetch(url, opts);
}
