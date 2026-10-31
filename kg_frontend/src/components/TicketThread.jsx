'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import Icon from './Icon';
import { firstUnreadIndex, groupByDay } from '../lib/support';

// The conversation on a support ticket, used by both sides of the desk.
//
// Before this existed, the platform side's whole record of a ticket was one
// `admin_note` field that a reply overwrote, so any back-and-forth happened by
// telephone and was then lost. A message here belongs to exactly one side, and
// an internal note is one the customer never receives — it is filtered out of
// their response server-side (api/requests_api._thread), so nothing here is
// relied upon to keep it private.

function fmtTime(iso) {
  try {
    return new Date(iso).toLocaleString('fa-IR', { timeStyle: 'short' });
  } catch { return iso; }
}

function fmtDay(day) {
  try {
    const d = new Date(`${day}T00:00:00`);
    const today = new Date();
    const same = (a, b) => a.toDateString() === b.toDateString();
    if (same(d, today)) return 'امروز';
    const yesterday = new Date(today.getTime() - 86400000);
    if (same(d, yesterday)) return 'دیروز';
    return d.toLocaleDateString('fa-IR', { dateStyle: 'full' });
  } catch { return day; }
}

export default function TicketThread({
  messages = [],
  onSend,
  disabled = false,
  placeholder = 'پاسخ خود را بنویسید…',
  sendLabel = 'ارسال',
  allowInternal = false,
  note = null,
  unreadCount = 0,
  truncated = false,
}) {
  const [text, setText] = useState('');
  const [internal, setInternal] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const endRef = useRef(null);
  const unreadRef = useRef(null);

  const groups = useMemo(() => groupByDay(messages), [messages]);
  const unreadAt = useMemo(() => firstUnreadIndex(messages, unreadCount),
                           [messages, unreadCount]);

  // Resume where the reader stopped. Scrolling to the bottom of a conversation
  // with eight unread replies hides the first seven, which is how a thread
  // stops being read at all. The divider is the anchor when there is one.
  useEffect(() => {
    const target = unreadRef.current || endRef.current;
    target?.scrollIntoView({ block: 'nearest' });
  }, [messages.length, unreadAt]);

  // Enter sends, Shift+Enter is a newline — the convention anybody who has
  // used a chat expects, and the reason this feels like a conversation.
  const onKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (text.trim() && !busy && !disabled) send();
    }
  };

  const send = async () => {
    const body = text.trim();
    if (!body) { setErr('متن پیام خالی است.'); return; }
    setBusy(true); setErr('');
    try {
      await onSend?.(body, { internal });
      setText('');
      setInternal(false);
    } catch (e) {
      setErr(e?.message || 'ارسال ناموفق بود.');
    } finally { setBusy(false); }
  };

  return (
    <div className="tkt-thread">
      {messages.length === 0 && (
        <p className="tkt-thread-empty">هنوز پیامی رد و بدل نشده است.</p>
      )}
      {truncated && (
        <p className="tkt-thread-trunc">
          تنها آخرین پیام‌های این گفت‌وگو نشان داده می‌شود.
        </p>
      )}
      {/* The reader is told about an arriving message without having to watch
          for it; `polite` so it never interrupts what they are typing. */}
      <div className="tkt-msgs-wrap" aria-live="polite" aria-relevant="additions">
        {groups.map((g) => (
          <section key={g.day} className="tkt-day">
            <h4 className="tkt-day-sep"><span>{fmtDay(g.day)}</span></h4>
            <ol className="tkt-msgs">
              {g.messages.map((m) => {
                const idx = messages.indexOf(m);
                const isUnreadStart = unreadAt >= 0 && idx === unreadAt;
                const mine = m.author?.kind === 'admin' ? 'admin' : 'user';
                return (
                  <li key={m.id} ref={isUnreadStart ? unreadRef : null}
                      className={`tkt-msg tkt-msg-${mine}${m.internal ? ' tkt-msg-internal' : ''}`}>
                    {isUnreadStart && (
                      <div className="tkt-unread-sep"><span>پیام‌های تازه</span></div>
                    )}
                    <div className="tkt-msg-head">
                      <b className="tkt-msg-who">{m.author?.name || '—'}</b>
                      {m.internal && <span className="tkt-internal-tag">یادداشت داخلی</span>}
                      <span className="tkt-msg-when">{fmtTime(m.created_at)}</span>
                    </div>
                    <p className="tkt-msg-body">{m.body}</p>
                  </li>
                );
              })}
            </ol>
          </section>
        ))}
      </div>
      <div ref={endRef} />

      {note && <div className="tkt-compose-note">{note}</div>}

      {onSend && (
        <div className="tkt-compose">
          <textarea
            className="tkt-compose-text"
            rows={3}
            value={text}
            disabled={disabled || busy}
            onChange={(e) => { setText(e.target.value); setErr(''); }}
            onKeyDown={onKeyDown}
            placeholder={placeholder}
            aria-label={placeholder}
          />
          <div className="tkt-compose-actions">
            {allowInternal && (
              <label className="tkt-internal-check">
                <input
                  type="checkbox"
                  checked={internal}
                  onChange={(e) => setInternal(e.target.checked)}
                />
                {/* An internal note is never shown to the customer and never
                    counts as the first response. */}
                یادداشت داخلی (مشتری نمی‌بیند)
              </label>
            )}
            <button
              type="button"
              className="btn btn-accent tkt-send"
              disabled={disabled || busy || !text.trim()}
              onClick={send}
            >
              <Icon name="send" size={15} /> {busy ? 'در حال ارسال…' : sendLabel}
            </button>
          </div>
          {err && <div className="pform-error">{err}</div>}
        </div>
      )}
    </div>
  );
}
