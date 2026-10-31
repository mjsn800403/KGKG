'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import Icon from '../components/Icon';
import {
  CATEGORIES, articlesFor, contextualArticles, tourById,
} from './content';
import { kbApi } from '../utils/api';

// On-demand, searchable help panel.
//
// Two sources, on purpose. The built-in articles in ./content.js explain how
// the product works and ship with the frontend. The knowledge base
// (/api/kb/, api/knowledge.py) holds answers written by the support side —
// including ones promoted straight out of a solved ticket — and changes
// without a deploy. Searching here searches both, and a search that finds
// nothing in the knowledge base is logged server-side: those misses are the
// list of articles that ought to exist next. Slide-over from the inline-start edge (RTL).
// Master/detail: a categorized, searchable list; selecting an article shows its
// body, optional step list, an optional "start the visual tour" button, and a
// subtle source-doc reference. Opens directly on the most relevant article for
// the current surface (context-sensitive help). Fully keyboard-accessible:
// focus moves in on open, Esc closes (handled by the provider), the search box
// is auto-focused, and everything is reachable by Tab.
export default function HelpCenter({
  open, audience, context, initialArticleId, onClose, onStartTour,
}) {
  const [q, setQ] = useState('');
  const [selId, setSelId] = useState(null);
  const [kbItems, setKbItems] = useState([]);
  const [kbSel, setKbSel] = useState(null);      // the loaded KB article
  const [kbBusy, setKbBusy] = useState(false);
  const [kbVoted, setKbVoted] = useState(false);
  const searchRef = useRef(null);
  const panelRef = useRef(null);

  const all = useMemo(() => articlesFor(audience), [audience]);
  const contextual = useMemo(
    () => contextualArticles(audience, context),
    [audience, context],
  );

  // Choose the landing article each time the panel opens.
  useEffect(() => {
    if (!open) return;
    setQ('');
    setSelId(initialArticleId || contextual[0]?.id || null);
    setKbSel(null);
    const t = setTimeout(() => searchRef.current?.focus(), 60);
    return () => clearTimeout(t);
  }, [open, initialArticleId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Knowledge-base results, debounced so typing does not log a search per
  // keystroke. Only for a signed-in seat: the endpoint is portal-authenticated,
  // and teamFetch treats a 401 as "the session is gone", so asking on behalf of
  // a visitor would be both pointless and rude. A failure is otherwise silent —
  // the built-in help must still work when the knowledge base does not answer.
  const kbAllowed = Boolean(audience && audience.role !== 'visitor' && !audience.isAdmin);
  useEffect(() => {
    if (!open || !kbAllowed) return undefined;
    const term = q.trim();
    const id = setTimeout(() => {
      setKbBusy(true);
      kbApi.list(term ? { q: term } : {})
        .then((d) => setKbItems(d.articles || []))
        .catch(() => setKbItems([]))
        .finally(() => setKbBusy(false));
    }, term ? 320 : 0);
    return () => clearTimeout(id);
  }, [open, q, kbAllowed]);

  const openKb = async (slug) => {
    setKbBusy(true);
    setKbVoted(false);
    try {
      const d = await kbApi.article(slug);
      setKbSel(d.article || null);
      setSelId(null);
    } catch {
      setKbSel(null);
    } finally { setKbBusy(false); }
  };

  const voteKb = async (helpful) => {
    if (!kbSel || kbVoted) return;
    setKbVoted(true);
    try { await kbApi.vote(kbSel.slug, helpful); } catch { /* a vote is not worth an error */ }
  };

  const filtered = useMemo(() => {
    const term = q.trim().toLowerCase();
    if (!term) return all;
    return all.filter((a) => {
      const hay = [a.title, a.summary, ...(a.keywords || []), ...(a.body || [])]
        .join(' ').toLowerCase();
      return hay.includes(term);
    });
  }, [q, all]);

  const grouped = useMemo(() => {
    const byCat = new Map();
    for (const a of filtered) {
      if (!byCat.has(a.category)) byCat.set(a.category, []);
      byCat.get(a.category).push(a);
    }
    return CATEGORIES
      .filter((c) => byCat.has(c.id))
      .map((c) => ({ ...c, items: byCat.get(c.id) }));
  }, [filtered]);

  const selected = selId ? all.find((a) => a.id === selId) : null;

  if (!open) return null;

  return (
    <div className="guide-help-scrim" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <aside
        className="guide-help-panel"
        role="dialog"
        aria-modal="true"
        aria-label="راهنمای سامانه"
        ref={panelRef}
      >
        <header className="guide-help-head">
          <div className="ghh-title">
            <Icon name="question" /> <span>مرکز راهنما</span>
          </div>
          <button type="button" className="guide-icon-btn" aria-label="بستن راهنما" onClick={onClose}>
            <Icon name="x" />
          </button>
        </header>

        {!selected && !kbSel && (
          <>
            <div className="guide-search">
              <Icon name="search" />
              <input
                ref={searchRef}
                type="text"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="جستجو در راهنما…"
                aria-label="جستجو در راهنما"
              />
              {q && (
                <button type="button" className="guide-search-clear" aria-label="پاک کردن" onClick={() => setQ('')}>
                  <Icon name="x" />
                </button>
              )}
            </div>

            <div className="guide-help-body">
              {!q && contextual.length > 0 && (
                <div className="guide-ctx">
                  <div className="guide-sec-label">مرتبط با این صفحه</div>
                  {contextual.slice(0, 3).map((a) => (
                    <button type="button" key={a.id} className="guide-ctx-card" onClick={() => setSelId(a.id)}>
                      <div className="gcc-title">{a.title}</div>
                      <div className="gcc-sum">{a.summary}</div>
                    </button>
                  ))}
                </div>
              )}

              {kbItems.length > 0 && (
                <div className="guide-cat">
                  <div className="guide-sec-label">
                    دانش‌نامهٔ پشتیبانی
                    {kbBusy && <span className="guide-kb-busy"> (در حال جستجو…)</span>}
                  </div>
                  <ul className="guide-art-list">
                    {kbItems.slice(0, 12).map((a) => (
                      <li key={a.slug}>
                        <button type="button" className="guide-art-row" onClick={() => openKb(a.slug)}>
                          <span className="gar-title">{a.title}</span>
                          {a.category && <span className="guide-kb-cat">{a.category}</span>}
                          <Icon name="back" className="gar-chev" />
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {grouped.length === 0 && kbItems.length === 0 && (
                <div className="guide-empty">
                  {q
                    ? 'نتیجه‌ای یافت نشد. عبارت دیگری را امتحان کنید.'
                    : 'برای این بخش راهنمای مستقیمی ثبت نشده است. از راهنمای تصویری یا دکمه‌های همین صفحه استفاده کنید.'}
                </div>
              )}

              {grouped.map((cat) => (
                <div className="guide-cat" key={cat.id}>
                  <div className="guide-sec-label">{cat.label}</div>
                  <ul className="guide-art-list">
                    {cat.items.map((a) => (
                      <li key={a.id}>
                        <button type="button" className="guide-art-row" onClick={() => setSelId(a.id)}>
                          <span className="gar-title">{a.title}</span>
                          <Icon name="back" className="gar-chev" />
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </>
        )}

        {kbSel && (
          <div className="guide-help-body guide-article">
            <button type="button" className="guide-back" onClick={() => setKbSel(null)}>
              <Icon name="chevron" /> همهٔ مقاله‌ها
            </button>
            <h3 className="guide-art-h">{kbSel.title}</h3>
            {kbSel.category && <p className="guide-art-sum">{kbSel.category}</p>}
            {/* Article bodies are plain text written by the support side; they
                are rendered as text, never as HTML. */}
            {String(kbSel.body || '').split(/\n{2,}/).map((para, i) => (
              <p className="guide-art-p" key={i}>{para}</p>
            ))}
            <div className="guide-kb-vote">
              {kbVoted ? (
                <span>ممنون از بازخوردتان 🙏</span>
              ) : (
                <>
                  <span>این مقاله کمک‌کننده بود؟</span>
                  <button type="button" className="fb-btn" aria-label="کمک‌کننده بود"
                    onClick={() => voteKb(true)}>👍</button>
                  <button type="button" className="fb-btn" aria-label="کمک‌کننده نبود"
                    onClick={() => voteKb(false)}>👎</button>
                </>
              )}
            </div>
          </div>
        )}

        {!kbSel && selected && (
          <div className="guide-help-body guide-article">
            <button type="button" className="guide-back" onClick={() => setSelId(null)}>
              <Icon name="chevron" /> همهٔ مقاله‌ها
            </button>
            <h3 className="guide-art-h">{selected.title}</h3>
            {selected.summary && <p className="guide-art-sum">{selected.summary}</p>}
            {(selected.body || []).map((p, i) => (
              <p className="guide-art-p" key={i}>{p}</p>
            ))}
            {selected.steps && selected.steps.length > 0 && (
              <ol className="guide-art-steps">
                {selected.steps.map((s, i) => <li key={i}>{s}</li>)}
              </ol>
            )}
            {selected.tourId && tourById(selected.tourId) && (
              <button
                type="button"
                className="btn btn-accent guide-tour-launch"
                onClick={() => { onClose(); onStartTour(selected.tourId); }}
              >
                <Icon name="sparkles" /> شروع راهنمای تصویری
              </button>
            )}
            {/* docRef points at our own internal docs tree; it stays in the
                data for maintenance but is never shown to the reader. */}
          </div>
        )}

        <footer className="guide-help-foot">
          <span>کلید میان‌بر: <kbd>؟</kbd></span>
        </footer>
      </aside>
    </div>
  );
}
