'use client';

import { useEffect, useRef, useState } from 'react';
import Icon from './Icon';

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
    return new Date(iso).toLocaleString('fa-IR', { dateStyle: 'short', timeStyle: 'short' });
  } catch { return iso; }
}

export default function TicketThread({
  messages = [],
  onSend,
  disabled = false,
  placeholder = 'پاسخ خود را بنویسید…',
  sendLabel = 'ارسال',
  allowInternal = false,
  note = null,
}) {
  const [text, setText] = useState('');
  const [internal, setInternal] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const endRef = useRef(null);

  useEffect(() => { endRef.current?.scrollIntoView({ block: 'nearest' }); }, [messages.length]);

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
      <ol className="tkt-msgs">
        {messages.map((m) => (
          <li
            key={m.id}
            className={`tkt-msg tkt-msg-${m.author?.kind === 'admin' ? 'admin' : 'user'}${m.internal ? ' tkt-msg-internal' : ''}`}
          >
            <div className="tkt-msg-head">
              <b className="tkt-msg-who">{m.author?.name || '—'}</b>
              {m.internal && <span className="tkt-internal-tag">یادداشت داخلی</span>}
              <span className="tkt-msg-when">{fmtTime(m.created_at)}</span>
            </div>
            <p className="tkt-msg-body">{m.body}</p>
          </li>
        ))}
      </ol>
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
