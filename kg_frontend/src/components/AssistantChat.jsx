'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import EvidencePanel from './EvidencePanel';
import FeedbackBar from './FeedbackBar';
import { rateAnswer } from '../utils/api';

// Renders bot text and turns markdown links into clickable elements.
// Supports both [label](href) and the instruction's [BUTTON](title="..", href="..")
// form. Internal links (starting with "/") open in-app via next/link; external
// ones open in a new tab.
// Source links built before the in-title-slash fix carry "%2F" inside a path
// segment; the site encodes that "/" as U+2044 (see NAV_SLASH), so rewrite it
// or the link opens an error page.
// The diagnostic index also predates the TIS rebuild, whose manual root is
// "Repair and Diagnosis" (the old "... (Single Page)" root no longer exists).
export function fixHref(href) {
  // Parts-catalog routes keep a literal %2F for in-title slashes: leave them be.
  if (/\/parts(\/|\?|$)/.test(href)) return href;
  return href
    .replace(/%2F/gi, '%E2%81%84')
    .replace(/\/Repair%20and%20Diagnosis%20(?:%28|\()Single%20Page(?:%29|\))\//i, '/Repair%20and%20Diagnosis/');
}

// Minimal markdown for the LLM's prose: **bold** and "#" headings. Everything
// else stays plain text (never HTML), so nothing in a reply can inject markup.
function renderInline(str, keyBase) {
  const out = [];
  const lines = str.split('\n');
  lines.forEach((line, li) => {
    const heading = line.replace(/^\s*#{1,6}\s+/, '');
    const isHeading = heading !== line;
    const parts = heading.split(/\*\*([^*\n]+?)\*\*/g);
    const inner = parts.map((part, i) => (i % 2
      ? <strong key={i}>{part}</strong>
      : part.replace(/\*\*/g, '')));
    out.push(isHeading
      ? <strong key={`${keyBase}-${li}`} className="chat-heading">{inner}</strong>
      : <span key={`${keyBase}-${li}`}>{inner}</span>);
    if (li < lines.length - 1) out.push('\n');
  });
  return out;
}

function RenderReply({ text, streaming = false }) {
  if (!text) return null;
  // Mid-stream text is unvalidated: show the prose only (no link buttons, no
  // half-written tokens). The gated final reply replaces it on completion.
  if (streaming) {
    const prose = text
      .replace(/\[BUTTON\]\([^)\n]*\)?/g, '')
      .replace(/\[BUTTON\][^\n]*$/, '')
      .replace(/\[([^\]]+)\]\([^)\s]*\)?/g, '$1');
    return <div className="chat-reply-body">{renderInline(prose, 's')}</div>;
  }

  const nodes = [];
  let lastIndex = 0;
  let key = 0;

  // [BUTTON](title="X", href="Y")
  const buttonRe = /\[BUTTON\]\(\s*title\s*=\s*"([^"]*)"\s*,\s*href\s*=\s*"?([^"\s)]*)"?\s*\)/g;
  // generic [label](href)
  const linkRe = /\[([^\]]+)\]\(([^)\s]+)\)/g;

  // First normalize BUTTON tokens into generic [label](href) so one pass handles both.
  const normalized = text
    .replace(buttonRe, (_, title, href) => `[${title}](${href})`)
    .replace(/\[BUTTON\]\([^)\n]*\)?/g, '');

  let m;
  while ((m = linkRe.exec(normalized)) !== null) {
    if (m.index > lastIndex) {
      nodes.push(<span key={key++}>{renderInline(normalized.slice(lastIndex, m.index), key)}</span>);
    }
    const label = m[1].replace(/\*\*/g, '');
    const href = fixHref(m[2]);
    // The assistant only ever cites in-app links (server-side faithfulness gate
    // keeps the retrieved ones). So render ONLY internal "/..." hrefs as links;
    // anything else is a hallucinated/injected URL — show its label as plain
    // text, never an anchor. This also neutralises javascript:/data:/phishing.
    if (href.startsWith('/')) {
      nodes.push(
        <Link key={key++} href={href} className="chat-action-btn">
          {label} ←
        </Link>
      );
    } else {
      nodes.push(<span key={key++}>{label}</span>);
    }
    lastIndex = linkRe.lastIndex;
  }
  if (lastIndex < normalized.length) {
    nodes.push(<span key={key++}>{renderInline(normalized.slice(lastIndex), key)}</span>);
  }

  return <div className="chat-reply-body">{nodes}</div>;
}

// Example questions shown under the greeting, covering the assistant's main
// jobs: fault codes, specifications, capacities and repair procedures.
const STARTERS = [
  'کد خطای P0301 یعنی چه و چطور عیب‌یابی می‌شود؟',
  'گشتاور بستن شمع موتور چقدر است؟',
  'ظرفیت روغن موتور با فیلتر چقدر است؟',
  'مراحل تعویض لنت ترمز جلو چیست؟',
];

export default function AssistantChat({ brand, year, model, car } = {}) {
  // The car this assistant is scoped to (the page passes it; the backend uses it
  // to pick the right per-car diagnostic index and to rank manual hits).
  const carName = car || model;
  const greeting = carName
    ? `سلام 👋 من دستیار هوشمند ${carName}${year ? ' ' + year : ''} هستم. ` +
      'می‌تونی مشکل ماشین رو فارسی بگی (مثلاً «موتور لرزش داره و چراغ چک روشنه») ' +
      'یا کد خطا (DTC) رو وارد کنی (مثلاً P0301) تا عیب رو برات تشخیص بدم و مرحله‌به‌مرحله راهنماییت کنم. ' +
      'برای کارهای تعمیری هم بپرس (مثلاً «روغن ترمز رو چطور عوض کنم»).'
    : 'سلام 👋 من دستیار هوشمند سرویس خودرو هستم. بگو می‌خوای چه کاری روی ماشینت انجام بدی — مثلاً «می‌خوام روغن ترمز رو عوض کنم» — تا راهنمای دقیقش رو برات پیدا کنم.';
  const [messages, setMessages] = useState([{ role: 'ai', content: greeting }]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const userIdRef = useRef(null);
  const scrollRef = useRef(null);
  const hydratedRef = useRef(false);

  // Per-conversation storage key: scoped to the car so each vehicle keeps its
  // own thread, and a global one for the car-less assistant.
  const storageKey = `kg_chat_v1_${brand || ''}_${carName || ''}_${year || ''}`
    .replace(/\s+/g, '_');

  // Stable per-browser user id, persisted so the conversation context survives reloads.
  useEffect(() => {
    let uid = null;
    try {
      uid = localStorage.getItem('kg_assistant_uid');
      if (!uid) {
        uid = `web-${Math.random().toString(36).slice(2)}-${Date.now()}`;
        localStorage.setItem('kg_assistant_uid', uid);
      }
    } catch {
      uid = `web-${Date.now()}`;
    }
    userIdRef.current = uid;
  }, []);

  // Restore the saved conversation after mount (kept out of the initial state to
  // avoid an SSR/CSR hydration mismatch). The chat then survives a page reload
  // instead of resetting to the greeting.
  useEffect(() => {
    try {
      const raw = localStorage.getItem(storageKey);
      if (raw) {
        const saved = JSON.parse(raw);
        if (Array.isArray(saved?.messages) && saved.messages.length) {
          setMessages(saved.messages);
        }
        if (saved?.sessionId) setSessionId(saved.sessionId);
      }
    } catch { /* corrupt/unavailable storage — start fresh */ }
    hydratedRef.current = true;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storageKey]);

  // Persist the conversation (only after the restore has run, so we never
  // overwrite a saved thread with the empty greeting on first paint).
  useEffect(() => {
    if (!hydratedRef.current) return;
    try {
      const trimmed = messages.filter((m) => !m.streaming).slice(-60);   // cap growth
      localStorage.setItem(storageKey, JSON.stringify({ messages: trimmed, sessionId }));
    } catch { /* storage full/unavailable — non-fatal */ }
  }, [messages, sessionId, storageKey]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, loading]);

  // overrideText: a suggestion chip's underlying query; displayText: the chip
  // label shown as the user's bubble (falls back to the sent text).
  async function send(overrideText, displayText) {
    const text = (overrideText ?? input).trim();
    if (!text || loading) return;
    setInput('');
    // Multi-turn context: recent thread + the last answer's source titles let
    // the server resolve follow-ups («و گشتاورش چقدره؟») into a real query.
    const historyPayload = messages
      .filter((m) => !m.error && m.content)
      .slice(-6)
      .map((m) => ({ role: m.role === 'user' ? 'user' : 'ai',
                     content: String(m.content).slice(0, 400) }));
    const lastAi = [...messages].reverse()
      .find((m) => m.role === 'ai' && m.sources?.length);
    const prevSources = (lastAi?.sources || []).slice(0, 3)
      .map((s) => s.title_en || s.title).filter(Boolean);
    setMessages((m) => [...m, { role: 'user', content: (displayText ?? text) }]);
    setLoading(true);
    // Replace the in-flight streaming bubble (if any) or append a new one.
    const putAi = (msg) => setMessages((m) => (
      m.length && m[m.length - 1].streaming ? [...m.slice(0, -1), msg] : [...m, msg]));
    const finalMsg = (data) => ({
      role: 'ai', content: data.reply || '...', query: text,
      sources: data.sources || [], confidence: data.confidence || null,
      grounded: data.grounded, mode: data.mode, topBlobs: data.topBlobs || [],
      degraded: data.degraded || false, rated: false,
      suggestions: data.suggestions || [],
    });
    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text, sessionId, userId: userIdRef.current,
          brand, model, car: carName,
          history: historyPayload, prevSources, stream: true,
        }),
      });
      const ctype = res.headers.get('content-type') || '';
      if (res.ok && ctype.includes('ndjson') && res.body) {
        const reader = res.body.getReader();
        const dec = new TextDecoder();
        let buf = '';
        let shown = '';
        let final = null;
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += dec.decode(value, { stream: true });
          let nl;
          while ((nl = buf.indexOf('\n')) >= 0) {
            const line = buf.slice(0, nl);
            buf = buf.slice(nl + 1);
            if (!line.trim()) continue;
            const ev = JSON.parse(line);
            if (ev.t === 'delta') {
              shown += ev.d;
              putAi({ role: 'ai', content: shown, streaming: true });
            } else if (ev.t === 'done') {
              final = ev;
            } else if (ev.t === 'error') {
              throw new Error(ev.error || 'خطا');
            }
          }
        }
        if (!final) throw new Error('پاسخ ناقص دریافت شد');
        if (final.sessionId) setSessionId(final.sessionId);
        putAi(finalMsg(final));
      } else {
        const data = await res.json();
        if (!res.ok) throw new Error(data?.error || 'خطا');
        if (data.sessionId) setSessionId(data.sessionId);
        putAi(finalMsg(data));
      }
    } catch (err) {
      putAi({ role: 'ai', content: `متأسفم، ارتباط با دستیار برقرار نشد. (${err.message})`, error: true });
    } finally {
      setLoading(false);
    }
  }

  function onKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  function resetChat() {
    setMessages([{ role: 'ai', content: greeting }]);
    setSessionId(null);
    setInput('');
    try { localStorage.removeItem(storageKey); } catch { /* ignore */ }
  }

  function rate(msg, idx, { verdict, reason, comment }) {
    rateAnswer({
      query: msg.query, verdict, reason, comment, mode: msg.mode,
      topBlobs: msg.topBlobs, blobId: msg.topBlobs?.[0] ?? null,
      brand, model, car: carName,
    });
    setMessages((m) => m.map((x, i) => (i === idx ? { ...x, rated: true } : x)));
  }

  return (
    <div className="chat-wrap glass">
      <div className="chat-topbar">
        <span className="chat-topbar-title">دستیار هوشمند</span>
        <button
          type="button"
          className="chat-reset"
          onClick={resetChat}
          disabled={loading || messages.length <= 1}
          title="شروع گفتگوی تازه"
        >
          گفتگوی جدید
        </button>
      </div>
      <div className="chat-scroll" ref={scrollRef}>
        {messages.map((msg, i) => (
          <div key={i} className={`chat-msg ${msg.role === 'user' ? 'from-user' : 'from-ai'}`}>
            {msg.role === 'ai' && <div className="chat-avatar">AI</div>}
            <div className={`chat-bubble${msg.error ? ' error' : ''}`}>
              {msg.role === 'ai' ? <RenderReply text={msg.content} streaming={!!msg.streaming} /> : msg.content}
              {msg.role === 'ai' && !msg.error && msg.query && msg.mode !== 'clarify' && (
                <>
                  <EvidencePanel
                    sources={msg.sources}
                    confidence={msg.confidence}
                    grounded={msg.grounded}
                    mode={msg.mode}
                    degraded={msg.degraded}
                  />
                  {!msg.rated
                    ? <FeedbackBar onRate={(v) => rate(msg, i, v)} />
                    : <div className="fb-bar fb-done">ممنون از بازخوردت 🙏</div>}
                </>
              )}
              {i === 0 && messages.length === 1 && !loading && carName && (
                <div className="chat-starters" aria-label="نمونه پرسش‌ها">
                  <span className="chat-starters-label">برای شروع می‌توانید بپرسید:</span>
                  {STARTERS.map((q) => (
                    <button key={q} type="button" className="chat-suggestion-chip" onClick={() => send(q)}>{q}</button>
                  ))}
                </div>
              )}
              {msg.role === 'ai' && !msg.error && i === messages.length - 1 &&
                !loading && (msg.suggestions?.length > 0) && (
                <div className="chat-suggestions">
                  {msg.suggestions.map((s, k) => (
                    <button
                      key={k}
                      type="button"
                      className="chat-suggestion-chip"
                      onClick={() => send(s.query, s.label)}
                    >
                      {s.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}
        {loading && !messages[messages.length - 1]?.streaming && (
          <div className="chat-msg from-ai">
            <div className="chat-avatar">AI</div>
            <div className="chat-bubble">
              <span className="chat-typing"><i></i><i></i><i></i></span>
            </div>
          </div>
        )}
      </div>

      <div className="chat-inputbar">
        <textarea
          className="chat-input"
          aria-label="پیام به دستیار هوشمند"
          rows={1}
          placeholder="سؤالت رو بنویس… (فارسی یا English)"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
        />
        <button className="chat-send" onClick={send} disabled={loading || !input.trim()}>
          ارسال
        </button>
      </div>
    </div>
  );
}
