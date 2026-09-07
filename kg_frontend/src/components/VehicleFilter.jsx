'use client';

// ---------------------------------------------------------------------------
// Shared vehicle filter — ONE filtering experience for the whole platform.
//
// Every screen that lists vehicles (the customer fleet, the admin catalogue,
// the access editors that grant a user/company a car, the data-health and
// vehicle-spec tables, the org-graph seat panel) mounts this same component,
// so "narrow by brand / model / year" always looks and behaves the same.
//
// Those three ARE the filter. Attribute facets read out of the vehicle name
// (trim, drivetrain, powertrain, transmission) were tried and removed on
// request — do not reintroduce them without asking.
//
// Usage — one hook, one line of JSX:
//
//   const { filtered, bar } = useVehicleFilter(cars);
//   return <>{bar}{filtered.map(...)}</>;
//
// The bar disappears on its own below MIN_ITEMS vehicles (nothing to narrow),
// and a caller can add screen-specific facets — e.g. the super-admin's data
// completeness / indexing status:
//
//   useVehicleFilter(cars, { facets: [
//     { id: 'health', label: 'سلامت داده', options: [
//       { id: 'ok', label: 'کامل', test: (car) => car.status === 'complete' },
//     ] },
//   ] })
//
// Vehicle shape is deliberately not fixed: the platform's endpoints return
// `{brand_name, car_name, year}`, `{brand, model, year}`, `{brand, label}` and
// data-quality's `{stem, brand, year}`. readVehicle() normalises all of them.
// ---------------------------------------------------------------------------

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';

// These bars are server-rendered on the browse routes; useLayoutEffect is a
// no-op (and a React warning) on the server, so fall back to useEffect there.
const useIsoLayoutEffect = typeof window === 'undefined' ? useEffect : useLayoutEffect;

// A list longer than this gets a filter bar. Four cars fit on one screen; five
// is where scrolling-to-find starts, so that is where filtering starts too.
export const MIN_ITEMS = 4;

// Model families whose name spans more than one word — checked before the
// default "first word" rule so "Land Cruiser Base" groups under "Land Cruiser"
// and "Grand Highlander XLE, FWD" under "Grand Highlander" (not "Land"/"Grand").
export const MULTIWORD_FAMILIES = [
  'Land Cruiser', 'Corolla Cross', 'Grand Highlander', 'Highlander Hybrid',
  'Crown Signia', 'GR Corolla', 'GR Supra', 'GR Yaris',
];

// Warehouse stems disambiguate a repeated model with a trailing model year —
// "Corolla Cross Hybrid S (2023)". That suffix is metadata, not part of the name.
const YEAR_SUFFIX_RE = /\s*\((\d{4})\)\s*$/;

export function stripYearSuffix(name) {
  return String(name || '').replace(YEAR_SUFFIX_RE, '').trim();
}

// "bZ4X Limited, AWD" -> "bZ4X"; "RAV4 Hybrid SE, 2.5L …" -> "RAV4"; "NX 350h" -> "NX"
export function familyOf(carName) {
  const base = stripYearSuffix(carName).split(',')[0].trim();
  const lower = base.toLowerCase();
  const hit = MULTIWORD_FAMILIES.find(
    (f) => lower === f.toLowerCase() || lower.startsWith(`${f.toLowerCase()} `)
  );
  if (hit) return hit;
  return base.split(/\s+/)[0] || base;
}

// ---------------------------------------------------------------------------
// Normalisation — every vehicle payload in the platform reduced to one shape.
// ---------------------------------------------------------------------------
export function readVehicle(item) {
  if (!item || typeof item !== 'object') {
    return { brand: '', model: '', year: null, label: String(item ?? ''), haystack: String(item ?? '').toLowerCase() };
  }

  const brand = String(item.brand ?? item.brand_name ?? '').trim();
  let model = String(item.model ?? item.car_name ?? item.display_name ?? item.stem ?? '').trim();
  let year = item.year ?? null;
  const given = String(item.label ?? '').trim();

  // Org-graph seats ship a single pre-joined label ("Toyota RAV4 LE, AWD 2025")
  // instead of parts; peel the brand off the front and the year off the back.
  if (!model && given) {
    let rest = given;
    if (brand && rest.toLowerCase().startsWith(brand.toLowerCase())) rest = rest.slice(brand.length);
    const m = rest.match(/\s(\d{4})\s*$/);
    if (m) {
      if (year == null) year = Number(m[1]);
      rest = rest.slice(0, m.index);
    }
    model = rest.trim();
  }
  if (year == null) {
    const m = String(item.car_name ?? item.model ?? item.stem ?? '').match(YEAR_SUFFIX_RE);
    if (m) year = Number(m[1]);
  }

  const clean = stripYearSuffix(model);
  const family = familyOf(model);
  const label = given || [brand, clean, year].filter(Boolean).join(' ');

  return {
    brand,
    model: clean,
    year: year == null || year === '' ? null : year,
    family,
    label,
    // Search still spans the WHOLE name, so typing "AWD" or "Hybrid" finds
    // those vehicles even though neither is a filter of its own.
    haystack: `${brand} ${model} ${year ?? ''} ${family} ${item.stem ?? ''}`.toLowerCase(),
  };
}

// ---------------------------------------------------------------------------
// Built-in dimensions — brand, model, year, and nothing else. `values` returns
// the option ids an item belongs to; an empty array means "this vehicle has no
// value here" (never matched, never counted), which is how a row with no year
// stays out of the year picker instead of inventing a blank entry.
// ---------------------------------------------------------------------------
const one = (x) => (x === '' || x === null || x === undefined ? [] : [String(x)]);

const BUILTIN_DIMS = [
  { id: 'brand', label: 'برند', all: 'همه برندها', kind: 'menu', values: (v) => one(v.brand) },
  { id: 'year', label: 'سال ساخت', all: 'همه سال‌ها', kind: 'menu', sort: 'year', values: (v) => one(v.year) },
  { id: 'family', label: 'مدل', all: 'همه مدل‌ها', kind: 'chips', values: (v) => one(v.family) },
];

// ---------------------------------------------------------------------------
// The hook
// ---------------------------------------------------------------------------
/**
 * @param {Array} items       vehicles in any of the platform's shapes
 * @param {Object} [options]
 * @param {Array}  [options.facets]     extra screen-specific facets
 * @param {number} [options.minItems]   show the bar above this many vehicles
 * @param {string} [options.searchPlaceholder]
 * @param {string} [options.noun]       what is being counted ("خودرو")
 * @param {boolean}[options.dense]      compact spacing for side panels/modals
 * @returns {{filtered: Array, bar: JSX.Element|null, active: boolean, reset: Function}}
 */
const NO_FACETS = [];

export function useVehicleFilter(items, options = {}) {
  const {
    facets = NO_FACETS,
    minItems = MIN_ITEMS,
    searchPlaceholder = 'جستجوی برند / مدل / سال…',
    noun = 'خودرو',
    dense = false,
  } = options;

  const list = useMemo(() => (Array.isArray(items) ? items : []), [items]);
  const rows = useMemo(() => list.map((item) => ({ item, v: readVehicle(item) })), [list]);

  const [q, setQ] = useState('');
  const [sel, setSel] = useState({});

  // Keyed on the caller's array identity, not on the facet ids: a facet's
  // `test` routinely closes over live state (the access editor's "already
  // selected" facet reads the draft grant), so a literal re-created each render
  // is exactly the signal that those closures — and the counts — went stale.
  const dims = useMemo(
    () => [
      ...BUILTIN_DIMS,
      ...facets.map((f) => ({
        id: f.id,
        label: f.label,
        all: f.all || 'همه',
        kind: f.kind || 'chips',
        custom: true,
        options: f.options || [],
        labelOf: (id) => (f.options || []).find((o) => o.id === id)?.label || id,
        values: (v, item) => (f.options || []).filter((o) => o.test(item, v)).map((o) => o.id),
      })),
    ],
    [facets]
  );

  const active = list.length > minItems;

  // A selection the current data cannot satisfy at all (the fleet reloaded, a
  // grant was revoked) is ignored rather than stored-then-cleared, so the list
  // can never sit empty because of a filter nothing on screen still offers.
  const effectiveSel = useMemo(() => {
    const out = {};
    for (const d of dims) {
      const picked = sel[d.id];
      if (picked && rows.some((r) => d.values(r.v, r.item).includes(picked))) out[d.id] = picked;
    }
    return out;
  }, [dims, rows, sel]);

  const matches = useCallback(
    (row, skipId) =>
      dims.every((d) => {
        if (d.id === skipId) return true;
        const picked = effectiveSel[d.id];
        if (!picked) return true;
        return d.values(row.v, row.item).includes(picked);
      }),
    [dims, effectiveSel]
  );

  const needle = q.trim().toLowerCase();
  const searchHit = useCallback(
    (row) => !needle || row.v.haystack.includes(needle),
    [needle]
  );

  const filtered = useMemo(() => {
    if (!active) return list;
    return rows.filter((r) => searchHit(r) && matches(r, null)).map((r) => r.item);
  }, [active, list, rows, searchHit, matches]);

  // Each dimension is counted against everything EXCEPT its own selection, so
  // the numbers on screen tell you what picking that option would actually give.
  const views = useMemo(() => {
    if (!active) return [];
    return dims.map((d) => {
      const counts = new Map();
      rows.forEach((r) => {
        if (!searchHit(r) || !matches(r, d.id)) return;
        d.values(r.v, r.item).forEach((val) => counts.set(val, (counts.get(val) || 0) + 1));
      });
      let opts = [...counts.entries()].map(([id, count]) => ({
        id,
        count,
        label: d.labelOf ? d.labelOf(id) : id,
      }));
      if (d.custom) {
        const order = d.options.map((o) => o.id);
        opts.sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id));
      } else if (d.sort === 'year') {
        opts.sort((a, b) => Number(b.id) - Number(a.id));
      } else {
        opts.sort((a, b) => a.label.localeCompare(b.label, 'fa'));
      }
      return { ...d, options: opts };
    });
  }, [active, dims, rows, searchHit, matches]);

  const reset = useCallback(() => { setSel({}); setQ(''); }, []);

  // Picking narrows; it never dead-ends. Choosing a brand that the standing
  // model filter contradicts drops the model rather than emptying the list —
  // resolved here, at the click, so no effect has to clean up afterwards.
  const pick = useCallback((dimId, value) => {
    setSel((prev) => {
      const next = { ...prev };
      if (!value || prev[dimId] === value) delete next[dimId];
      else next[dimId] = value;

      const anyRow = (chosen) => rows.some((r) =>
        dims.every((d) => !chosen[d.id] || d.values(r.v, r.item).includes(chosen[d.id])));
      for (const d of dims) {
        if (d.id === dimId || !next[d.id] || anyRow(next)) continue;
        delete next[d.id];
      }
      return next;
    });
  }, [dims, rows]);

  const bar = active ? (
    <VehicleFilterBar
      views={views}
      sel={effectiveSel}
      onPick={pick}
      q={q}
      onSearch={setQ}
      onReset={reset}
      shown={filtered.length}
      total={list.length}
      searchPlaceholder={searchPlaceholder}
      noun={noun}
      dense={dense}
    />
  ) : null;

  return { filtered, bar, active, reset, sel: effectiveSel, query: q };
}

// ---------------------------------------------------------------------------
// The bar
// ---------------------------------------------------------------------------
export function VehicleFilterBar({
  views, sel, onPick, q, onSearch, onReset, shown, total,
  searchPlaceholder, noun = 'خودرو', dense = false,
}) {
  const [open, setOpen] = useState('');
  const rootRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const close = (e) => {
      if (!rootRef.current || !rootRef.current.contains(e.target)) setOpen('');
    };
    const onKey = (e) => { if (e.key === 'Escape') setOpen(''); };
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', close);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const menus = views.filter((d) => d.kind === 'menu' && (d.options.length > 1 || sel[d.id]));
  const chipGroups = views.filter((d) => d.kind === 'chips' && (d.options.length > 1 || sel[d.id]));
  const activeCount = views.filter((d) => sel[d.id]).length + (q ? 1 : 0);

  return (
    <div className={`vf${dense ? ' vf-dense' : ''}`} ref={rootRef} data-tour="vehicle-filter">
      <div className="vf-row">
        <label className="vf-search">
          <span className="vf-search-ico" aria-hidden="true">⌕</span>
          <input
            type="search"
            value={q}
            placeholder={searchPlaceholder}
            onChange={(e) => onSearch(e.target.value)}
            aria-label={searchPlaceholder}
          />
        </label>

        {menus.map((d) => (
          <VehicleFilterMenu
            key={d.id}
            dim={d}
            value={sel[d.id] || ''}
            isOpen={open === d.id}
            onToggle={() => setOpen((o) => (o === d.id ? '' : d.id))}
            onPick={(val) => { onPick(d.id, val); setOpen(''); }}
          />
        ))}
      </div>

      {chipGroups.map((d) => (
        <div className="vf-chips" key={d.id}>
          <span className="vf-chips-label">{d.label}:</span>
          <button
            type="button"
            className={`model-chip${sel[d.id] ? '' : ' active'}`}
            onClick={() => onPick(d.id, '')}
          >
            {d.all}
          </button>
          {d.options.map((o) => (
            <button
              type="button"
              key={o.id}
              className={`model-chip${sel[d.id] === o.id ? ' active' : ''}`}
              onClick={() => onPick(d.id, o.id)}
            >
              {o.label}<span className="cnt">{o.count}</span>
            </button>
          ))}
        </div>
      ))}

      <div className="vf-foot">
        <span className="vf-count">
          نمایش <b>{shown.toLocaleString('fa-IR')}</b> از {total.toLocaleString('fa-IR')} {noun}
        </span>
        {activeCount > 0 && (
          <button type="button" className="vf-reset" onClick={onReset}>
            پاک کردن فیلترها ({activeCount.toLocaleString('fa-IR')})
          </button>
        )}
      </div>
    </div>
  );
}

// A dropdown whose menu is fixed-positioned: these bars live inside scrolling
// side panels and cards (`.org-panel-body`, `.card`), which would clip an
// absolutely-positioned menu.
function VehicleFilterMenu({ dim, value, isOpen, onToggle, onPick }) {
  const btnRef = useRef(null);
  const [pos, setPos] = useState(null);

  useIsoLayoutEffect(() => {
    if (!isOpen || !btnRef.current) { setPos(null); return undefined; }
    const place = () => {
      const r = btnRef.current?.getBoundingClientRect();
      if (!r) return;
      const below = window.innerHeight - r.bottom;
      setPos({
        left: r.left,
        width: r.width,
        top: below > 240 ? r.bottom + 6 : undefined,
        bottom: below > 240 ? undefined : window.innerHeight - r.top + 6,
        maxHeight: Math.max(160, Math.min(260, below > 240 ? below - 16 : r.top - 16)),
      });
    };
    place();
    window.addEventListener('scroll', place, true);
    window.addEventListener('resize', place);
    return () => {
      window.removeEventListener('scroll', place, true);
      window.removeEventListener('resize', place);
    };
  }, [isOpen]);

  const current = value ? (dim.options.find((o) => o.id === value)?.label ?? value) : dim.all;

  return (
    <div className={`vf-dd${isOpen ? ' open' : ''}${value ? ' on' : ''}`}>
      <button
        type="button"
        ref={btnRef}
        className="vf-dd-btn"
        onClick={onToggle}
        aria-haspopup="listbox"
        aria-expanded={isOpen}
      >
        <span className="vf-dd-label">{dim.label}</span>
        <span className="vf-dd-value">{current}</span>
        <span className="arr" aria-hidden="true">▾</span>
      </button>
      {isOpen && pos && (
        <div
          className="vf-dd-menu glass"
          role="listbox"
          style={{
            position: 'fixed',
            left: pos.left,
            width: pos.width,
            top: pos.top,
            bottom: pos.bottom,
            maxHeight: pos.maxHeight,
          }}
        >
          <button
            type="button"
            className={`vf-dd-item${value ? '' : ' on'}`}
            role="option"
            aria-selected={!value}
            onClick={() => onPick('')}
          >
            {dim.all}
          </button>
          {dim.options.map((o) => (
            <button
              type="button"
              key={o.id}
              className={`vf-dd-item${value === o.id ? ' on' : ''}`}
              role="option"
              aria-selected={value === o.id}
              onClick={() => onPick(o.id)}
            >
              <span>{o.label}</span>
              <span className="cnt">{o.count}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default useVehicleFilter;
