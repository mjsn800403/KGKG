'use client';

import { useRouter } from 'next/navigation';
import { resolveHref } from '@/utils/api';
import { showModal } from '@/components/Modal';
import { sanitizeHtml } from '@/lib/sanitizeHtml';

// The manual's HTML content cross-links to other sections using the
// original static site's flat "pages/<id>.html" filenames (optionally with
// a "#<encoded title chain>" fragment), which don't correspond to anything
// in our app's URL structure. We intercept clicks on these links and
// translate them into a real navigation instead of letting the browser
// follow them (which 404s).
function isManualPageLink(href) {
  return /(^|\/)pages\/[^/]+\.html/i.test(href);
}

export default function ContentRenderer({ content, brand, year, model }) {
  const router = useRouter();

  if (!content) return null;

  function goToSegments(targetBrand, targetYear, targetModel, segments) {
    const encodedBrand = encodeURIComponent(targetBrand);
    const encodedModel = encodeURIComponent(targetModel);
    const encodedPath = segments.map(encodeURIComponent).join('/');
    router.push(`/${encodedBrand}/${targetYear}/${encodedModel}/${encodedPath}`);
  }

  async function handleClick(e) {
    const anchor = e.target.closest('a');
    if (!anchor) return;

    const href = anchor.getAttribute('href') || '';
    if (!isManualPageLink(href)) return;

    e.preventDefault();

    // Any "#..." fragment here is an in-page anchor into the original
    // site's combined "single page" document (used for scrolling), not a
    // path through our node tree - we always resolve by the target file's
    // name and ignore the fragment, since we render one node at a time.
    const filename = href.split('#')[0].split('/').filter(Boolean).pop();
    try {
      const target = await resolveHref(brand, year, model, filename);
      goToSegments(target.brand, target.year, target.model, target.segments);
    } catch (err) {
      if (err.notFound) {
        // No node matches this page - it's an orphan page that the crawler
        // never registered (e.g. an alternate-variant "Other Variant" page
        // reachable only via this cross-link). Its HTML still exists in the
        // current car's source folder, so render it through the raw-page
        // route instead of failing.
        router.push(`/${encodeURIComponent(brand)}/${year}/${encodeURIComponent(model)}/page/${encodeURIComponent(filename)}`);
        return;
      }
      console.error('Could not resolve manual link:', href, err);
      showModal(
        'بارگذاری محتوا ناموفق بود',
        'در دریافت این صفحه از سامانه خطایی رخ داد. لطفاً دوباره تلاش کنید.',
        '!'
      );
    }
  }

  return (
    <div className="viewer glass">
      <div className="viewer-body content-renderer" onClick={handleClick}>
        <div
          className="content-wrapper"
          dangerouslySetInnerHTML={{ __html: sanitizeHtml(content) }}
        />
      </div>
    </div>
  );
}
