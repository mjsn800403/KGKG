'use client';

// The flattened "stack everything below this node" page. Every content node in
// the subtree is rendered as its own <section id="node-<id>">, so the car-tree
// sidebar (and the on-page contents list) can jump straight to any of them via
// #node-<id>. Manual cross-links (pages/<id>.html) are intercepted and turned
// into real in-app navigation, same as ContentRenderer.
import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { resolveHref } from '@/utils/api';
import { showModal } from '@/components/Modal';

// Collision-free separator for the section's relative path (matches CarNav).
const SEP = String.fromCharCode(1);

function isManualPageLink(href) {
  return /(^|\/)pages\/[^/]+\.html/i.test(href);
}

export default function StackedContent({ payload, brand, year, model }) {
  const router = useRouter();
  const items = payload?.items || [];

  async function handleClick(e) {
    const anchor = e.target.closest('a');
    if (!anchor) return;
    const href = anchor.getAttribute('href') || '';
    if (href.startsWith('#')) {                    // in-page contents link
      const el = document.getElementById(decodeURIComponent(href.slice(1)));
      if (el) {
        e.preventDefault();
        history.replaceState(null, '', href);
        el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
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

  // Client-rendered sections don't exist yet when the browser first tries to
  // honour the URL hash, so scroll to the target once mounted (and on later
  // hash changes driven by the sidebar).
  useEffect(() => {
    const scrollToHash = () => {
      const h = window.location.hash;
      if (!h) return;
      const el = document.getElementById(decodeURIComponent(h.slice(1)));
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };
    const t = setTimeout(scrollToHash, 80);
    window.addEventListener('hashchange', scrollToHash);
    return () => { clearTimeout(t); window.removeEventListener('hashchange', scrollToHash); };
  }, [payload]);

  if (!items.length) {
    return <div className="empty-state">محتوایی برای نمایش در این بخش وجود ندارد.</div>;
  }

  return (
    <div className="viewer glass stack">
      <div className="viewer-body content-renderer" onClick={handleClick}>
        {payload.truncated && (
          <div className="stack-note">
            این بخش بسیار بزرگ است؛ {items.length} مورد نخست نمایش داده شده است. برای دیدن باقی موارد از نوار کناری استفاده کنید.
          </div>
        )}
        {items.length > 1 && (
          <nav className="stack-toc" aria-label="فهرست این صفحه">
            <div className="stack-toc-head">در این صفحه</div>
            <ul>
              {items.map((it) => (
                <li key={it.id}><a href={`#node-${it.id}`}>{it.title}</a></li>
              ))}
            </ul>
          </nav>
        )}
        {items.map((it) => (
          <section key={it.id} id={`node-${it.id}`} data-rel={(it.segments || []).join(SEP)} className="stack-section">
            <h2 className="stack-section-title">{it.title}</h2>
            {it.segments && it.segments.length > 1 && (
              <div className="stack-section-crumb" dir="ltr">{it.segments.join('  /  ')}</div>
            )}
            <div className="content-wrapper" dangerouslySetInnerHTML={{ __html: it.content }} />
          </section>
        ))}
      </div>
    </div>
  );
}
