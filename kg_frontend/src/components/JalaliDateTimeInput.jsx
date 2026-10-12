'use client';

// Shamsi (Jalali) date + time picker for the admin panel.
//
// Drop-in for <input type="datetime-local">: `value` and `onChange(value)` use
// the SAME Gregorian wall-clock string ("YYYY-MM-DDTHH:mm", or '' for none), so
// nothing changes for the backend — only what the admin sees and clicks is
// Shamsi. The panel opens inline (not as a floating popover) so it is never
// clipped by a scrolling modal and fits at 375 px.
//
// Calendar maths is the jalaali-js algorithm (Borkowski), inlined to avoid a
// dependency.

import { useState } from 'react';

const div = (a, b) => ~~(a / b);
const mod = (a, b) => a - ~~(a / b) * b;
const BREAKS = [-61, 9, 38, 199, 426, 686, 756, 818, 1111, 1181, 1210, 1635,
  2060, 2097, 2192, 2262, 2324, 2394, 2456, 3178];

function jalCal(jy) {
  const gy = jy + 621;
  let leapJ = -14, jp = BREAKS[0], jump = 0;
  for (let i = 1; i < BREAKS.length; i += 1) {
    const jm = BREAKS[i];
    jump = jm - jp;
    if (jy < jm) break;
    leapJ += div(jump, 33) * 8 + div(mod(jump, 33), 4);
    jp = jm;
  }
  let n = jy - jp;
  leapJ += div(n, 33) * 8 + div(mod(n, 33) + 3, 4);
  if (mod(jump, 33) === 4 && jump - n === 4) leapJ += 1;
  const leapG = div(gy, 4) - div((div(gy, 100) + 1) * 3, 4) - 150;
  const march = 20 + leapJ - leapG;
  if (jump - n < 6) n = n - jump + div(jump + 4, 33) * 33;
  let leap = mod(mod(n + 1, 33) - 1, 4);
  if (leap === -1) leap = 4;
  return { leap, gy, march };
}

function g2d(gy, gm, gd) {
  const d = div((gy + div(gm - 8, 6) + 100100) * 1461, 4)
    + div(153 * mod(gm + 9, 12) + 2, 5) + gd - 34840408;
  return d - div(div(gy + 100100 + div(gm - 8, 6), 100) * 3, 4) + 752;
}

function d2g(jdn) {
  let j = 4 * jdn + 139361631;
  j += div(div(4 * jdn + 183187720, 146097) * 3, 4) * 4 - 3908;
  const i = div(mod(j, 1461), 4) * 5 + 308;
  const gd = div(mod(i, 153), 5) + 1;
  const gm = mod(div(i, 153), 12) + 1;
  const gy = div(j, 1461) - 100100 + div(8 - gm, 6);
  return { gy, gm, gd };
}

function j2d(jy, jm, jd) {
  const r = jalCal(jy);
  return g2d(r.gy, 3, r.march) + (jm - 1) * 31 - div(jm, 7) * (jm - 7) + jd - 1;
}

function d2j(jdn) {
  const { gy } = d2g(jdn);
  let jy = gy - 621;
  const r = jalCal(jy);
  let k = jdn - g2d(gy, 3, r.march);
  if (k >= 0) {
    if (k <= 185) return { jy, jm: 1 + div(k, 31), jd: mod(k, 31) + 1 };
    k -= 186;
  } else {
    jy -= 1;
    k += 179;
    if (r.leap === 1) k += 1;
  }
  return { jy, jm: 7 + div(k, 30), jd: mod(k, 30) + 1 };
}

export const toJalali = (gy, gm, gd) => d2j(g2d(gy, gm, gd));
export const toGregorian = (jy, jm, jd) => d2g(j2d(jy, jm, jd));
const monthLength = (jy, jm) => (jm <= 6 ? 31 : jm <= 11 ? 30 : jalCal(jy).leap === 0 ? 30 : 29);

export const J_MONTHS = ['فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور',
  'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند'];
const WEEKDAYS = ['ش', 'ی', 'د', 'س', 'چ', 'پ', 'ج'];

const fa = (n) => Number(n).toLocaleString('fa-IR', { useGrouping: false });
const fa2 = (n) => fa(n).padStart(2, '۰');
const p2 = (n) => String(n).padStart(2, '0');

// "YYYY-MM-DDTHH:mm" -> parts, or null.
function parse(v) {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(v || '');
  if (!m) return null;
  const [gy, gm, gd, hh, mi] = m.slice(1).map(Number);
  return { ...toJalali(gy, gm, gd), hh, mi };
}

function build(jy, jm, jd, hh, mi) {
  const { gy, gm, gd } = toGregorian(jy, jm, jd);
  return `${gy}-${p2(gm)}-${p2(gd)}T${p2(hh)}:${p2(mi)}`;
}

function todayJ() {
  const d = new Date();
  return toJalali(d.getFullYear(), d.getMonth() + 1, d.getDate());
}

// Human label for a stored value, e.g. «۵ مهر ۱۴۰۵ · ۱۰:۰۰».
export function jalaliLabel(v) {
  const p = parse(v);
  return p ? `${fa(p.jd)} ${J_MONTHS[p.jm - 1]} ${fa(p.jy)} · ${fa2(p.hh)}:${fa2(p.mi)}` : '';
}

const smallSelect = {
  width: 'auto', padding: '6px 8px', fontSize: 13.5, borderRadius: 8,
  background: 'var(--surface-2)', border: '1px solid var(--border)', color: 'var(--text)',
  fontFamily: 'var(--fa)',
};

export default function JalaliDateTimeInput({
  value, onChange, placeholder = 'انتخاب تاریخ (شمسی)', defaultTime = '23:59',
  clearable = true, disabled = false,
}) {
  const cur = parse(value);
  const [open, setOpen] = useState(false);
  const [view, setView] = useState(null); // {jy, jm} shown in the grid

  const shown = view || (cur ? { jy: cur.jy, jm: cur.jm } : (({ jy, jm }) => ({ jy, jm }))(todayJ()));
  const today = todayJ();
  const [dh, dm] = defaultTime === 'now'
    ? [new Date().getHours(), new Date().getMinutes()]
    : defaultTime.split(':').map(Number);
  const hh = cur ? cur.hh : dh;
  const mi = cur ? cur.mi : dm;

  const shift = (delta) => {
    let jm = shown.jm + delta, jy = shown.jy;
    if (jm < 1) { jm = 12; jy -= 1; }
    if (jm > 12) { jm = 1; jy += 1; }
    setView({ jy, jm });
  };
  const pickDay = (jd) => onChange(build(shown.jy, shown.jm, jd, hh, mi));
  const setTime = (h, m) => {
    const base = cur || { ...today };
    onChange(build(base.jy, base.jm, base.jd, h, m));
  };

  // Saturday-first grid: JS getDay() Sat=6 -> column 0.
  const g = toGregorian(shown.jy, shown.jm, 1);
  const lead = (new Date(g.gy, g.gm - 1, g.gd).getDay() + 1) % 7;
  const days = monthLength(shown.jy, shown.jm);
  const cells = [...Array(lead).fill(null), ...Array.from({ length: days }, (_, i) => i + 1)];
  const years = Array.from({ length: 21 }, (_, i) => today.jy - 5 + i);
  if (!years.includes(shown.jy)) years.push(shown.jy);

  return (
    <div className="jdp">
      <button type="button" disabled={disabled} aria-expanded={open}
        onClick={() => { setOpen((o) => !o); setView(null); }}
        style={{
          width: '100%', textAlign: 'right', background: 'var(--surface-2)',
          border: `1px solid ${open ? 'var(--accent)' : 'var(--border)'}`, color: cur ? 'var(--text)' : 'var(--text-faint)',
          padding: '13px 14px', fontFamily: 'var(--fa)', fontSize: 14.5, borderRadius: 'var(--radius)',
          cursor: disabled ? 'not-allowed' : 'pointer', display: 'flex', justifyContent: 'space-between', gap: 8,
        }}>
        <span>{cur ? jalaliLabel(value) : placeholder}</span>
        <span aria-hidden="true" style={{ opacity: 0.6 }}>{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div role="dialog" aria-label="انتخاب تاریخ شمسی" dir="rtl"
          style={{
            marginTop: 6, padding: 10, borderRadius: 'var(--radius)', background: 'var(--surface)',
            border: '1px solid var(--border)', boxShadow: 'var(--shadow)', maxWidth: 340,
          }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
            <button type="button" className="btn" style={{ padding: '4px 10px' }} onClick={() => shift(-1)} aria-label="ماه قبل">›</button>
            <select value={shown.jm} onChange={(e) => setView({ ...shown, jm: Number(e.target.value) })} style={{ ...smallSelect, flex: 1 }}>
              {J_MONTHS.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}
            </select>
            <select value={shown.jy} onChange={(e) => setView({ ...shown, jy: Number(e.target.value) })} style={smallSelect}>
              {years.sort((a, b) => a - b).map((y) => <option key={y} value={y}>{fa(y)}</option>)}
            </select>
            <button type="button" className="btn" style={{ padding: '4px 10px' }} onClick={() => shift(1)} aria-label="ماه بعد">‹</button>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: 3, textAlign: 'center' }}>
            {WEEKDAYS.map((w) => (
              <div key={w} style={{ fontSize: 12, color: 'var(--text-dim)', padding: '2px 0' }}>{w}</div>
            ))}
            {cells.map((d, i) => {
              if (d === null) return <div key={`e${i}`} />;
              const sel = cur && cur.jy === shown.jy && cur.jm === shown.jm && cur.jd === d;
              const isToday = today.jy === shown.jy && today.jm === shown.jm && today.jd === d;
              return (
                <button key={d} type="button" onClick={() => pickDay(d)}
                  style={{
                    padding: '7px 0', borderRadius: 8, fontFamily: 'var(--fa)', fontSize: 13.5, cursor: 'pointer',
                    background: sel ? 'var(--accent)' : 'transparent',
                    color: sel ? '#fff' : (i % 7 === 6 ? 'var(--gold)' : 'var(--text)'),
                    border: isToday && !sel ? '1px solid var(--accent)' : '1px solid transparent',
                  }}>
                  {fa(d)}
                </button>
              );
            })}
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 10, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 13, color: 'var(--text-dim)' }}>ساعت (تهران):</span>
            <span dir="ltr" style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
              <select value={hh} onChange={(e) => setTime(Number(e.target.value), mi)} style={smallSelect} aria-label="ساعت">
                {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{fa2(h)}</option>)}
              </select>
              :
              <select value={mi} onChange={(e) => setTime(hh, Number(e.target.value))} style={smallSelect} aria-label="دقیقه">
                {Array.from({ length: 60 }, (_, m) => <option key={m} value={m}>{fa2(m)}</option>)}
              </select>
            </span>
          </div>

          <div style={{ display: 'flex', gap: 6, marginTop: 10, flexWrap: 'wrap' }}>
            <button type="button" className="btn" style={{ padding: '5px 12px' }}
              onClick={() => { onChange(build(today.jy, today.jm, today.jd, hh, mi)); setView(null); }}>امروز</button>
            {clearable && (
              <button type="button" className="btn" style={{ padding: '5px 12px' }}
                onClick={() => { onChange(''); setOpen(false); }}>بدون تاریخ</button>
            )}
            <button type="button" className="btn btn-accent" style={{ padding: '5px 12px', marginInlineStart: 'auto' }}
              onClick={() => setOpen(false)}>تأیید</button>
          </div>
        </div>
      )}
    </div>
  );
}
