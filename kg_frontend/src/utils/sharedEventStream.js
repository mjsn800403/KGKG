// One event-stream connection per audience (admin or portal) per browser tab,
// shared by every component that subscribes. Each SSE connection holds a server
// request thread and runs a query every second, so five components must not mean
// five connections.
//
// `open` is the real connector: ({admin, onEvent, onStatus}) => close.
// The connection opens with the first subscriber and closes shortly after the
// last one leaves; the short grace period keeps a tab switch (unmount then mount)
// from tearing the stream down and re-opening it.

export const CLOSE_GRACE_MS = 1500;

export function createSharedEventStream({ open, setTimer = setTimeout, clearTimer = clearTimeout } = {}) {
  /** key -> {subs:Set, status, close, timer} */
  const hubs = new Map();

  function hubFor(admin) {
    const key = admin ? 'admin' : 'portal';
    let hub = hubs.get(key);
    if (!hub) {
      hub = { subs: new Set(), status: 'idle', close: null, timer: null, dead: false };
      hubs.set(key, hub);
    }
    return hub;
  }

  function connect(admin, hub) {
    hub.status = 'connecting';
    hub.dead = false;
    hub.close = open({
      admin,
      onStatus: (s) => {
        hub.status = s;
        hub.subs.forEach((sub) => sub.onStatus?.(s));
        if (s === 'unauthorized') {
          // The session is gone and the connector has stopped: forget this
          // connection so the next subscriber (after signing in again) opens a
          // fresh one with the new credentials instead of inheriting a dead one.
          hub.dead = true;
          const close = hub.close;
          hub.close = null;
          close?.();
        }
      },
      onEvent: (evt) => {
        // A throwing subscriber must not stop delivery to the others.
        hub.subs.forEach((sub) => { try { sub.onEvent?.(evt); } catch { /* isolate */ } });
      },
    });
    // The connector can report 'unauthorized' before it returns (no token at all).
    if (hub.dead) hub.close = null;
  }

  return {
    /** Returns an unsubscribe function. */
    subscribe(admin, handlers) {
      const hub = hubFor(admin);
      const sub = { onEvent: handlers.onEvent, onStatus: handlers.onStatus };
      if (hub.timer) { clearTimer(hub.timer); hub.timer = null; }
      hub.subs.add(sub);
      if (!hub.close) connect(admin, hub);
      else sub.onStatus?.(hub.status);            // a late joiner learns the current state
      let done = false;
      return () => {
        if (done) return;
        done = true;
        hub.subs.delete(sub);
        if (hub.subs.size === 0 && !hub.timer) {
          hub.timer = setTimer(() => {
            hub.timer = null;
            if (hub.subs.size === 0 && hub.close) {
              const close = hub.close;
              hub.close = null;
              hub.status = 'idle';
              close();
            }
          }, CLOSE_GRACE_MS);
        }
      };
    },
    /** For tests and diagnostics. */
    stats() {
      return Object.fromEntries([...hubs].map(([k, h]) => [k, { subscribers: h.subs.size, open: !!h.close, status: h.status }]));
    },
  };
}
