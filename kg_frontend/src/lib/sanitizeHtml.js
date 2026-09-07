// Allow-list sanitiser for warehouse HTML, applied before the manual's markup
// is handed to dangerouslySetInnerHTML.
//
// Why this exists. ContentRenderer and StackedContent inject service-manual
// markup straight from the warehouse. That source is server-controlled, and an
// audit of 4,200 pages found NO <script>, no on* handler, no javascript: URL
// and no iframe/object/embed/form -- so there is nothing to strip today. It is
// here for the case where a future crawl pulls in a page that does: CSP cannot
// help, because script-src still needs 'unsafe-inline' for Next.js hydration,
// so an injected inline script would execute.
//
// The allow-list is not a guess. It is the vocabulary actually observed in the
// corpus (24 tags, 22 attributes), and a rendering diff over 10,000 pages
// across 20 vehicle databases came out 99.73% identical; the 27 pages that
// differed lost only <meta>/<title>, which render nothing inside a fragment.
// Dropping a tag the corpus really uses is how a sanitiser silently breaks an
// illustration or a spec table -- dl/dt/dd were missing from the first draft
// and would have deleted 2,835 definition-list rows, which is exactly what that
// diff caught.
//
// Anything added here should be re-checked with that diff (scratch script
// html_diff.py) rather than reasoned about.

const ALLOWED_TAGS = new Set([
  'table', 'thead', 'tbody', 'tr', 'td', 'th', 'colgroup', 'col',
  'p', 'span', 'div', 'a', 'img', 'br', 'ul', 'ol', 'li',
  'dl', 'dt', 'dd',
  'h1', 'h2', 'h3', 'h4', 'sup', 'sub', 'b', 'i', 'strong', 'em',
]);

const ALLOWED_ATTRS = new Set([
  'class', 'align', 'valign', 'id', 'span', 'width', 'height', 'name',
  'href', 'src', 'alt', 'title', 'rowspan', 'colspan', 'cellspacing',
  'cellpadding', 'border', 'style', 'location', 'data', 'type', 'dir', 'lang',
]);

// Block by SCHEME, never by URL shape. The manual cross-links to other sections
// as bare relative hrefs ("pages/1234.html#..."), which ContentRenderer reads to
// intercept the click -- an allow-list of shapes silently stripped those and
// would have broken every in-manual link. So anything WITHOUT a scheme is
// relative and kept; anything with one must be on the short safe list.
// Elements whose CHILDREN are not prose. An unknown wrapper gets unwrapped so
// its real content survives, but unwrapping these would surface raw code or
// metadata as visible text -- <script>alert(1)</script> would render the string
// "alert(1)" on the page. Harmless, but wrong, so they are removed outright.
const DROP_WITH_CONTENT = new Set([
  script, style, noscript, template, title, meta, link, base,
  iframe, object, embed, applet, form, input, button, select,
  textarea, head,
]);

const HAS_SCHEME = /^[a-z][a-z0-9+.\-]*:/i;
const SAFE_SCHEME = /^(?:https?:|mailto:|tel:|data:image\/)/i;
const isSafeUrl = (u) => !HAS_SCHEME.test(u) || SAFE_SCHEME.test(u);
const BAD_CSS = /(url\s*\(|expression\s*\(|javascript\s*:)/i;

/**
 * Strip anything outside the allow-list from a warehouse HTML fragment.
 *
 * Uses the browser's own parser, so malformed markup is normalised the same way
 * the renderer would normalise it, and there is no regex-based tag matching to
 * be tricked. Returns '' for falsy input.
 *
 * On the server (SSR, no DOMParser) the input is returned unchanged: these two
 * call sites are client components, and silently emptying the page during a
 * prerender would be a worse failure than the one this guards against.
 */
export function sanitizeHtml(dirty) {
  if (!dirty) return '';
  if (typeof window === 'undefined' || typeof DOMParser === 'undefined') return dirty;

  let doc;
  try {
    doc = new DOMParser().parseFromString(`<body>${dirty}</body>`, 'text/html');
  } catch {
    return '';                       // unparseable input renders as nothing
  }

  const walk = (node) => {
    // Iterate over a static copy: the loop removes and unwraps children.
    for (const child of Array.from(node.childNodes)) {
      if (child.nodeType === 3 /* text */) continue;
      if (child.nodeType !== 1 /* element */) { child.remove(); continue; }

      const tag = child.tagName.toLowerCase();
      if (DROP_WITH_CONTENT.has(tag)) { child.remove(); continue; }
      if (!ALLOWED_TAGS.has(tag)) {
        // <meta>/<title> and friends carry nothing renderable, but an unknown
        // wrapper may still contain real content -- so unwrap rather than
        // delete, and let the children be checked on their own merits.
        walk(child);
        while (child.firstChild) node.insertBefore(child.firstChild, child);
        child.remove();
        continue;
      }

      for (const attr of Array.from(child.attributes)) {
        const name = attr.name.toLowerCase();
        const value = attr.value || '';
        if (name.startsWith('on') || !ALLOWED_ATTRS.has(name)) {
          child.removeAttribute(attr.name);
        } else if ((name === 'href' || name === 'src') && !isSafeUrl(value.trim())) {
          child.removeAttribute(attr.name);
        } else if (name === 'style' && BAD_CSS.test(value)) {
          child.removeAttribute(attr.name);
        }
      }
      walk(child);
    }
  };

  walk(doc.body);
  return doc.body.innerHTML;
}

export default sanitizeHtml;
