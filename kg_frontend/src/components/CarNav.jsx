'use client';

// Lazy-expanding navigator for one car's whole content tree (the "sidebar"),
// styled like the table of contents of a book: chapters (top level) hold
// sub-sections, the trail down to where you are is highlighted, and — on a
// flattened (stacked) page — the section currently under your reading position
// is auto-expanded, highlighted and kept in view, so you can always locate
// yourself without scrolling back to the top.
//
// The manual tree is huge (tens of thousands of nodes per car), so children are
// fetched on demand — never the whole tree at once — via the nav-mode children
// endpoint (structure only, no page bodies). Every node links to its own page;
// the page itself decides whether to stack the subtree (small enough) or show a
// drill-down index (too big). Folders also expand in place via the caret.
import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { fetchNav, buildNodeHref, urlToSeg } from '@/utils/api';

// A separator that cannot appear inside a node title, so a joined segment list
// is a collision-free map key. Segments are always normalised to real "/" (the
// nav titles carry the U+2044 fraction slash for literal slashes) so tree keys
// line up with the URL path and with the sections' data-rel attribute.
const SEP = String.fromCharCode(1);
const keyOf = (segs) => segs.join(SEP);
const samePath = (a, b) => a.length === b.length && a.every((s, i) => s === b[i]);
// True when `segs` is a strict ancestor of `path` (i.e. on the trail to it).
const isAncestor = (segs, path) =>
  segs.length < path.length && segs.every((s, i) => s === path[i]);

export default function CarNav({ brand, year, model, currentPath = [] }) {
  const router = useRouter();
  const [byKey, setByKey] = useState({});        // key -> { loading, children }
  const [expanded, setExpanded] = useState(() => new Set());
  // Keys already fetched or in flight. A ref, not state: the state updater runs
  // asynchronously, so it can't be used to decide "should I fetch?" without
  // racing (which previously left every level stuck on "loading…").
  const requested = useRef(new Set());
  // The active row's DOM node, so we can scroll it into view when the path
  // changes (deep pages otherwise leave you lost in a long tree).
  const activeRef = useRef(null);
  // Scroll-spy: the id of the stacked section currently at the top of the
  // viewport, plus the full segment path to it — so the matching leaf lights up
  // and its ancestor folders auto-open as you scroll a flattened page.
  const [activeSection, setActiveSection] = useState(null);
  const [spyPath, setSpyPath] = useState([]);
  const spyKey = keyOf(spyPath);

  const load = useCallback(async (segs) => {
    const key = keyOf(segs);
    if (requested.current.has(key)) return;
    requested.current.add(key);
    setByKey((m) => ({ ...m, [key]: { loading: true, children: null } }));
    try {
      const children = await fetchNav(brand, year, model, segs);
      setByKey((m) => ({ ...m, [key]: { loading: false, children: children || [] } }));
    } catch {
      requested.current.delete(key);   // allow a retry on next expand
      setByKey((m) => ({ ...m, [key]: { loading: false, children: [] } }));
    }
  }, [brand, year, model]);

  // On mount / when the current path changes: load the roots, every ancestor
  // level along the current path, AND the current node's own children — so the
  // page you're on opens to reveal its sub-sections like a book chapter — then
  // reveal the whole trail.
  const currentKey = keyOf(currentPath);
  useEffect(() => {
    load([]);
    for (let i = 0; i <= currentPath.length; i++) load(currentPath.slice(0, i));
    setExpanded((prev) => {
      const s = new Set(prev);
      for (let i = 0; i <= currentPath.length; i++) s.add(keyOf(currentPath.slice(0, i)));
      return s;
    });
  }, [load, currentKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // Bring the active row into view once, when the route changes (not on every
  // lazy child load — that would keep yanking the sidebar back to the root).
  useEffect(() => {
    const t = setTimeout(() => {
      activeRef.current?.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }, 300);
    return () => clearTimeout(t);
  }, [currentKey]);

  // Scroll-spy over the stacked page's sections. A rect check on scroll (rather
  // than an IntersectionObserver) is used deliberately: sections here can be
  // thousands of px tall and fully span any thin observer band, which IO reports
  // inconsistently. The "current" section is the last one whose top has crossed
  // a reading line near the top of the viewport.
  useEffect(() => {
    if (typeof document === 'undefined') return;
    const LINE = 140;
    let raf = 0;
    const pick = () => {
      raf = 0;
      const secs = document.querySelectorAll('.stack-section[id^="node-"]');
      if (!secs.length) { setActiveSection(null); setSpyPath([]); return; }
      let current = null;
      for (const s of secs) {
        if (s.getBoundingClientRect().top <= LINE) current = s;
        else break;                       // sections are in document order
      }
      if (!current) current = secs[0];
      const id = current.id.slice(5);
      setActiveSection((prev) => (prev === id ? prev : id));
      const rel = current.dataset.rel || '';
      const segs = rel ? [...currentPath, ...rel.split(SEP)] : [...currentPath];
      setSpyPath((prev) => (keyOf(prev) === keyOf(segs) ? prev : segs));
    };
    const onScroll = () => { if (!raf) raf = requestAnimationFrame(pick); };
    pick();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => { window.removeEventListener('scroll', onScroll); if (raf) cancelAnimationFrame(raf); };
  }, [currentKey, byKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-expand the folder chain down to the spied section so its leaf row is
  // actually rendered (its ancestors are folders, collapsed by default).
  useEffect(() => {
    if (spyPath.length <= currentPath.length) return;
    for (let i = currentPath.length; i < spyPath.length; i++) load(spyPath.slice(0, i));
    setExpanded((prev) => {
      const s = new Set(prev);
      let changed = false;
      for (let i = currentPath.length; i < spyPath.length; i++) {
        const k = keyOf(spyPath.slice(0, i));
        if (!s.has(k)) { s.add(k); changed = true; }
      }
      return changed ? s : prev;
    });
  }, [spyKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // Keep the highlighted (spied) row visible — but scroll only the sidebar's own
  // scroll box, never the window, so the reading position isn't disturbed.
  useEffect(() => {
    if (!activeSection) return;
    const t = setTimeout(() => {
      const tree = document.querySelector('.car-tree');
      const row = document.querySelector('.tree-label.spy');
      if (!tree || !row) return;
      const tr = tree.getBoundingClientRect();
      const rr = row.getBoundingClientRect();
      if (rr.top < tr.top + 12 || rr.bottom > tr.bottom - 12) {
        tree.scrollTop += (rr.top - tr.top) - tree.clientHeight / 2;
      }
    }, 140);
    return () => clearTimeout(t);
  }, [activeSection, byKey]);

  const toggle = (segs) => {
    const key = keyOf(segs);
    setExpanded((prev) => {
      const s = new Set(prev);
      if (s.has(key)) s.delete(key);
      else { s.add(key); if (!byKey[key]) load(segs); }
      return s;
    });
  };

  function TreeRow({ node, segs }) {
    const folder = !node.has_content;
    const key = keyOf(segs);
    const open = expanded.has(key);
    const active = samePath(segs, currentPath);
    const trail = isAncestor(segs, currentPath);
    // Scroll-spy highlighting: the leaf you're reading, and the trail of folders
    // leading down to it (so the whole path to your position is lit).
    const spy = !folder && node.id != null && String(node.id) === String(activeSection);
    const spyTrail = !active && spyPath.length > currentPath.length && isAncestor(segs, spyPath);
    const depth = segs.length;                 // 1 = chapter, deeper = sections
    const href = buildNodeHref(brand, year, model, segs);

    const rowCls = [
      'tree-row',
      `depth-${Math.min(depth, 4)}`,
      active ? 'active-row' : '',
      trail ? 'trail-row' : '',
      spyTrail ? 'spy-trail-row' : '',
    ].filter(Boolean).join(' ');

    // Navigate — but if this node's content is already rendered on the current
    // stacked page, scroll to it instead (no reload, no route change: the whole
    // point of the flattened page). A leaf maps to its own <section>; a folder
    // maps to the FIRST section beneath it (its children are folders, not
    // sections). Falls back to normal navigation when nothing is on the page.
    const scrollToEl = (el, id) => {
      history.replaceState(null, '', `#node-${id}`);
      el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };
    const go = () => {
      if (typeof document !== 'undefined' && node.id != null) {
        const own = document.getElementById(`node-${node.id}`);
        if (own) { scrollToEl(own, node.id); return; }
        // Descendant of (or equal to) the stacked root => its sections are here.
        if (samePath(segs, currentPath) || isAncestor(currentPath, segs)) {
          const rel = segs.slice(currentPath.length).join(SEP);
          for (const el of document.querySelectorAll('.stack-section[data-rel]')) {
            const dr = el.dataset.rel || '';
            if (dr === rel || (rel && dr.startsWith(rel + SEP))) {
              scrollToEl(el, el.id.slice(5));
              return;
            }
          }
        }
      }
      router.push(href);
    };

    return (
      <li className="tree-li">
        <div className={rowCls} ref={active ? activeRef : null}>
          {folder ? (
            <button
              type="button"
              className={`tree-caret${open ? ' open' : ''}`}
              aria-label={open ? 'بستن' : 'باز کردن'}
              aria-expanded={open}
              onClick={() => toggle(segs)}
            >
              <svg viewBox="0 0 16 16" width="11" height="11" aria-hidden="true">
                <path d="M4 6l4 4 4-4" fill="none" stroke="currentColor"
                      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          ) : (
            <span className="tree-caret tree-dot" aria-hidden="true" />
          )}
          <span
            className={`tree-label${active ? ' active' : ''}${spy ? ' spy' : ''}`}
            onClick={go}
            title={node.title}
            role="link"
            tabIndex={0}
            onKeyDown={(e) => { if (e.key === 'Enter') go(); }}
          >{node.title}</span>
        </div>
        {folder && open && renderLevel(segs)}
      </li>
    );
  }

  function renderLevel(parentSegs) {
    const entry = byKey[keyOf(parentSegs)];
    if (!entry) return null;
    if (entry.loading) return <div className="tree-loading">در حال بارگذاری…</div>;
    if (!entry.children.length) return null;
    return (
      <ul className="tree-children">
        {entry.children.map((node) => (
          <TreeRow key={node.id || node.title} node={node}
                   segs={[...parentSegs, urlToSeg(node.title)]} />
        ))}
      </ul>
    );
  }

  return (
    <nav className="car-tree" aria-label="فهرست خودرو">
      <div className="car-tree-head">
        <span className="car-tree-kicker">فهرست مطالب</span>
        {model}
      </div>
      {renderLevel([]) || <div className="tree-loading">در حال بارگذاری…</div>}
    </nav>
  );
}
