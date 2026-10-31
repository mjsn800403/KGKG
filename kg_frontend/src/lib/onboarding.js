// When the feature-discovery strip shows, and what it says.
//
// The server decides what a seat is entitled to and what it has found
// (api/onboarding.py); this file decides only whether to say anything about
// it. The rules are here, pure and tested, because the failure mode is a
// product that nags: a strip that appears with nothing to suggest, or that
// comes back after someone closed it, trains people to ignore everything the
// interface tells them — including the things that matter.

import { faNum } from './support.js';

/** Whether the strip has anything worth saying. False on a malformed payload:
 *  a discovery hint is an enhancement, and it must never be the reason a page
 *  fails to render. */
export function shouldShowStrip(payload) {
  if (!payload || !Array.isArray(payload.items)) return false;
  if (payload.dismissed) return false;
  return payload.items.some((i) => !i.done);
}

/** The first outstanding item — what the collapsed one-liner points at. */
export function nextItem(payload) {
  if (!payload || !Array.isArray(payload.items)) return null;
  return payload.items.find((i) => !i.done) || null;
}

/** '۲ از ۵ قدم' — a fraction, so the end is visible from the start. */
export function progressLabel(done, total) {
  return `${faNum(done)} از ${faNum(total)} قدم`;
}
