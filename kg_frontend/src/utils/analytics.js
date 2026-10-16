// utils/analytics.js — Umami helpers usable from any module (no hooks, no
// 'use client'); every call is a no-op on the server or if the tracker is
// blocked. The page-view component lives in components/Analytics.jsx.
//
// The tracker is loaded with auto-track OFF so every URL goes through redact():
// query strings are dropped and secret path segments (invite tokens) never
// leave the browser.

const SECRET_SEGMENTS = [/^\/invite\/[^/]+/];

export function redact(path) {
  let p = (path || '/').split('?')[0].split('#')[0];
  for (const re of SECRET_SEGMENTS) p = p.replace(re, (m) => m.replace(/[^/]+$/, ':token'));
  return p;
}

export function withUmami(fn, tries = 20) {
  if (typeof window === 'undefined') return;
  if (window.umami) {
    try { fn(window.umami); } catch { /* analytics never breaks the app */ }
    return;
  }
  if (tries > 0) setTimeout(() => withUmami(fn, tries - 1), 500);
}

// Funnel event, e.g. track('purchase_request', { plan: 'monthly' }).
export function track(name, data) {
  if (typeof window === 'undefined') return;
  const url = redact(window.location.pathname);
  withUmami((u) => u.track((props) => ({ ...props, url, referrer: '', name, data })));
}
