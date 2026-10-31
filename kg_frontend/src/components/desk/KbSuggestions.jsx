'use client';

import { useEffect, useRef, useState } from 'react';
import Icon from '../Icon';
import { kbApi } from '../../utils/api';

// Articles offered while a ticket is being written.
//
// "This answered it" is an explicit button, and it is the ONLY thing that
// records a deflection. Inferring one from "opened an article and did not
// file" would be inventing a success metric, which is exactly what the
// evaluation told us not to do.

export default function KbSuggestions({ query, carId, onResolved }) {
  const [articles, setArticles] = useState([]);
  const [openSlug, setOpenSlug] = useState(null);
  const [body, setBody] = useState('');
  // One id for this opened form. Every search and the deflection carry it, so
  // the metric counts compose sessions rather than debounced keystrokes.
  //
  // Minted in a ref rather than useMemo (which may not call an impure
  // initialiser during render) and rather than useId — React reuses a useId
  // for a component remounted at the same tree position, which would merge
  // two separate compose sessions into one opportunity.
  const composeIdRef = useRef('');
  const mintComposeId = () => {
    if (!composeIdRef.current) {
      composeIdRef.current = `c${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
    }
    return composeIdRef.current;
  };

  useEffect(() => {
    let cancelled = false;
    const q = (query || '').trim();
    // Everything, including clearing a short query's suggestions, happens in
    // the timer callback: a synchronous setState in the effect body would
    // re-render on every keystroke before the debounce has done its job.
    const id = setTimeout(() => {
      if (cancelled) return;
      if (q.length < 3) { setArticles([]); return; }
      kbApi.suggest(q, carId, mintComposeId())
        .then((d) => { if (!cancelled) setArticles((d.articles || []).slice(0, 3)); })
        .catch(() => { if (!cancelled) setArticles([]); });
    }, q.length < 3 ? 0 : 400);
    return () => { cancelled = true; clearTimeout(id); };
  }, [query, carId]);

  if (articles.length === 0) return null;

  // The article opens HERE rather than on another page. Sending somebody away
  // mid-sentence loses what they had typed, and the point is to answer them
  // before the ticket exists, not to redirect them.
  const toggle = async (slug) => {
    if (openSlug === slug) { setOpenSlug(null); setBody(''); return; }
    setOpenSlug(slug);
    setBody('');
    try {
      const d = await kbApi.article(slug);
      setBody(d.article?.body || '');
    } catch { setBody('متن این راهنما بارگذاری نشد.'); }
  };

  return (
    <div className="kbs">
      <p className="kbs-head">
        <Icon name="manual" size={14} /> شاید یکی از این راهنماها پاسخ شما باشد:
      </p>
      <ul className="kbs-list">
        {articles.map((a) => (
          <li key={a.slug} className="kbs-item">
            <div className="kbs-row">
              <button type="button" className="kbs-link" aria-expanded={openSlug === a.slug}
                onClick={() => toggle(a.slug)}>
                <Icon name="chevron" size={13} /> {a.title}
              </button>
              <button
                type="button"
                className="btn kbs-yes"
                onClick={async () => {
                  // A failed record must not cost the reader their answer.
                  try { await kbApi.deflect(a.slug, query, mintComposeId()); } catch { /* ignore */ }
                  onResolved?.(a);
                }}
              >
                همین پاسخ را می‌خواستم
              </button>
            </div>
            {openSlug === a.slug && (
              <div className="kbs-body">{body || 'در حال بارگذاری…'}</div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
