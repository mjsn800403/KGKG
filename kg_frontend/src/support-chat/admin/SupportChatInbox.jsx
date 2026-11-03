'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { supportChatApi as api } from '../../utils/supportChatApi';
import useEventStream from '../../utils/useEventStream';
import { friendlyError } from '../../lib/friendlyError';
import {
  FILTERS, INTENT_LABELS, PRIORITY_LABELS, STATUS_LABELS, eventThreadId, heartbeatBody, isChatEvent, mergeMessages,
} from './logic';
import './support-chat-admin.css';

const HEARTBEAT_MS = 20000;
// Fallback refresh. Overridable at build time only so the E2E can switch it off
// and prove the stream alone delivers.
const REFRESH_MS = (Number(process.env.NEXT_PUBLIC_SUPPORT_INBOX_REFRESH_S) || 20) * 1000;
const AWAY_AFTER_MS = 10 * 60 * 1000;
const fmt = (at) => (at ? new Date(at).toLocaleString('fa-IR', { dateStyle: 'short', timeStyle: 'short' }) : '');

function Availability() {
  const [status, setStatus] = useState(null);
  const [err, setErr] = useState('');
  const lastInput = useRef(null);

  useEffect(() => {
    const mark = () => { lastInput.current = Date.now(); };
    mark();                                   // opening the console is itself activity
    const evs = ['keydown', 'pointerdown', 'wheel', 'touchstart'];
    evs.forEach((e) => window.addEventListener(e, mark, { passive: true }));
    return () => evs.forEach((e) => window.removeEventListener(e, mark));
  }, []);

  useEffect(() => {
    api.presence().then(() => {}).catch(() => {});
    const beat = () => {
      const body = heartbeatBody({ signedIn: true, lastInputAt: lastInput.current, now: Date.now(), awayAfterMs: AWAY_AFTER_MS });
      if (body) api.heartbeat(body.active).catch(() => {});
    };
    beat();
    const iv = setInterval(beat, HEARTBEAT_MS);
    return () => clearInterval(iv);
  }, []);

  const set = async (s) => {
    try { await api.setPresence(s); setStatus(s); setErr(''); } catch (e) { setErr(friendlyError(e)); }
  };
  return (
    <div className="scx-avail" role="group" aria-label="وضعیت من">
      <span>وضعیت من:</span>
      {[['available', 'آماده پاسخ'], ['away', 'دور از میز'], ['offline', 'آفلاین']].map(([id, label]) => (
        <button key={id} type="button" className={status === id ? 'is-on' : ''} aria-pressed={status === id} onClick={() => set(id)}>{label}</button>
      ))}
      {err && <span className="scx-err">{err}</span>}
    </div>
  );
}

function ThreadRow({ t, selected, onOpen }) {
  const who = t.contact?.name || (t.contact?.has_phone ? t.contact.phone : '') || `گفتگو ${t.id.slice(0, 6)}`;
  return (
    <li>
      <button type="button" className={`scx-row ${selected ? 'is-sel' : ''}`} onClick={() => onOpen(t.id)} aria-current={selected ? 'true' : undefined}>
        <span className="scx-row-top">
          {t.unread && <span className="scx-dot" aria-label="خوانده‌نشده" />}
          <strong dir="auto">{who}</strong>
          <span className="scx-chip">{INTENT_LABELS[t.intent] || t.intent}</span>
        </span>
        <span className="scx-snippet" dir="auto">{t.last_message ? `${t.last_message.internal ? '🔒 ' : ''}${t.last_message.snippet}` : ''}</span>
        <span className="scx-row-bot">
          <span>{STATUS_LABELS[t.status]}</span>
          {t.priority !== 'normal' && <span className="scx-chip scx-chip-hot">{PRIORITY_LABELS[t.priority]}</span>}
          {t.assignee ? <span>{t.assignee.username}</span> : <span className="scx-muted">بدون مسئول</span>}
          <span className="scx-muted">{fmt(t.last_activity_at)}</span>
        </span>
      </button>
    </li>
  );
}

function ThreadPane({ id, me, onChanged }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState('');
  const [text, setText] = useState('');
  const [internal, setInternal] = useState(false);
  const [busy, setBusy] = useState(false);
  const [reveal, setReveal] = useState(false);
  // The pane is keyed by thread id, so it remounts per conversation and starts clean.
  const load = useCallback(async (opts = {}) => {
    try {
      const d = await api.detail(id, opts.reveal ? { reveal_contact: 1 } : {}, { background: !!opts.background });
      setData((cur) => (cur && !opts.reveal
        ? { ...d, messages: mergeMessages(cur.messages, d.messages) } : d));
      setErr('');
    } catch (e) { setErr(friendlyError(e)); }
  }, [id]);

  useEffect(() => { const t = setTimeout(load, 0); return () => clearTimeout(t); }, [load]);
  // Opening a thread marks it seen once (this drives the visitor's read tick).
  useEffect(() => { api.seen(id).then(() => onChanged?.()).catch(() => {}); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { const h = () => load({ background: true }); window.addEventListener('kg-support-chat-refresh', h); return () => window.removeEventListener('kg-support-chat-refresh', h); }, [load]);

  const act = async (fn) => {
    setBusy(true);
    try { await fn(); await load(); onChanged?.(); setErr(''); } catch (e) { setErr(friendlyError(e)); }
    setBusy(false);
  };
  const send = () => {
    const body = text.trim();
    if (!body) return;
    act(async () => { await api.reply(id, body, internal); setText(''); });
  };

  if (!data) return <div className="scx-pane scx-empty">{err || 'در حال بارگذاری…'}</div>;
  const th = data.thread;
  const closed = th.status === 'closed';
  const spam = th.status === 'spam';
  // What this person may do here (the server re-checks every request). Absent means offer all.
  const caps = data.capabilities || {};
  const can = (k) => caps[k] !== false;
  return (
    <div className="scx-pane">
      <header className="scx-pane-head">
        <div>
          <strong dir="auto">{th.contact.name || `گفتگو ${th.id.slice(0, 6)}`}</strong>
          <div className="scx-muted">
            {STATUS_LABELS[th.status]} · {INTENT_LABELS[th.intent]} · {th.source_page || '—'}
          </div>
          <div className="scx-contact" dir="ltr">
            {th.contact.has_phone && <span>{th.contact.phone}</span>}
            {th.contact.has_email && <span>{th.contact.email}</span>}
            {(th.contact.has_phone || th.contact.has_email) && !reveal && can('reveal_contact') && (
              <button type="button" className="scx-link" onClick={() => { setReveal(true); load({ reveal: true }); }}>نمایش اطلاعات تماس</button>
            )}
          </div>
        </div>
        <div className="scx-actions">
          <button type="button" disabled={busy || !can('take') || (th.assignee && th.assignee.id === me)} onClick={() => act(() => api.assign(id, 'me'))}>
            {th.assignee ? `مسئول: ${th.assignee.username}` : 'برداشتن گفتگو'}
          </button>
          <select aria-label="اولویت" value={th.priority} disabled={busy || !can('priority')} onChange={(e) => act(() => api.priority(id, e.target.value))}>
            {Object.entries(PRIORITY_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          {closed
            ? <button type="button" disabled={busy || !can('reopen')} onClick={() => act(() => api.reopen(id))}>بازگشایی</button>
            : <button type="button" disabled={busy || spam || !can('close')} onClick={() => act(() => api.close(id))}>بستن</button>}
          {spam
            ? <button type="button" disabled={busy || !can('spam')} onClick={() => act(() => api.restore(id))}>بازگرداندن از اسپم</button>
            : <button type="button" disabled={busy || !can('spam')} onClick={() => act(() => api.spam(id))}>اسپم</button>}
        </div>
      </header>

      <div className="scx-log" role="log" aria-label="پیام‌ها">
        {data.messages.map((m) => (
          <div key={m.id} className={`scx-msg scx-${m.author_kind}${m.internal ? ' scx-note' : ''}`}>
            <div className="scx-msg-meta">
              {m.author_kind === 'visitor' ? 'بازدیدکننده' : m.author_kind === 'system' ? 'سامانه' : (m.author?.username || 'پشتیبانی')}
              {m.internal && ' · یادداشت داخلی'} · {fmt(m.created_at)}
            </div>
            <div className="scx-msg-body" dir="auto">{m.body}</div>
          </div>
        ))}
      </div>

      {err && <div className="scx-err" role="alert">{err}</div>}
      {closed || spam || !can('reply') ? null : (
        <form className="scx-compose" onSubmit={(e) => { e.preventDefault(); send(); }}>
          <textarea
            value={text} onChange={(e) => setText(e.target.value)} rows={3} maxLength={2000} dir="auto"
            aria-label={internal ? 'یادداشت داخلی' : 'پاسخ به مشتری'}
            placeholder={internal ? 'یادداشت داخلی (برای مشتری نمایش داده نمی‌شود)' : 'پاسخ به مشتری'}
            onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); send(); } }}
          />
          <div className="scx-compose-bar">
            <label><input type="checkbox" checked={internal} onChange={(e) => setInternal(e.target.checked)} /> یادداشت داخلی</label>
            <button type="submit" disabled={busy || !text.trim()}>{internal ? 'ثبت یادداشت' : 'ارسال پاسخ'}</button>
          </div>
        </form>
      )}
    </div>
  );
}

export default function SupportChatInbox({ me = null }) {
  const [filter, setFilter] = useState('active');
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [data, setData] = useState({ threads: [], counts: {} });
  const [selected, setSelected] = useState(null);
  const [err, setErr] = useState('');
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async (opts = {}) => {
    try {
      const d = await api.list({ status: filter, unread: unreadOnly ? 1 : '' }, { background: !!opts.background });
      setData(d);
      setErr('');
    } catch (e) { setErr(friendlyError(e)); }
    setLoaded(true);
  }, [filter, unreadOnly]);
  useEffect(() => { const t = setTimeout(load, 0); return () => clearTimeout(t); }, [load]);
  // The live stream can drop or be buffered by a proxy; a slow refresh keeps the
  // inbox correct without it, and only while someone is looking at the tab.
  useEffect(() => {
    const iv = setInterval(() => { if (!document.hidden) load({ background: true }); }, REFRESH_MS);
    return () => clearInterval(iv);
  }, [load]);

  useEventStream({
    admin: true,
    onEvent: (evt) => {
      if (!isChatEvent(evt)) return;
      load({ background: true });
      if (eventThreadId(evt)) window.dispatchEvent(new Event('kg-support-chat-refresh'));
    },
  });

  useEffect(() => {
    const base = document.title.replace(/^\(\d+\)\s*/, '');
    const n = data.counts?.unread || 0;
    document.title = n > 0 ? `(${n}) ${base}` : base;
    return () => { document.title = base; };
  }, [data.counts?.unread]);

  return (
    <section className="scx" aria-label="گفتگوهای زنده">
      <div className="scx-top">
        <Availability />
        <div className="scx-filters" role="tablist">
          {FILTERS.map((f) => (
            <button key={f.id} type="button" role="tab" aria-selected={filter === f.id} className={filter === f.id ? 'is-on' : ''} onClick={() => setFilter(f.id)}>
              {f.label} {data.counts?.[f.id] != null ? `(${Number(data.counts[f.id]).toLocaleString('fa-IR')})` : ''}
            </button>
          ))}
          <button type="button" onClick={() => load()}>بازخوانی</button>
          <label className="scx-unread"><input type="checkbox" checked={unreadOnly} onChange={(e) => setUnreadOnly(e.target.checked)} /> فقط خوانده‌نشده ({Number(data.counts?.unread || 0).toLocaleString('fa-IR')})</label>
        </div>
      </div>
      {err && <div className="scx-err" role="alert">{err}</div>}
      <div className="scx-grid">
        <ul className="scx-list" aria-label="فهرست گفتگوها">
          {loaded && data.threads.length === 0 && <li className="scx-empty">گفتگویی در این بخش نیست.</li>}
          {data.threads.map((t) => <ThreadRow key={t.id} t={t} selected={t.id === selected} onOpen={setSelected} />)}
        </ul>
        {selected
          ? <ThreadPane key={selected} id={selected} me={me} onChanged={load} />
          : <div className="scx-pane scx-empty">یک گفتگو را انتخاب کنید.</div>}
      </div>
    </section>
  );
}
