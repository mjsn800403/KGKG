'use client';
/* eslint-disable react-hooks/refs --
   False positive: the hook's refs (poll timer, Turnstile mount) are only read
   inside event handlers and effects, never while rendering. */

import { useEffect, useState } from 'react';
import { usePathname } from 'next/navigation';
import './support-chat.css';
import { COPY } from './copy.fa';
import useSupportChat from './useSupportChat';
import { Composer, ContactCard, ClosedBar, MessageList, Starters } from './Parts';

// The anonymous visitor's chat. It mounts only where a visitor may be talking to
// sales or support (the landing page and the purchase page for now) and only
// when the server says it is on. Not rendered on /admin or /invite at all.
const SHOW_ON = ['/', '/purchase'];
const MAX_LENGTH = 2000;

function Countdown({ seconds, children }) {
  const [left, setLeft] = useState(seconds);
  useEffect(() => {
    const iv = setInterval(() => setLeft((s) => Math.max(0, s - 1)), 1000);
    return () => clearInterval(iv);
  }, []);
  return left > 0 ? children(left) : null;
}

function Notice({ chat }) {
  const n = chat.notice;
  if (!n && chat.online) return null;
  if (!chat.online) return <div className="sc-bar" role="status">{COPY.offline}</div>;
  if (n.kind === 'rate_limited') {
    return <Countdown key={n.seq} seconds={n.seconds}>{(s) => <div className="sc-bar" role="status">{COPY.rateLimited(s)}</div>}</Countdown>;
  }
  if (n.kind === 'security') {
    return (
      <div className="sc-bar sc-bar-bad" role="alert">
        <p>{COPY.securityFailed}</p>
        <p className="sc-meta">{COPY.fallbackContacts}</p>
        <button type="button" className="sc-btn" onClick={chat.retrySecurity}>{COPY.securityRetry}</button>
      </div>
    );
  }
  if (n.kind === 'invalid') return <div className="sc-bar sc-bar-bad" role="alert">{n.text || COPY.generalError}</div>;
  if (n.kind === 'reopen_expired') return <div className="sc-bar" role="status">{COPY.reopenExpired}</div>;
  if (n.kind === 'unavailable') return <div className="sc-bar sc-bar-bad" role="alert">{COPY.fallbackContacts}</div>;
  return <div className="sc-bar sc-bar-bad" role="alert">{COPY.generalError}</div>;
}

function Availability({ chat }) {
  const { avail, state } = chat;
  let line = COPY.unknown;
  let hint = '';
  let tone = 'unknown';
  if (avail.known) {
    // Before a thread exists only the status endpoint knows; afterwards each
    // poll carries the server's current answer for this conversation.
    const mode = state.threadId ? state.mode : avail.mode;
    const live = mode === 'live' && !state.fellBack;
    tone = live ? 'live' : 'async';
    line = live ? COPY.live : COPY.async;
    if (!live) hint = state.fellBack ? COPY.fellBack : COPY.asyncHint;
    if (live && avail.replyTarget) hint = COPY.replyWithin(avail.replyTarget);
  }
  return (
    <div className="sc-avail" data-tone={tone}>
      <span className="sc-dot" aria-hidden="true" />
      <span>{line}</span>
      {hint && <span className="sc-meta"> · {hint}</span>}
    </div>
  );
}

function Panel({ chat }) {
  const { state } = chat;
  const [draft, setDraft] = useState(() => chat.getDraft());
  const { saveDraft } = chat;
  useEffect(() => { saveDraft(draft); }, [draft, saveDraft]);
  const [placeholder, setPlaceholder] = useState('');
  const [menu, setMenu] = useState(false);
  const [contactDone, setContactDone] = useState(false);
  const hasSent = state.messages.some((m) => m.kind === 'visitor' && m.delivery !== 'failed' && m.delivery !== 'sending');
  // Starters until the visitor has tried to say something; a message that failed
  // to send stays visible (with its retry) instead of vanishing behind them.
  const welcome = (state.phase === 'welcome' || state.phase === 'gone') && state.messages.length === 0;
  const closed = state.phase === 'closed';

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') chat.close(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [chat]);

  return (
    <section className="sc-panel" role="dialog" aria-label={COPY.title} id="sc-panel" dir="rtl">
      <header className="sc-head">
        <div>
          <strong>{COPY.title}</strong>
          <Availability chat={chat} />
        </div>
        <div className="sc-head-actions">
          <button type="button" className="sc-icon" aria-label={COPY.menu} aria-expanded={menu} onClick={() => setMenu(!menu)}>⋯</button>
          <button type="button" className="sc-icon" aria-label={COPY.close} onClick={chat.close}>✕</button>
        </div>
        {menu && (
          <div className="sc-menu" role="menu">
            <button type="button" role="menuitem" onClick={() => { chat.newChat(); setMenu(false); }}>{COPY.newChat}</button>
            <a role="menuitem" href="/privacy" target="_blank" rel="noopener noreferrer">{COPY.privacy}</a>
            <button type="button" role="menuitem" onClick={() => { chat.forget(); setMenu(false); }}>{COPY.forget}</button>
          </div>
        )}
      </header>

      <div className="sc-body">
        {state.phase === 'gone' && <div className="sc-bar" role="status">{COPY.gone}</div>}
        {welcome
          ? <Starters onPick={(s) => { chat.setIntent(s.intent); setPlaceholder(s.placeholder); }} />
          : <MessageList messages={state.messages} staffSeenAt={state.staffSeenAt} onRetry={chat.retry} />}
        {hasSent && !contactDone && !closed && (
          <ContactCard compact={state.mode === 'live'} onSave={chat.saveContact} onSkip={() => setContactDone(true)} />
        )}
        {state.fellBack && <div className="sc-system"><span>{COPY.fellBack}</span></div>}
        {closed && <ClosedBar canReopen={state.canReopen} onReopen={chat.reopen} onNew={chat.newChat} rated={state.rated} onRate={chat.rate} />}
      </div>

      <Notice chat={chat} />
      <div ref={chat.setMount} className="sc-turnstile" />
      {!closed && (
        <Composer
          onSend={(text) => chat.send(text)} value={draft} setValue={setDraft} max={MAX_LENGTH}
          disabled={!state.threadId && state.messages.some((m) => m.delivery === 'sending')}
          placeholder={placeholder}
        />
      )}
    </section>
  );
}

export default function SupportChat() {
  const pathname = usePathname() || '/';
  const chat = useSupportChat();
  const [label, setLabel] = useState(true);
  useEffect(() => { const t = setTimeout(() => setLabel(false), 6000); return () => clearTimeout(t); }, []);
  const show = SHOW_ON.includes(pathname.replace(/\/+$/, '') || '/');
  if (!show || chat.avail.enabled === false) return null;
  const { state } = chat;
  return (
    <div className="sc-root" data-open={state.panelOpen ? '1' : '0'} data-page={pathname.replace(/\/+$/, '') || '/'}>
      {state.panelOpen && <Panel chat={chat} />}
      {!state.panelOpen && (
        <button type="button" className="sc-launcher" aria-expanded="false" aria-controls="sc-panel" onClick={chat.open}>
          <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true"><path d="M4 5h16v11H9l-5 4V5Z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" /></svg>
          {label && <span className="sc-launcher-label">{COPY.launcher}</span>}
          {state.unread > 0 && <span className="sc-badge" aria-label={`${state.unread}`}>{state.unread.toLocaleString('fa-IR')}</span>}
        </button>
      )}
    </div>
  );
}
