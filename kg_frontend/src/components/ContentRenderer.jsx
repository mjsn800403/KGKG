'use client';

import { useRouter } from 'next/navigation';
import { resolveHref } from '@/utils/api';

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

  function goToSegments(segments) {
    const encodedBrand = encodeURIComponent(brand);
    const encodedModel = encodeURIComponent(model);
    const encodedPath = segments.map(encodeURIComponent).join('/');
    router.push(`/${encodedBrand}/${year}/${encodedModel}/${encodedPath}`);
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
      const segments = await resolveHref(brand, year, model, filename);
      goToSegments(segments);
    } catch (err) {
      console.error('Could not resolve manual link:', href, err);
    }
  }

  return (
    <div className="content-renderer" onClick={handleClick}>
      <div
        className="content-wrapper"
        dangerouslySetInnerHTML={{ __html: content }}
      />
    </div>
  );
}
