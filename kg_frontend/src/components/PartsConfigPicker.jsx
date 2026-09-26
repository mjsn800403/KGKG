'use client';

// Vehicle configuration (EPC frame) picker for the parts catalogue.
//
// A vehicle can carry ~40 frames, and the old picker printed all of them as raw
// code chips ("ZSG10L-DHXEKW"), which filled the first screen — the whole first
// screen on a phone — before any catalogue content. Here the active
// configuration is one line, and the rest open in a searchable panel that shows
// what actually distinguishes them: engine, transmission, steering, grade,
// market and production period.
import { useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import Icon from './Icon';

// EPC period codes arrive as raw YYYYMM ("202109") — show them as 2021/09.
function period(code) {
  const s = String(code || '').trim();
  return /^\d{6}$/.test(s) ? `${s.slice(0, 4)}/${s.slice(4)}` : s;
}

function frameBits(f) {
  return [
    f.grade && `کلاس ${f.grade}`,
    f.engine && `موتور ${f.engine}`,
    f.transmission && `گیربکس ${f.transmission}`,
    f.steering && `فرمان ${f.steering}`,
    (f.destination || f.region) && `بازار ${f.destination || f.region}`,
  ].filter(Boolean);
}

export default function PartsConfigPicker({ frames = [], active, base }) {
  // Switching configuration returns to the catalogue root (group trees differ
  // per frame, so a deep path may not exist in the next one).
  const hrefFor = (code) => `${base}?cfg=${encodeURIComponent(code)}`;
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const boxRef = useRef(null);

  const activeFrame = frames.find((f) => f.code === active) || frames[0];
  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return frames;
    return frames.filter((f) => [f.code, f.engine, f.transmission, f.steering, f.grade, f.destination, f.region]
      .filter(Boolean).join(' ').toLowerCase().includes(needle));
  }, [frames, q]);

  if (!frames.length) return null;
  // A single configuration needs no picker — its details show in the strip.
  if (frames.length === 1) return null;

  return (
    <div className="pcfg" data-guide="parts-config" ref={boxRef}>
      <button type="button" className="pcfg-current" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <span className="pcfg-label">پیکربندی خودرو</span>
        <span className="pcfg-value">
          <bdi dir="ltr">{activeFrame?.code}</bdi>
          {frameBits(activeFrame).length > 0 && <small>{frameBits(activeFrame).join(' · ')}</small>}
        </span>
        <span className="pcfg-count">{frames.length.toLocaleString('fa-IR')} پیکربندی</span>
        <span className="pcfg-x" aria-hidden="true" />
      </button>

      {open && (
        <div className="pcfg-panel">
          <label className="pcfg-search">
            <Icon name="search" />
            <input
              value={q} onChange={(e) => setQ(e.target.value)} autoFocus
              placeholder="جستجو بر اساس کد، موتور، گیربکس یا بازار…"
            />
          </label>
          <ul className="pcfg-list">
            {filtered.map((f) => (
              <li key={f.code}>
                <Link
                  href={hrefFor(f.code)}
                  className={`pcfg-item${f.code === active ? ' is-on' : ''}`}
                  onClick={() => setOpen(false)}
                >
                  <bdi dir="ltr" className="pcfg-code">{f.code}</bdi>
                  <span className="pcfg-bits">{frameBits(f).join(' · ') || '—'}</span>
                  {f.date_from && (
                    <span className="pcfg-period">
                      <bdi dir="ltr">{period(f.date_from)}{f.date_to ? ` – ${period(f.date_to)}` : ' –'}</bdi>
                    </span>
                  )}
                </Link>
              </li>
            ))}
            {filtered.length === 0 && <li className="pcfg-empty">پیکربندی‌ای با این مشخصات پیدا نشد.</li>}
          </ul>
          <p className="pcfg-note">با تغییر پیکربندی، به ریشهٔ کاتالوگ برمی‌گردید؛ گروه‌های قطعات در هر پیکربندی متفاوت‌اند.</p>
        </div>
      )}
    </div>
  );
}
