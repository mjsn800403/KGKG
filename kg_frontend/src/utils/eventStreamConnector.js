// The Server-Sent Events connector behind openEventStream (api.jsx), with its
// environment injected so every failure mode can be tested without a browser.
//
// fetch()+ReadableStream rather than EventSource, so the Bearer token travels in a
// header and never in the URL. Reconnects with Last-Event-ID so nothing is missed
// across the server's periodic recycle (~300 s).
//
// What it guards against, beyond a clean close:
//   * a stalled connection (half-open TCP, proxy idle drop, laptop sleep): the server
//     sends a comment frame every 15 s, so silence for `stallMs` means the stream is
//     dead and is torn down and reopened;
//   * a server that is down or throttling: retry delay doubles up to `maxRetryMs`
//     with jitter and resets once a stream opens, so a fleet of tabs does not
//     hammer a recovering server every 3 s in lockstep;
//   * the network coming back: an `online` event reconnects at once instead of
//     waiting out the delay;
//   * a revoked or expired session (401): reports `unauthorized` and stops.

export const STALL_MS = 45000;          // three missed server heartbeats
export const MAX_RETRY_MS = 60000;

export function connectEventStream({
  url, headers = () => ({}), onEvent, onStatus,
  fetchFn = (...a) => fetch(...a),
  setTimer = setTimeout, clearTimer = clearTimeout, random = Math.random,
  target = typeof window !== 'undefined' ? window : null,
  stallMs = STALL_MS, maxRetryMs = MAX_RETRY_MS,
} = {}) {
  let closed = false;
  let controller = null;
  let cursor = 0;
  let serverRetry = 3000;               // the server's `retry:` hint is the base delay
  let failures = 0;
  let retryTimer = null;
  let stallTimer = null;
  let running = false;

  function nextDelay() {
    const base = Math.min(maxRetryMs, serverRetry * 2 ** Math.min(Math.max(failures - 1, 0), 6));
    return Math.round(base * (0.75 + random() * 0.5));     // +/-25 %
  }

  function armStall() {
    clearTimer(stallTimer);
    stallTimer = setTimer(() => { try { controller?.abort(); } catch { /* already gone */ } }, stallMs);
  }

  function schedule(delay) {
    if (closed || retryTimer) return;
    retryTimer = setTimer(() => { retryTimer = null; connect(); }, delay);
  }

  async function connect() {
    if (closed || running) return;
    running = true;
    controller = new AbortController();
    onStatus?.('connecting');
    let opened = false;
    try {
      armStall();
      const res = await fetchFn(url, {
        headers: { ...headers(), Accept: 'text/event-stream', ...(cursor ? { 'Last-Event-ID': String(cursor) } : {}) },
        signal: controller.signal,
        cache: 'no-store',
      });
      if (res.status === 401) { onStatus?.('unauthorized'); closed = true; return; }
      if (!res.ok || !res.body) throw new Error(`stream ${res.status}`);
      opened = true;
      failures = 0;
      onStatus?.('open');
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      while (!closed) {
        const { value, done } = await reader.read();
        if (done) break;
        armStall();                                          // any bytes, heartbeats included
        buf += decoder.decode(value, { stream: true });
        let sep;
        while ((sep = buf.indexOf('\n\n')) !== -1) {
          const raw = buf.slice(0, sep);
          buf = buf.slice(sep + 2);
          parseFrame(raw);
        }
      }
    } catch {
      if (closed) return;
    } finally {
      clearTimer(stallTimer);
      stallTimer = null;
      running = false;
    }
    if (closed) return;
    if (!opened) failures += 1;
    onStatus?.('reconnecting');
    // A clean server recycle after a healthy stream reconnects at the base delay.
    schedule(opened ? Math.round(serverRetry * (0.75 + random() * 0.5)) : nextDelay());
  }

  function parseFrame(raw) {
    let ev = 'message';
    let data = '';
    let id = null;
    for (const line of raw.split('\n')) {
      if (line.startsWith(':')) continue;                    // comment / heartbeat
      if (line.startsWith('event:')) ev = line.slice(6).trim();
      else if (line.startsWith('data:')) data += line.slice(5).trim();
      else if (line.startsWith('id:')) id = line.slice(3).trim();
      else if (line.startsWith('retry:')) {
        const n = parseInt(line.slice(6).trim(), 10);
        if (!Number.isNaN(n) && n > 0) serverRetry = n;
      }
    }
    if (id) cursor = parseInt(id, 10) || cursor;
    if (ev === 'ready') {
      try { const d = JSON.parse(data || '{}'); if (d.cursor) cursor = d.cursor; } catch { /* ignore */ }
      return;
    }
    if (ev === 'reconnect') return;                          // graceful server recycle
    if (!data) return;
    let payload = {};
    try { payload = JSON.parse(data); } catch { return; }
    onEvent?.({ type: ev, ...payload });
  }

  function onOnline() {
    if (closed) return;
    if (retryTimer) { clearTimer(retryTimer); retryTimer = null; }
    failures = 0;
    if (!running) connect();
  }
  target?.addEventListener?.('online', onOnline);

  connect();
  return () => {
    closed = true;
    clearTimer(retryTimer);
    clearTimer(stallTimer);
    target?.removeEventListener?.('online', onOnline);
    try { controller?.abort(); } catch { /* already gone */ }
  };
}
