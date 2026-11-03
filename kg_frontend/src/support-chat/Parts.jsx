'use client';

import { useEffect, useRef, useState } from 'react';
import { COPY, LABELS } from './copy.fa';
import { deliveryOf } from './state';

const time = (at) => {
  const d = new Date(at);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleTimeString('fa-IR', { hour: '2-digit', minute: '2-digit' });
};

function Delivery({ message, staffSeenAt, onRetry }) {
  const d = deliveryOf(message, staffSeenAt);
  if (!d) return null;
  if (d === 'failed') {
    return (
      <span className="sc-meta sc-meta-bad">
        {COPY.failed}{' '}
        <button type="button" className="sc-link" onClick={() => onRetry(message.clientId)}>{COPY.retry}</button>
      </span>
    );
  }
  return <span className="sc-meta" data-delivery={d}>{COPY[d === 'sending' ? 'sending' : d === 'read' ? 'read' : 'sent']}</span>;
}

export function MessageList({ messages, staffSeenAt, onRetry }) {
  const endRef = useRef(null);
  useEffect(() => { endRef.current?.scrollIntoView?.({ block: 'end' }); }, [messages.length]);
  return (
    <div className="sc-log" role="log" aria-label={COPY.title} aria-live="off">
      {messages.map((m) => {
        if (m.kind === 'system') {
          return <div key={m.key} className="sc-system"><span>{LABELS.system}: <bdi>{m.body}</bdi></span></div>;
        }
        const mine = m.kind === 'visitor';
        return (
          <div key={m.key} className={`sc-row ${mine ? 'sc-mine' : 'sc-theirs'}`}>
            {!mine && <span className="sc-who">{LABELS.staff}</span>}
            <div className="sc-bubble" dir="auto" data-kind={m.kind}>{m.body}</div>
            <div className="sc-foot">
              <span className="sc-meta">{time(m.at)}</span>
              {mine && <Delivery message={m} staffSeenAt={staffSeenAt} onRetry={onRetry} />}
            </div>
          </div>
        );
      })}
      <div ref={endRef} />
    </div>
  );
}

export function Starters({ onPick }) {
  return (
    <div className="sc-welcome">
      <p className="sc-greet">{COPY.greeting}</p>
      <div className="sc-starters">
        {COPY.starters.map((s) => (
          <button key={s.intent} type="button" className="sc-starter" onClick={() => onPick(s)}>{s.label}</button>
        ))}
      </div>
    </div>
  );
}

export function Composer({ onSend, disabled, placeholder, max, value, setValue }) {
  const ref = useRef(null);
  const submit = () => {
    if (disabled || !value.trim()) return;
    const text = value;
    setValue('');
    Promise.resolve(onSend(text)).then((ok) => { if (ok === false) setValue((cur) => cur || text); });
  };
  return (
    <form className="sc-composer" onSubmit={(e) => { e.preventDefault(); submit(); }}>
      <textarea
        ref={ref} rows={1} value={value} maxLength={max} dir="auto" aria-label={COPY.placeholder}
        placeholder={placeholder || COPY.placeholder} disabled={disabled}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit(); } }}
      />
      {value.length >= 1800 && <span className="sc-count" aria-live="polite">{COPY.counter(value.length, max)}</span>}
      <button type="submit" className="sc-send" disabled={disabled || !value.trim()} aria-label={COPY.send}>
        <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path d="M3 11.5 21 3l-5.5 18-3.7-7.2L3 11.5Z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" transform="scale(-1 1) translate(-24 0)" /></svg>
      </button>
    </form>
  );
}

export function ContactCard({ onSave, onSkip, compact }) {
  const [v, setV] = useState({ name: '', phone: '', email: '' });
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const [expanded, setExpanded] = useState(!compact);
  if (!expanded) {
    // Live conversation: one quiet line, the fields are one tap away.
    return (
      <div className="sc-contact" data-compact="1">
        <p className="sc-contact-title">{COPY.contactTitle}</p>
        <div className="sc-contact-actions">
          <button type="button" className="sc-btn" onClick={() => setExpanded(true)}>{COPY.contactAdd}</button>
          <button type="button" className="sc-btn sc-btn-quiet" onClick={() => onSkip()}>{COPY.contactSkip}</button>
        </div>
      </div>
    );
  }
  const submit = async (e) => {
    e.preventDefault();
    const body = Object.fromEntries(Object.entries(v).filter(([, x]) => x.trim()));
    if (!Object.keys(body).length) { onSkip(); return; }
    setBusy(true);
    const r = await onSave(body);
    setBusy(false);
    if (r.ok) onSkip(true); else setErr(r.message || COPY.generalError);
  };
  return (
    <form className="sc-contact" onSubmit={submit}>
      <p className="sc-contact-title">{COPY.contactTitle}</p>
      <div className="sc-contact-grid">
        <input aria-label={COPY.contactName} placeholder={COPY.contactName} autoComplete="name"
          value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} />
        <input aria-label={COPY.contactPhone} placeholder={COPY.contactPhone} inputMode="tel" autoComplete="tel" dir="ltr"
          value={v.phone} onChange={(e) => setV({ ...v, phone: e.target.value })} />
        <input aria-label={COPY.contactEmail} placeholder={COPY.contactEmail} inputMode="email" autoComplete="email" dir="ltr"
          value={v.email} onChange={(e) => setV({ ...v, email: e.target.value })} />
      </div>
      {err && <p className="sc-error" role="alert">{err}</p>}
      <p className="sc-privacy">{COPY.privacyNotice} <a href="/privacy" target="_blank" rel="noopener noreferrer">{COPY.privacy}</a></p>
      <div className="sc-contact-actions">
        <button type="submit" className="sc-btn" disabled={busy}>{COPY.contactSave}</button>
        <button type="button" className="sc-btn sc-btn-quiet" onClick={() => onSkip()}>{COPY.contactSkip}</button>
      </div>
    </form>
  );
}

export function ClosedBar({ canReopen, onReopen, onNew, rated, onRate }) {
  return (
    <div className="sc-closed" role="status">
      <p>{COPY.closedBar}</p>
      {!rated ? (
        <div className="sc-rate" role="group" aria-label={COPY.rateTitle}>
          <span>{COPY.rateTitle}</span>
          {COPY.rateFaces.map((label, i) => (
            <button key={label} type="button" className="sc-face" aria-label={label} title={label} onClick={() => onRate(i + 1)}>
              {['😞', '🙁', '😐', '🙂', '😀'][i]}
            </button>
          ))}
        </div>
      ) : <p className="sc-meta">{COPY.rateThanks}</p>}
      <div className="sc-contact-actions">
        {canReopen
          ? <button type="button" className="sc-btn" onClick={onReopen}>{COPY.continueChat}</button>
          : <button type="button" className="sc-btn" onClick={onNew}>{COPY.newChat}</button>}
      </div>
    </div>
  );
}
