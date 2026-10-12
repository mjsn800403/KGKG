'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

// Spotlight walkthrough for one tour. Controlled by GuidanceProvider: it renders
// only while a tour is active and calls onClose(completed) when the user
// finishes or skips. No external library — a dimmed overlay with a cut-out ring
// around the current target plus a positioned tooltip. Reduced-motion friendly
// (the ring's CSS transitions are the only motion, and they're subtle).
//
// A step whose target selector isn't on the page is skipped automatically, so a
// tour degrades gracefully if a surface changes.
export default function TourEngine({ tour, onClose }) {
  const [idx, setIdx] = useState(0);
  const [rect, setRect] = useState(null);
  const [tipPos, setTipPos] = useState(null);
  const tipRef = useRef(null);
  const steps = tour?.steps || [];

  const findEl = useCallback((i) => {
    const step = steps[i];
    if (!step) return null;
    // Selectors may be comma-lists ("a, b"); querySelector picks the first match.
    return document.querySelector(step.sel);
  }, [steps]);

  // Advance past steps whose target is missing (in either direction).
  const resolveStep = useCallback((start, dir) => {
    let i = start;
    while (i >= 0 && i < steps.length && !findEl(i)) i += dir;
    return i;
  }, [steps, findEl]);

  const measure = useCallback(() => {
    const el = findEl(idx);
    if (!el) { setRect(null); return; }
    const r = el.getBoundingClientRect();
    const pad = 8;
    const ring = {
      top: r.top - pad, left: r.left - pad,
      width: r.width + pad * 2, height: r.height + pad * 2,
    };
    setRect(ring);
    const tipH = tipRef.current?.offsetHeight || 190;
    const tipW = Math.min(340, window.innerWidth - 32);
    const below = ring.top + ring.height + 14;
    const top = below + tipH < window.innerHeight - 12
      ? below
      : Math.max(12, ring.top - tipH - 14);
    let left = ring.left + ring.width / 2 - tipW / 2;
    left = Math.max(16, Math.min(left, window.innerWidth - tipW - 16));
    setTipPos({ top, left });
  }, [idx, findEl]);

  // On mount, jump to the first present step (skip missing leading targets).
  useEffect(() => {
    const first = resolveStep(0, 1);
    if (first >= steps.length) { onClose(true); return; }
    if (first !== 0) setIdx(first);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tour]);

  useEffect(() => {
    const el = findEl(idx);
    if (el) el.scrollIntoView({ block: 'center', behavior: 'smooth' });
    const t1 = setTimeout(measure, 80);
    const t2 = setTimeout(measure, 420);
    const onWin = () => measure();
    window.addEventListener('resize', onWin);
    window.addEventListener('scroll', onWin, true);
    return () => {
      clearTimeout(t1); clearTimeout(t2);
      window.removeEventListener('resize', onWin);
      window.removeEventListener('scroll', onWin, true);
    };
  }, [idx, findEl, measure]);

  // Esc to leave (also handled globally, but keep it local for focus safety).
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') onClose(false);
      else if (e.key === 'ArrowLeft') go(1);   // RTL: left = next
      else if (e.key === 'ArrowRight') go(-1);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idx, steps.length]);

  function go(dir) {
    const next = resolveStep(idx + dir, dir);
    if (next < 0) return;
    if (next >= steps.length) { onClose(true); return; }
    setIdx(next);
  }

  if (!tour || !steps.length) return null;
  const step = steps[idx];
  if (!step) return null; // guard: idx can never point past the current tour's steps
  const visibleTotal = steps.length;

  return (
    <div className="guide-tour-layer" role="dialog" aria-label={tour.title}>
      {rect && (
        <div
          className="guide-tour-ring"
          style={{ top: rect.top, left: rect.left, width: rect.width, height: rect.height }}
        />
      )}
      <div
        className="guide-tour-tip"
        ref={tipRef}
        style={tipPos ? { top: tipPos.top, left: tipPos.left } : { opacity: 0 }}
      >
        <div className="gt-step">{idx + 1} / {visibleTotal}</div>
        <h5>{step.title}</h5>
        <p>{step.body}</p>
        <div className="guide-tour-nav">
          {idx > 0 && <button type="button" className="btn" onClick={() => go(-1)}>قبلی</button>}
          <button type="button" className="btn btn-accent" onClick={() => go(1)}>
            {idx + 1 >= visibleTotal ? 'پایان' : 'بعدی'}
          </button>
          <button type="button" className="guide-tour-skip" onClick={() => onClose(false)}>
            رد کردن راهنما
          </button>
        </div>
      </div>
    </div>
  );
}
