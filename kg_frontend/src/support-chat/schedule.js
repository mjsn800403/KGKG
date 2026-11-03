// How long to wait before the visitor's next poll, or null for "do not poll".
// Visitors poll (they must not hold one of the 24 request threads like an SSE
// stream would). The numbers are a PROPOSAL, unmeasured until the k6 check on
// staging; they stay under the server's 30-per-minute per-thread limit.

export const LIVE_MS = 3000;
export const ASYNC_RECENT_MS = 10000;
export const ASYNC_IDLE_MS = 20000;
export const AWAITING_CLOSED_MS = 60000;
export const BACKOFF_MAX_MS = 60000;
export const RECENT_SEND_WINDOW_MS = 120000;

/**
 * @param {object} s
 * @param {boolean} s.hasThread     a thread exists in this browser
 * @param {boolean} s.closed        the thread is closed (nothing to wait for)
 * @param {boolean} s.hidden        the tab is in the background
 * @param {boolean} s.panelOpen
 * @param {'live'|'async'} s.mode
 * @param {boolean} s.awaitingReply a visitor message is not yet answered
 * @param {number} s.msSinceSend    since the visitor's last message
 * @param {number} s.errors         consecutive failed polls
 * @param {number} [s.retryAfter]   seconds from a 429, if the last poll got one
 * @param {() => number} [rand]     0 <= r < 1, for jitter
 */
export function nextPollDelay(s, rand = Math.random) {
  if (!s.hasThread || s.closed || s.hidden) return null;
  let base;
  if (s.panelOpen) {
    base = s.mode === 'live'
      ? LIVE_MS
      : (s.msSinceSend < RECENT_SEND_WINDOW_MS ? ASYNC_RECENT_MS : ASYNC_IDLE_MS);
  } else if (s.awaitingReply) {
    base = AWAITING_CLOSED_MS;
  } else {
    return null;
  }
  if (s.errors > 0) base = Math.max(base, Math.min(BACKOFF_MAX_MS, 5000 * 2 ** (s.errors - 1)));
  if (s.retryAfter > 0) base = Math.max(base, s.retryAfter * 1000);
  const jitter = 0.8 + 0.4 * rand();
  return Math.round(base * jitter);
}
