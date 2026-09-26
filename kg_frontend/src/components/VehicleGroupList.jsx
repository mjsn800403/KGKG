'use client';

// One way to present a list of vehicles across the whole portal: grouped by
// model family, collapsed while the list is long, flat while it is short.
// Used by the fleet (خودروهای فعال), the brand/year browse step and the
// assistant's car picker — a 235-vehicle catalogue is unreadable as a flat
// grid of cards (it ran to 40,000px on a phone).
//
// The caller owns the card markup and passes it as `renderItem`, so the fleet
// keeps its parts chip and the picker keeps its own call to action.
import { useMemo, useState } from 'react';
import { familyOf } from './VehicleFilter';

const FA = (n) => Number(n).toLocaleString('fa-IR');
// Below this many vehicles a flat grid is already scannable.
export const GROUP_FROM = 9;
// Groups start open while the visible list is short (a narrowed filter or a
// small catalogue), collapsed otherwise so the page reads as a list of models.
const OPEN_UNDER = 24;

function groupByFamily(rows, keyOf) {
  const map = new Map();
  rows.forEach((row) => {
    const v = keyOf(row);
    const family = familyOf(v.model);
    const key = `${v.brand}|${family}`;
    if (!map.has(key)) map.set(key, { key, brand: v.brand, family, rows: [], years: [] });
    const g = map.get(key);
    g.rows.push(row);
    if (v.year) g.years.push(Number(v.year));
  });
  return [...map.values()]
    .map((g) => ({
      ...g,
      min: g.years.length ? Math.min(...g.years) : null,
      max: g.years.length ? Math.max(...g.years) : null,
    }))
    .sort((a, b) => a.brand.localeCompare(b.brand) || a.family.localeCompare(b.family));
}

export default function VehicleGroupList({
  rows = [],
  total = rows.length,
  keyOf = (r) => ({ brand: r.brand ?? r.brand_name ?? '', model: r.model ?? r.car_name ?? '', year: r.year }),
  renderItem,
  itemKey = (r, i) => i,
  empty = null,
  gridClass = 'fleet-grid',
}) {
  const groups = useMemo(() => groupByFamily(rows, keyOf), [rows, keyOf]);
  const grouped = total >= GROUP_FROM && rows.length > 0;
  // null = follow the list length; true/false = the reader's explicit choice.
  const [allOpen, setAllOpen] = useState(null);
  const openNow = allOpen ?? (rows.length <= OPEN_UNDER || groups.length === 1);

  if (!rows.length) return empty;

  if (!grouped) {
    return <div className={gridClass}>{rows.map((r, i) => <Item key={itemKey(r, i)} r={r} i={i} renderItem={renderItem} />)}</div>;
  }

  return (
    <>
      <div className="fleet-groups-bar">
        <span>{FA(groups.length)} مدل</span>
        <button type="button" className="btn fleet-toggle" onClick={() => setAllOpen(!openNow)}>
          {openNow ? 'بستن همه' : 'باز کردن همه'}
        </button>
      </div>
      <div className="fleet-groups">
        {groups.map((g) => (
          <details className="fleet-group" key={`${g.key}:${openNow}`} open={openNow}>
            <summary>
              <span className="fg-name"><bdi dir="ltr">{g.family}</bdi></span>
              <span className="fg-brand"><bdi dir="ltr">{String(g.brand).toUpperCase()}</bdi></span>
              <span className="fg-meta">
                {FA(g.rows.length)} نسخه
                {g.min != null && (
                  <span className="fg-years">
                    <bdi dir="ltr">{g.min === g.max ? g.min : `${g.min}–${g.max}`}</bdi>
                  </span>
                )}
              </span>
              <span className="fg-chev" aria-hidden="true" />
            </summary>
            <div className={gridClass}>
              {g.rows.map((r, i) => <Item key={itemKey(r, i)} r={r} i={i} renderItem={renderItem} />)}
            </div>
          </details>
        ))}
      </div>
    </>
  );
}

function Item({ r, i, renderItem }) {
  return renderItem(r, i);
}
