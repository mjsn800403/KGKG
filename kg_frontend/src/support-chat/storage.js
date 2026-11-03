// What the widget keeps in the visitor's browser, and nothing else:
//   localStorage   kg_sc_v1    thread id, token, intent  (survives the tab)
//   sessionStorage kg_sc_q_v1  unsent messages           (this tab, 24 h cap)
// Both can be unavailable, full or throw (private windows, blocked storage):
// every access is guarded and the store falls back to memory, so the chat still
// works for the current page view. Message text is never written to localStorage.

export const THREAD_KEY = 'kg_sc_v1';
export const QUEUE_KEY = 'kg_sc_q_v1';
export const QUEUE_MAX = 20;
export const QUEUE_TTL_MS = 24 * 60 * 60 * 1000;

function guarded(backing) {
  const mem = new Map();
  return {
    get(key) {
      try {
        const v = backing?.getItem(key);
        if (v !== null && v !== undefined) return v;
      } catch { /* fall through to memory */ }
      return mem.has(key) ? mem.get(key) : null;
    },
    set(key, value) {
      mem.set(key, value);
      try { backing?.setItem(key, value); } catch { /* memory copy remains */ }
    },
    remove(key) {
      mem.delete(key);
      try { backing?.removeItem(key); } catch { /* ignore */ }
    },
  };
}

function parse(raw, fallback) {
  try {
    const v = JSON.parse(raw);
    return v && typeof v === 'object' ? v : fallback;
  } catch { return fallback; }
}

export function createStore({ local, session, now = () => Date.now() } = {}) {
  const loc = guarded(local);
  const ses = guarded(session);
  const listeners = new Set();
  const emit = () => listeners.forEach((fn) => { try { fn(); } catch { /* listener bug */ } });

  function thread() {
    const t = parse(loc.get(THREAD_KEY), null);
    return t && typeof t.threadId === 'string' && typeof t.token === 'string' ? t : null;
  }

  function queue() {
    const items = parse(ses.get(QUEUE_KEY), []);
    const list = Array.isArray(items) ? items : [];
    const fresh = list.filter((m) => m && typeof m.clientId === 'string'
      && typeof m.body === 'string' && now() - m.at < QUEUE_TTL_MS);
    if (fresh.length !== list.length) ses.set(QUEUE_KEY, JSON.stringify(fresh));
    return fresh;
  }

  return {
    thread,
    saveThread(t) {
      loc.set(THREAD_KEY, JSON.stringify({
        threadId: t.threadId, token: t.token, intent: t.intent || 'other', savedAt: now(),
      }));
      emit();
    },
    clearThread() { loc.remove(THREAD_KEY); emit(); },
    queue,
    /** false when the queue is full: the caller must keep the text in the composer. */
    enqueue({ clientId, body, token, intent }) {
      const list = queue();
      if (list.some((m) => m.clientId === clientId)) return true;
      if (list.length >= QUEUE_MAX) return false;
      // `token` is the thread token a first message will create the thread with,
      // kept (this tab only) so a retry after a lost response reuses it.
      list.push({ clientId, body, at: now(), ...(token ? { token } : {}), ...(intent ? { intent } : {}) });
      ses.set(QUEUE_KEY, JSON.stringify(list));
      emit();
      return true;
    },
    dequeue(clientId) {
      ses.set(QUEUE_KEY, JSON.stringify(queue().filter((m) => m.clientId !== clientId)));
      emit();
    },
    /** "Delete this conversation from this browser". */
    forget() { loc.remove(THREAD_KEY); ses.remove(QUEUE_KEY); emit(); },
    onChange(fn) { listeners.add(fn); return () => listeners.delete(fn); },
  };
}
