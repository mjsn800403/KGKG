// Reading aids applied to warehouse manual HTML after it is injected.
//
// The source markup is a 2000s-era static site: bare <table>s wider than any
// column, illustrations with their licence line inside the cell, and
// cross-links written as pages/<id>.html. Rather than rewrite the HTML (the
// sanitiser's allow-list is diff-verified against the corpus), we decorate it
// in place once it is in the DOM:
//   • every table gets a scroll container, so a wide spec table scrolls
//     inside the page instead of being clipped by the RTL layout;
//   • the repeated licence line under each illustration becomes a caption;
//   • figures are marked so CSS can frame them like paper.
// Idempotent: a node already processed carries data-kg-enhanced.

const LICENCE_RE = /^courtesy of\s+©/i;

export function enhanceManualRoot(root) {
  if (!root) return;

  // The stacked view prints the page title above the content, and the source
  // HTML repeats it as its own first heading — drop the echo.
  root.querySelectorAll('.stack-section:not([data-kg-dedup])').forEach((section) => {
    section.setAttribute('data-kg-dedup', '1');
    const own = section.querySelector('.stack-section-title')?.textContent?.trim();
    const first = section.querySelector('.content-wrapper :is(h1, h2, h3)');
    if (own && first && first.textContent.trim() === own) first.remove();
  });

  root.querySelectorAll('table:not([data-kg-enhanced])').forEach((table) => {
    table.setAttribute('data-kg-enhanced', '1');
    // A table already inside a scroller (re-render, nested markup) is skipped.
    if (table.parentElement?.classList.contains('kg-tablewrap')) return;
    const wrap = document.createElement('div');
    wrap.className = 'kg-tablewrap';
    wrap.setAttribute('tabindex', '0');
    wrap.setAttribute('role', 'region');
    wrap.setAttribute('aria-label', 'جدول مستندات — در صورت نیاز افقی اسکرول کنید');
    table.parentNode.insertBefore(wrap, table);
    wrap.appendChild(table);
  });

  // "Courtesy of © TOYOTA, LICENSE AGREEMENT ..." repeats under every
  // illustration; keep it (it is the source's licence notice) but demote it.
  root.querySelectorAll('td:not([data-kg-cap]), p:not([data-kg-cap])').forEach((el) => {
    const text = (el.textContent || '').trim();
    if (!LICENCE_RE.test(text)) return;
    el.setAttribute('data-kg-cap', '1');
    el.classList.add('kg-licence');
  });

  root.querySelectorAll('img:not([data-kg-enhanced])').forEach((img) => {
    img.setAttribute('data-kg-enhanced', '1');
    img.setAttribute('loading', 'lazy');
    img.classList.add('kg-figure');
  });
}

/**
 * Group a flattened subtree's items by their parent section, so a contents
 * list of 200 entries reads as a handful of procedures instead of one long
 * run of repeated "Caution / Notice / Hint" lines.
 * items: [{ id, title, segments }]
 */
export function groupBySection(items = []) {
  const groups = [];
  let current = null;
  items.forEach((it) => {
    const segs = it.segments || [];
    const parent = segs.length > 1 ? segs[segs.length - 2] : '';
    if (!current || current.parent !== parent) {
      current = { parent, items: [] };
      groups.push(current);
    }
    current.items.push(it);
  });
  return groups;
}
