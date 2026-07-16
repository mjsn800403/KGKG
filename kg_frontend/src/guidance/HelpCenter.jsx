'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import Icon from '../components/Icon';
import {
  CATEGORIES, articlesFor, contextualArticles, tourById,
} from './content';

// On-demand, searchable help panel. Slide-over from the inline-start edge (RTL).
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
    const t = setTimeout(() => searchRef.current?.focus(), 60);
    return () => clearTimeout(t);
  }, [open, initialArticleId]); // eslint-disable-line react-hooks/exhaustive-deps

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

        {!selected && (
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

              {grouped.length === 0 && (
                <div className="guide-empty">نتیجه‌ای یافت نشد. عبارت دیگری را امتحان کنید.</div>
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

        {selected && (
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
            {selected.docRef && (
              <div className="guide-docref" title="مرجع مستندات فنی">مرجع: {selected.docRef}</div>
            )}
          </div>
        )}

        <footer className="guide-help-foot">
          <span>کلید میان‌بر: <kbd>؟</kbd></span>
        </footer>
      </aside>
    </div>
  );
}
