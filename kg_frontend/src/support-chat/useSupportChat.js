'use client';

import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import { createClient } from './client';
import { createStore } from './storage';
import { createTurnstile } from './turnstile';
import { browserRandomBytes, makeClientId, makeToken } from './token';
import { initialState, reduce, awaitingReply, shouldFallBack } from './state';
import { nextPollDelay } from './schedule';

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE || '/kg-api').replace(/\/+$/, '');
const STATUS_EVERY_MS = 30000;
const FALLBACK_AFTER_S = Number(process.env.NEXT_PUBLIC_SUPPORT_LIVE_FALLBACK_S) || 90;
const MAX_LEN = 2000;

function safe(name) {
  try { return window[name]; } catch { return undefined; }
}

/**
 * All behaviour of the visitor widget. Components only render `chat` and call
 * its actions. Network, storage and the clock are injected at the edges so the
 * pure modules (client, storage, state, schedule) carry the tests.
 */
export default function useSupportChat() {
  const [state, dispatch] = useReducer(reduce, undefined, initialState);
  const [avail, setAvail] = useState({ known: false, enabled: true, mode: 'async', replyTarget: null });
  const [online, setOnline] = useState(() => typeof navigator === 'undefined' || navigator.onLine !== false);
  const [notice, setNotice] = useState(null);        // {kind, text?, until?} shown beside the composer
  const [security, setSecurity] = useState('idle');  // idle | working | failed
  const stateRef = useRef(state);
  stateRef.current = state;
  const pollRef = useRef({ errors: 0, retryAfter: 0, timer: null, inflight: false });
  const lastSendRef = useRef(0);
  const mountRef = useRef(null);                     // element Turnstile renders into
  const setMount = useCallback((el) => { mountRef.current = el; }, []);
  const seqRef = useRef(0);                          // makes each rate-limit notice a fresh countdown
  const turnstileRef = useRef(null);

  const client = useMemo(() => createClient({ fetch: (...a) => window.fetch(...a), base: API_BASE }), []);
  const store = useMemo(() => createStore({ local: safe('localStorage'), session: safe('sessionStorage') }), []);

  const getTurnstile = useCallback(() => {
    if (!turnstileRef.current) {
      turnstileRef.current = createTurnstile({
        doc: document,
        getApi: () => window.turnstile,
        mount: () => mountRef.current,
      });
    }
    return turnstileRef.current;
  }, []);

  /* ---------- restore ---------- */
  useEffect(() => {
    const t = store.thread();
    if (t) dispatch({ type: 'restore', threadId: t.threadId, intent: t.intent });
    const off = store.onChange(() => {
      const cur = store.thread();
      if (!cur && stateRef.current.threadId) dispatch({ type: 'reset' });
    });
    const onStorage = (e) => {
      if (e.key !== 'kg_sc_v1') return;
      const cur = store.thread();
      if (cur && !stateRef.current.threadId) dispatch({ type: 'restore', threadId: cur.threadId, intent: cur.intent });
      if (!cur && stateRef.current.threadId) dispatch({ type: 'reset' });
    };
    window.addEventListener('storage', onStorage);
    const up = () => setOnline(true);
    const down = () => setOnline(false);
    window.addEventListener('online', up);
    window.addEventListener('offline', down);
    return () => {
      off();
      window.removeEventListener('storage', onStorage);
      window.removeEventListener('online', up);
      window.removeEventListener('offline', down);
      turnstileRef.current?.dispose();
    };
  }, [store]);

  /* ---------- availability ---------- */
  const refreshStatus = useCallback(async () => {
    const s = stateRef.current;
    const r = await client.status(s.intentChosen ? s.intent : undefined);
    if (r.ok) {
      setAvail({ known: true, enabled: r.data.enabled !== false, mode: r.data.mode === 'live' ? 'live' : 'async',
        replyTarget: r.data.reply_target_minutes ?? null });
    } else {
      setAvail((a) => ({ ...a, known: false, mode: 'async' }));
    }
  }, [client]);

  useEffect(() => {
    if (!state.panelOpen) return undefined;
    const first = setTimeout(refreshStatus, 0);
    const iv = setInterval(refreshStatus, STATUS_EVERY_MS);
    return () => { clearTimeout(first); clearInterval(iv); };
  }, [state.panelOpen, state.intentChosen, state.intent, refreshStatus]);

  /* ---------- polling ---------- */
  const pollOnce = useCallback(async () => {
    const t = store.thread();
    const p = pollRef.current;
    if (!t || p.inflight) return;
    p.inflight = true;
    const r = await client.poll(t.threadId, t.token, stateRef.current.lastId);
    p.inflight = false;
    if (r.ok) {
      p.errors = 0; p.retryAfter = 0;
      dispatch({ type: 'poll', messages: r.data.messages, status: r.data.status, mode: r.data.mode,
        staffSeenAt: r.data.staff_seen_at, canReopen: r.data.can_reopen });
    } else if (r.kind === 'not_found') {
      store.forget();
      dispatch({ type: 'gone' });
    } else if (r.kind === 'rate_limited') {
      p.retryAfter = r.retryAfter;
    } else if (!r.aborted) {
      p.errors += 1;
    }
  }, [client, store]);

  const schedule = useCallback(() => {
    const p = pollRef.current;
    clearTimeout(p.timer);
    const s = stateRef.current;
    const delay = nextPollDelay({
      hasThread: !!s.threadId, closed: s.phase === 'closed', hidden: document.hidden,
      panelOpen: s.panelOpen, mode: s.mode, awaitingReply: awaitingReply(s),
      msSinceSend: Date.now() - lastSendRef.current, errors: p.errors, retryAfter: p.retryAfter,
    });
    if (delay === null) return;
    p.timer = setTimeout(async () => { await pollOnce(); schedule(); }, delay);
  }, [pollOnce]);

  useEffect(() => {
    const p = pollRef.current;
    schedule();
    return () => clearTimeout(p.timer);
  }, [schedule, state.threadId, state.panelOpen, state.phase, state.mode, state.messages.length]);

  // First look at a stored thread, and again whenever the tab becomes visible.
  useEffect(() => {
    if (state.threadId) pollOnce().then(schedule);
  }, [state.threadId, pollOnce, schedule]);
  useEffect(() => {
    const onVisible = () => { if (!document.hidden && stateRef.current.threadId) pollOnce().then(schedule); };
    document.addEventListener('visibilitychange', onVisible);
    return () => document.removeEventListener('visibilitychange', onVisible);
  }, [pollOnce, schedule]);

  /* ---------- live to async fallback (a statement about this thread, not a promise) ---------- */
  useEffect(() => {
    if (state.mode !== 'live' || state.fellBack) return undefined;
    const iv = setInterval(() => {
      const s = stateRef.current;
      const first = s.messages.find((m) => m.kind === 'visitor');
      if (shouldFallBack({ mode: s.mode, messages: s.messages, fellBack: s.fellBack, now: Date.now(),
        firstSentAt: first ? new Date(first.at).getTime() || lastSendRef.current : 0, afterSeconds: FALLBACK_AFTER_S })) {
        dispatch({ type: 'fell_back' });
      }
    }, 5000);
    return () => clearInterval(iv);
  }, [state.mode, state.fellBack]);

  /* ---------- sending ---------- */
  const deliver = useCallback(async ({ clientId, body, intent, token }) => {
    setNotice(null);
    const existing = store.thread();
    if (existing) {
      const r = await client.send(existing.threadId, existing.token, { message: body, clientId });
      if (r.ok) {
        store.dequeue(clientId);
        dispatch({ type: 'send_ok', clientId, threadId: existing.threadId, message: r.data });
        return true;
      }
      dispatch({ type: 'send_fail', clientId });
      if (r.kind === 'closed') { store.dequeue(clientId); dispatch({ type: 'poll', messages: [], status: 'closed', canReopen: r.canReopen }); }
      else if (r.kind === 'not_found') { store.forget(); dispatch({ type: 'gone' }); }
      else if (r.kind === 'rate_limited') setNotice({ kind: 'rate_limited', seconds: r.retryAfter, seq: ++seqRef.current });
      else if (r.kind === 'invalid') setNotice({ kind: 'invalid', text: r.message });
      else setNotice({ kind: r.kind });
      return false;
    }
    // First message: Turnstile, then create with a browser-made token so a retry
    // after a lost response lands on the same thread.
    setSecurity('working');
    let ts;
    try {
      ts = await getTurnstile().execute();
    } catch (e) {
      setSecurity('failed');
      dispatch({ type: 'send_fail', clientId });
      setNotice({ kind: 'security', reason: e?.kind || 'failed' });
      return false;
    }
    setSecurity('idle');
    const r = await client.create({
      token, message: body, clientId, intent, page: window.location.pathname,
      referrer: document.referrer || '', turnstileToken: ts,
    });
    if (r.ok) {
      store.saveThread({ threadId: r.data.thread_id, token, intent });
      dispatch({ type: 'created', threadId: r.data.thread_id, mode: r.data.mode });
      lastSendRef.current = Date.now();
      if (!r.data.message) {
        // The same token had already created this thread (an earlier first
        // message whose reply was lost): send this one as an ordinary message.
        return deliver({ clientId, body, intent, token: undefined });
      }
      store.dequeue(clientId);
      dispatch({ type: 'send_ok', clientId, threadId: r.data.thread_id, message: r.data.message });
      return true;
    }
    getTurnstile().reset();
    dispatch({ type: 'send_fail', clientId });
    if (r.kind === 'not_found') setNotice({ kind: 'unavailable' });
    else if (r.kind === 'rate_limited') setNotice({ kind: 'rate_limited', seconds: r.retryAfter, seq: ++seqRef.current });
    else if (r.kind === 'invalid') setNotice({ kind: 'invalid', text: r.message });
    else setNotice({ kind: r.kind });
    return false;
  }, [client, store, getTurnstile]);

  const send = useCallback(async (text) => {
    const body = String(text || '').trim().slice(0, MAX_LEN);
    if (!body) return false;
    const clientId = makeClientId(browserRandomBytes);
    const intent = stateRef.current.intent;
    // Before a thread exists every first message shares one token, so a retry
    // (or a second message after a failed first one) can never create two threads.
    const token = store.thread() ? undefined
      : (store.queue().find((m) => m.token)?.token || makeToken(browserRandomBytes));
    if (!store.enqueue({ clientId, body, token, intent })) { setNotice({ kind: 'queue_full' }); return false; }
    lastSendRef.current = Date.now();
    dispatch({ type: 'send_start', clientId, body, at: new Date().toISOString() });
    return deliver({ clientId, body, intent, token });
  }, [deliver, store]);

  const retry = useCallback((clientId) => {
    const q = store.queue().find((m) => m.clientId === clientId);
    const m = stateRef.current.messages.find((x) => x.clientId === clientId);
    const body = q?.body || m?.body;
    if (!body) return;
    dispatch({ type: 'send_start', clientId, body, at: m?.at || new Date().toISOString() });
    deliver({ clientId, body, intent: q?.intent || stateRef.current.intent, token: q?.token });
  }, [deliver, store]);

  // Anything still queued when the connection returns is sent once.
  useEffect(() => {
    if (!online) return;
    for (const q of store.queue()) {
      const m = stateRef.current.messages.find((x) => x.clientId === q.clientId);
      if (m && m.delivery === 'failed') retry(q.clientId);
    }
  }, [online, store, retry]);

  /* ---------- other actions ---------- */
  const saveContact = useCallback(async (contact) => {
    const t = store.thread();
    if (!t) return { ok: false, message: '' };
    const r = await client.contact(t.threadId, t.token, contact);
    return r.ok ? { ok: true } : { ok: false, message: r.message || '' };
  }, [client, store]);

  const reopen = useCallback(async () => {
    const t = store.thread();
    if (!t) return;
    const r = await client.reopen(t.threadId, t.token);
    if (r.ok) { dispatch({ type: 'reopened' }); pollOnce().then(schedule); }
    else setNotice({ kind: r.kind === 'conflict' ? 'reopen_expired' : r.kind });
  }, [client, store, pollOnce, schedule]);

  const rate = useCallback(async (score) => {
    const t = store.thread();
    if (!t) return;
    const r = await client.rate(t.threadId, t.token, score);
    if (r.ok || (r.kind === 'conflict' && r.code === 'already_rated')) dispatch({ type: 'rated' });
  }, [client, store]);

  const newChat = useCallback(() => { store.forget(); dispatch({ type: 'reset' }); setNotice(null); }, [store]);

  return {
    state, avail, online, notice, security, setMount,
    open: () => { dispatch({ type: 'panel', open: true }); try { getTurnstile().prepare().catch(() => {}); } catch { /* blocked later */ } },
    close: () => dispatch({ type: 'panel', open: false }),
    setIntent: (intent) => dispatch({ type: 'intent', intent }),
    send, retry, saveContact, reopen, rate, newChat, forget: newChat,
    getDraft: store.draft, saveDraft: store.saveDraft,
    clearNotice: () => setNotice(null),
    retrySecurity: () => { setSecurity('idle'); setNotice(null); },
    ackGone: () => dispatch({ type: 'reset' }),
    maxLength: MAX_LEN,
  };
}
