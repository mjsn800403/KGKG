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
function RenderReply({ text }) {
  if (!text) return null;

  const nodes = [];
  let lastIndex = 0;
  let key = 0;

  // [BUTTON](title="X", href="Y")
  const buttonRe = /\[BUTTON\]\(\s*title\s*=\s*"([^"]*)"\s*,\s*href\s*=\s*"([^"]*)"\s*\)/g;
  // generic [label](href)
  const linkRe = /\[([^\]]+)\]\(([^)\s]+)\)/g;

  // First normalize BUTTON tokens into generic [label](href) so one pass handles both.
  const normalized = text.replace(buttonRe, (_, title, href) => `[${title}](${href})`);

  let m;
  while ((m = linkRe.exec(normalized)) !== null) {
    if (m.index > lastIndex) {
      nodes.push(<span key={key++}>{normalized.slice(lastIndex, m.index)}</span>);
    }
    const label = m[1];
    const href = m[2];
    const internal = href.startsWith('/');
    if (internal) {
      nodes.push(
        <Link key={key++} href={href} className="chat-action-btn">
          {label} ←
        </Link>
      );
    } else {
      nodes.push(
        <a key={key++} href={href} target="_blank" rel="noopener noreferrer" className="chat-action-btn">
          {label} ↗
        </a>
      );
    }
    lastIndex = linkRe.lastIndex;
  }
  if (lastIndex < normalized.length) {
    nodes.push(<span key={key++}>{normalized.slice(lastIndex)}</span>);
  }

  return <div className="chat-reply-body">{nodes}</div>;
}

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

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, loading]);

  async function send() {
    const text = input.trim();
    if (!text || loading) return;
    setInput('');
    setMessages((m) => [...m, { role: 'user', content: text }]);
    setLoading(true);
    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text, sessionId, userId: userIdRef.current,
          brand, model, car: carName,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.error || 'خطا');
      if (data.sessionId) setSessionId(data.sessionId);
      setMessages((m) => [...m, {
        role: 'ai', content: data.reply || '...', query: text,
        sources: data.sources || [], confidence: data.confidence || null,
        grounded: data.grounded, mode: data.mode, topBlobs: data.topBlobs || [],
        degraded: data.degraded || false, rated: false,
      }]);
    } catch (err) {
      setMessages((m) => [
        ...m,
        { role: 'ai', content: `متأسفم، ارتباط با دستیار برقرار نشد. (${err.message})`, error: true },
      ]);
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
      <div className="chat-scroll" ref={scrollRef}>
        {messages.map((msg, i) => (
          <div key={i} className={`chat-msg ${msg.role === 'user' ? 'from-user' : 'from-ai'}`}>
            {msg.role === 'ai' && <div className="chat-avatar">AI</div>}
            <div className={`chat-bubble${msg.error ? ' error' : ''}`}>
              {msg.role === 'ai' ? <RenderReply text={msg.content} /> : msg.content}
              {msg.role === 'ai' && !msg.error && msg.query && (
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
            </div>
          </div>
        ))}
        {loading && (
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
