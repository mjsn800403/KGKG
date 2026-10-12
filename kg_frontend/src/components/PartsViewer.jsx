'use client';

// PartsViewer — the parts-catalog leaf: one or more illustration sections,
// each an exploded-view diagram (pan/zoom) + its parts table. This is the
// deliberate UX split from the manuals: same tree navigation above, but the
// last node renders structured catalog data instead of manual HTML.
//
// Interactive callouts: each section ships `labels` — the callout landmarks
// scraped from partsouq (data-codeonimage + data-position/-size, in the
// image's native pixel space). We overlay them on the diagram and link them to
// the table both ways: hovering a part row pulses its marker(s) on the image
// (the red blinking circle), and hovering/clicking a marker highlights and
// scrolls to the matching row(s). Matching is by callout code, exactly as
// partsouq's own script keys off data-codeonimage.
import { useCallback, useEffect, useRef, useState } from 'react';
import Icon from './Icon';

const MIN_SCALE = 1;
const MAX_SCALE = 6;

function PartsDiagram({ image, alt, labels, selected, hovered, onHover, onPick }) {
  const frameRef = useRef(null);
  const [t, setT] = useState({ x: 0, y: 0, scale: 1 });
  const [dragging, setDragging] = useState(false);
  const [nat, setNat] = useState(null);       // { w, h } natural image size
  const imgRef = useRef(null);
  const drag = useRef(null);
  const moved = useRef(false);

  // Read the image's native size once it's known. onLoad ALONE misses cached
  // images — the load event can fire before React attaches the handler (or not
  // at all), leaving `nat` null so no markers ever render. So also check, after
  // mount and on every src change, whether the image is already complete.
  const readNat = useCallback((el) => {
    if (el && el.naturalWidth > 0) {
      setNat({ w: el.naturalWidth, h: el.naturalHeight });
    }
  }, []);
  useEffect(() => { readNat(imgRef.current); }, [image, readNat]);

  // Keep the illustration overlapping its frame: without this a single drag
  // can fling it outside the overflow:hidden box, leaving a blank panel.
  const clampPan = useCallback((x, y, scale) => {
    const el = frameRef.current;
    if (!el) return { x, y };
    const { width, height } = el.getBoundingClientRect();
    const maxX = Math.max(0, (width * scale - width) / 2) + width * 0.25;
    const maxY = Math.max(0, (height * scale - height) / 2) + height * 0.25;
    return {
      x: Math.min(maxX, Math.max(-maxX, x)),
      y: Math.min(maxY, Math.max(-maxY, y)),
    };
  }, []);

  const applyScale = useCallback((prev, nextScale, cx = 0, cy = 0) => {
    const scale = Math.min(MAX_SCALE, Math.max(MIN_SCALE, nextScale));
    if (scale === prev.scale) return prev;
    const k = scale / prev.scale;
    const x = cx - k * (cx - prev.x);
    const y = cy - k * (cy - prev.y);
    return { scale, ...clampPan(x, y, scale) };
  }, [clampPan]);

  // Wheel: zoom ONLY when already zoomed in or with ctrl/⌘ held. A bare wheel
  // at 1× must keep scrolling the page — a 480px panel that eats every scroll
  // is a trap on a long parts page.
  useEffect(() => {
    const el = frameRef.current;
    if (!el) return undefined;
    const onWheel = (e) => {
      const zoomGesture = e.ctrlKey || e.metaKey || t.scale > MIN_SCALE;
      if (!zoomGesture) return;              // let the page scroll
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const cx = e.clientX - rect.left - rect.width / 2;
      const cy = e.clientY - rect.top - rect.height / 2;
      const dir = e.deltaY < 0 ? 1.15 : 1 / 1.15;
      setT((prev) => applyScale(prev, prev.scale * dir, cx, cy));
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [applyScale, t.scale]);

  const onPointerDown = (e) => {
    moved.current = false;                   // reset every press, even at 1×,
    if (t.scale <= MIN_SCALE) return;        // so a later marker click isn't
    e.preventDefault();                      // swallowed by a stale drag flag.
    drag.current = { sx: e.clientX, sy: e.clientY, ox: t.x, oy: t.y };
    setDragging(true);
    e.currentTarget.setPointerCapture?.(e.pointerId);
  };
  const onPointerMove = (e) => {
    if (!drag.current) return;
    const { sx, sy, ox, oy } = drag.current;
    if (Math.abs(e.clientX - sx) + Math.abs(e.clientY - sy) > 3) moved.current = true;
    setT((prev) => ({
      ...prev,
      ...clampPan(ox + (e.clientX - sx), oy + (e.clientY - sy), prev.scale),
    }));
  };
  const onPointerUp = () => { drag.current = null; setDragging(false); };

  const zoom = (dir) => setT((prev) => applyScale(prev, prev.scale * (dir > 0 ? 1.3 : 1 / 1.3)));
  const reset = () => setT({ x: 0, y: 0, scale: 1 });
  const zoomed = t.scale > MIN_SCALE;

  // Only markers with real coordinates and a natural size to resolve against.
  const showMarks = nat && nat.w > 0 && nat.h > 0 && labels && labels.length > 0;

  return (
    <div className="parts-diagram-wrap">
      <div
        className={`parts-diagram${zoomed ? ' zoomed' : ''}${dragging ? ' dragging' : ''}`}
        ref={frameRef}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={onPointerUp}
        onDoubleClick={() => (zoomed ? reset() : zoom(1))}
        role="img"
        aria-label={alt}
      >
        <div
          className="parts-diagram-canvas"
          style={{
            transform: `translate(${t.x}px, ${t.y}px) scale(${t.scale})`,
            // Give the canvas the image's true proportions so it sizes to the
            // frame height at the correct width — and, critically, so the box
            // the callout markers are positioned against IS the image box.
            ...(nat && nat.w > 0 && nat.h > 0
              ? { aspectRatio: `${nat.w} / ${nat.h}` }
              : null),
          }}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            ref={imgRef}
            src={image}
            alt={alt}
            draggable={false}
            onLoad={(e) => readNat(e.target)}
          />
          {showMarks && (
            <div className="parts-landmarks">
              {labels.map((l, i) => {
                const bw = l.w || 24;
                const bh = l.h || 18;
                const cx = (l.x + bw / 2) / nat.w * 100;
                const cy = (l.y + bh / 2) / nat.h * 100;
                const sel = selected != null && l.code === selected;
                const hov = hovered != null && l.code === hovered;
                return (
                  <button
                    type="button"
                    key={`${l.code}-${i}`}
                    className={`parts-landmark${sel ? ' is-selected' : ''}${hov ? ' is-hover' : ''}`}
                    style={{
                      left: `${cx}%`,
                      top: `${cy}%`,
                      width: `${(bw / nat.w) * 100}%`,
                      height: `${(bh / nat.h) * 100}%`,
                    }}
                    title={l.title || l.code}
                    aria-label={l.title || `کد ${l.code}`}
                    onMouseEnter={() => onHover(l.code)}
                    onMouseLeave={() => onHover(null)}
                    onFocus={() => onHover(l.code)}
                    onBlur={() => onHover(null)}
                    onClick={(e) => {
                      // A click that ended a pan must not also pin a callout.
                      if (moved.current) return;
                      e.stopPropagation();
                      onPick(l.code);
                    }}
                  >
                    <span className="parts-landmark-ring" aria-hidden="true" />
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>
      <div className="parts-diagram-tools" dir="ltr">
        <button type="button" onClick={() => zoom(1)} aria-label="zoom in">+</button>
        <button type="button" onClick={() => zoom(-1)} aria-label="zoom out">−</button>
        <button type="button" onClick={reset} aria-label="reset">⟲</button>
        <span className="parts-diagram-zoom">{Math.round(t.scale * 100)}%</span>
        <span className="parts-diagram-hint">
          {zoomed
            ? 'کشیدن برای جابه‌جایی · اسکرول برای بزرگ‌نمایی · دوبار کلیک = بازنشانی'
            : 'روی قطعه در جدول یا تصویر بروید تا مکان آن مشخص شود'}
        </span>
      </div>
    </div>
  );
}

// navigator.clipboard only exists in a secure context; this deployment is
// served over plain HTTP, so the async API is undefined here and the button
// would silently do nothing. Fall back to the legacy execCommand path.
function writeClipboard(text) {
  if (navigator.clipboard?.writeText) {
    return navigator.clipboard.writeText(text);
  }
  return new Promise((resolve, reject) => {
    try {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', '');
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand('copy');
      document.body.removeChild(ta);
      ok ? resolve() : reject(new Error('copy rejected'));
    } catch (e) {
      reject(e);
    }
  });
}

function CopyPn({ pn }) {
  const [ok, setOk] = useState(false);
  const copy = async () => {
    try {
      await writeClipboard(pn);
      setOk(true);
      setTimeout(() => setOk(false), 1200);
    } catch { /* clipboard unavailable — ignore */ }
  };
  return (
    <button type="button" className={`parts-copy${ok ? ' ok' : ''}`} onClick={copy}
      title="کپی شماره فنی" aria-label={`کپی ${pn}`}>
      <Icon name={ok ? 'check' : 'copy'} size={13} />
    </button>
  );
}

function PartsTable({ parts, selected, hovered, onHover, onPick, hasLabels }) {
  return (
    <div className="parts-table-wrap">
      <table className="parts-table">
        <thead>
          <tr>
            <th className="c-callout" scope="col">کد روی تصویر</th>
            <th className="c-pn" scope="col">شماره فنی</th>
            <th className="c-name" scope="col">نام قطعه</th>
            <th className="c-qty" scope="col">تعداد</th>
            <th className="c-note" scope="col">ملاحظات</th>
            <th className="c-range" scope="col">بازه تولید</th>
          </tr>
        </thead>
        <tbody>
          {parts.map((p, i) => {
            // Only real callouts (present on the diagram) are interactive;
            // cross-reference rows have no location.
            const linkable = hasLabels && !p.is_xref && p.callout;
            const sel = linkable && p.callout === selected;
            const hov = linkable && p.callout === hovered;
            return (
              <tr
                key={`${p.pn}-${i}`}
                data-callout={linkable ? p.callout : undefined}
                className={`${p.is_xref ? 'parts-row-xref' : ''}${sel ? ' is-selected' : ''}${hov ? ' is-hover' : ''}${linkable ? ' parts-row-linkable' : ''}`}
                onMouseEnter={linkable ? () => onHover(p.callout) : undefined}
                onMouseLeave={linkable ? () => onHover(null) : undefined}
                onClick={linkable ? () => onPick(p.callout) : undefined}
              >
                <td className="c-callout" dir="ltr">{p.is_xref ? '—' : p.callout}</td>
                <td className="c-pn" dir="ltr">
                  <span className="pn-text">{p.pn_display || p.pn}</span>
                  <CopyPn pn={p.pn_display || p.pn} />
                </td>
                <td className="c-name">
                  {p.is_xref ? (
                    <span className="parts-xref-badge">مرجع جایگزین / شماره مرتبط</span>
                  ) : (
                    <>
                      <span dir="ltr" className="name-en">{p.name_en}</span>
                      {p.name_fa && <span className="name-fa">{p.name_fa}</span>}
                    </>
                  )}
                </td>
                <td className="c-qty" dir="ltr"
                  title={p.qty_display === 'X' ? 'X = به مقدار لازم' : undefined}>
                  {p.is_xref ? '' : (p.qty_display ?? p.qty)}
                </td>
                <td className="c-note" dir="ltr">{p.note}</td>
                <td className="c-range" dir="ltr">{p.date_range}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function PartsSection({ group, section }) {
  const labels = section.labels || [];
  const hasLabels = labels.length > 0;
  const [hover, setHover] = useState(null);     // transient (pointer over) — preview
  const [selected, setSelected] = useState(null); // sticky (clicked) — persists
  const bodyRef = useRef(null);
  const active = hover || selected;             // whichever should scroll into view

  // Bring the matching table row into view when a callout becomes active
  // (block:'nearest' means an already-visible row never jumps).
  useEffect(() => {
    if (active == null || !bodyRef.current) return;
    const esc = (window.CSS && CSS.escape) ? CSS.escape(active) : active.replace(/"/g, '\\"');
    const row = bodyRef.current.querySelector(`tr[data-callout="${esc}"]`);
    row?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }, [active]);

  // Click toggles a persistent selection (click the same item again to clear).
  const pick = (code) => setSelected((p) => (p === code ? null : code));

  return (
    <section className="parts-section glass">
      <header className="parts-section-head">
        <h3><bdi>{section.caption || group?.label}</bdi></h3>
        {section.figure_code && <span className="parts-fig" dir="ltr">FIG {section.figure_code}</span>}
      </header>
      <PartsDiagram
        image={section.image}
        alt={`${group?.label || ''} — ${section.caption || ''}`}
        labels={labels}
        selected={selected}
        hovered={hover}
        onHover={setHover}
        onPick={pick}
      />
      <div ref={bodyRef}>
        <PartsTable
          parts={section.parts || []}
          selected={selected}
          hovered={hover}
          onHover={setHover}
          onPick={pick}
          hasLabels={hasLabels}
        />
      </div>
    </section>
  );
}

export default function PartsViewer({ group, sections }) {
  return (
    <div className="parts-viewer">
      {group?.category && (
        <div className="parts-cat-line" >
          <span className="parts-cat-chip">{group.category_fa || group.category}</span>
          <span className="parts-cat-en" dir="ltr">{group.category}</span>
        </div>
      )}
      {sections.map((s, i) => (
        <PartsSection key={`${s.figure_code}-${i}`} group={group} section={s} />
      ))}
      {sections.length === 0 && (
        <div className="empty-state">برای این بخش دیاگرامی ثبت نشده است.</div>
      )}
    </div>
  );
}
