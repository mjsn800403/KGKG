'use client';

// The flattened "stack everything below this node" page. Every content node in
// the subtree is rendered as its own <section id="node-<id>">, so the car-tree
// sidebar (and the on-page contents list) can jump straight to any of them via
// #node-<id>. Manual cross-links (pages/<id>.html) are intercepted and turned
// into real in-app navigation, same as ContentRenderer.
//
// A big section can hold 200 pages (~90,000px of scroll), so sections render a
// batch at a time and the contents list is grouped by parent procedure. A deep
// link (#node-<id>) forces enough batches to include its target.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { resolveHref } from '@/utils/api';
import { showModal } from '@/components/Modal';
import Icon from '@/components/Icon';
import { sanitizeHtml } from '@/lib/sanitizeHtml';
import { enhanceManualRoot, groupBySection } from '@/lib/manualContent';

// Collision-free separator for the section's relative path (matches CarNav).
const SEP = String.fromCharCode(1);
// Sections rendered per batch: enough to fill a few screens, small enough that
// the page stays responsive on a workshop tablet.
const BATCH = 12;

function isManualPageLink(href) {
  return /(^|\/)pages\/[^/]+\.html/i.test(href);
}

export default function StackedContent({ payload, brand, year, model }) {
  const router = useRouter();
  const items = useMemo(() => payload?.items || [], [payload]);
  const bodyRef = useRef(null);
  const [shown, setShown] = useState(() => Math.min(items.length, BATCH));

  const groups = useMemo(() => groupBySection(items), [items]);
  const rest = items.length - shown;

  async function handleClick(e) {
    const anchor = e.target.closest('a');
    if (!anchor) return;
    const href = anchor.getAttribute('href') || '';
    if (href.startsWith('#')) {                    // in-page contents link
      const id = decodeURIComponent(href.slice(1));
      const index = items.findIndex((it) => `node-${it.id}` === id);
      e.preventDefault();
      history.replaceState(null, '', href);
      if (index >= shown) { setShown(index + 1); return; }   // the hash effect scrolls it
      document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      return;
    }
    if (!isManualPageLink(href)) return;
    e.preventDefault();
    const filename = href.split('#')[0].split('/').filter(Boolean).pop();
    try {
      const t = await resolveHref(brand, year, model, filename);
      const encodedPath = t.segments.map(encodeURIComponent).join('/');
      router.push(`/${encodeURIComponent(t.brand)}/${t.year}/${encodeURIComponent(t.model)}/${encodedPath}`);
    } catch (err) {
      if (err.notFound) {
        router.push(`/${encodeURIComponent(brand)}/${year}/${encodeURIComponent(model)}/page/${encodeURIComponent(filename)}`);
        return;
      }
      showModal('بارگذاری محتوا ناموفق بود', 'در دریافت این صفحه از سامانه خطایی رخ داد. لطفاً دوباره تلاش کنید.', '!');
    }
  }

  // A hash may point at a section outside the rendered batch, so grow the
  // batch first and scroll once the section exists.
  const syncToHash = useCallback(() => {
    const h = window.location.hash;
    if (!h) return;
    const id = decodeURIComponent(h.slice(1));
    const index = items.findIndex((it) => `node-${it.id}` === id);
    if (index >= 0) setShown((n) => (index >= n ? index + 1 : n));
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, [items]);

  useEffect(() => {
    const t = setTimeout(syncToHash, 80);
    window.addEventListener('hashchange', syncToHash);
    return () => { clearTimeout(t); window.removeEventListener('hashchange', syncToHash); };
  }, [syncToHash, shown]);

  // Decorate whatever is currently rendered (tables, figures, captions).
  useEffect(() => { enhanceManualRoot(bodyRef.current); }, [payload, shown]);

  if (!items.length) {
    return <div className="empty-state">محتوایی برای نمایش در این بخش وجود ندارد.</div>;
  }

  return (
    <div className="viewer glass stack">
      <div className="viewer-body content-renderer" onClick={handleClick} ref={bodyRef}>
        {payload.truncated && (
          <div className="stack-note">
            این بخش بسیار بزرگ است؛ {items.length.toLocaleString('fa-IR')} مورد نخست نمایش داده شده است. برای دیدن باقی موارد از نوار کناری استفاده کنید.
          </div>
        )}

        {items.length > 1 && (
          <nav className="stack-toc" id="stack-toc" aria-label="فهرست این صفحه">
            <details open={items.length <= 25}>
              <summary>
                <span className="stack-toc-head">در این صفحه</span>
                <span className="stack-toc-count">{items.length.toLocaleString('fa-IR')} صفحه</span>
                <span className="stack-toc-x" aria-hidden="true" />
              </summary>
              <div className="stack-toc-body">
                {groups.map((g, gi) => (
                  <div className="stack-toc-group" key={`${g.parent}-${gi}`}>
                    {g.parent && <h3 dir="ltr">{g.parent}</h3>}
                    <ul>
                      {g.items.map((it) => (
                        <li key={it.id}><a href={`#node-${it.id}`} dir="ltr">{it.title}</a></li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            </details>
          </nav>
        )}

        {items.slice(0, shown).map((it) => (
          <section key={it.id} id={`node-${it.id}`} data-rel={(it.segments || []).join(SEP)} className="stack-section">
            <div className="stack-section-head">
              <h2 className="stack-section-title" dir="ltr">{it.title}</h2>
              <a className="stack-section-up" href="#stack-toc" aria-label="بازگشت به فهرست این صفحه">
                <Icon name="arrow" /><span>فهرست</span>
              </a>
            </div>
            {it.segments && it.segments.length > 1 && (
              <div className="stack-section-crumb" dir="ltr">{it.segments.slice(0, -1).join(' / ')}</div>
            )}
            <div className="content-wrapper" dangerouslySetInnerHTML={{ __html: sanitizeHtml(it.content) }} />
          </section>
        ))}

        {rest > 0 && (
          <div className="stack-more">
            <button type="button" className="btn btn-accent" onClick={() => setShown((n) => Math.min(items.length, n + BATCH))}>
              نمایش {Math.min(BATCH, rest).toLocaleString('fa-IR')} صفحهٔ بعدی
            </button>
            <button type="button" className="btn" onClick={() => setShown(items.length)}>
              نمایش همهٔ {items.length.toLocaleString('fa-IR')} صفحه
            </button>
            <span>{rest.toLocaleString('fa-IR')} صفحهٔ دیگر در این بخش</span>
          </div>
        )}
      </div>
    </div>
  );
}
