// Shared helpers for the parts-catalog routes (server-component safe).
import Link from 'next/link';
import PartsConfigPicker from './PartsConfigPicker';

export const PARTS_LABEL = 'کاتالوگ قطعات یدکی';

// EPC category -> canonical analytics category id (mirrors the backend map in
// api/partsingest.CATEGORY_ANALYTICS; keep the two in sync).
export const PARTS_CATEGORY_ANALYTICS = {
  'Engine/Fuel/Tool': 'engine',
  'Power Train/Chassis': 'transmission',
  'Body/Interior': 'body',
  'Electrical': 'electrical',
};

export function partsBase(brand, year, model) {
  return `/${encodeURIComponent(brand)}/${year}/${encodeURIComponent(model)}/parts`;
}

export function partsHref(brand, year, model, segments = [], cfg = '') {
  const base = partsBase(brand, year, model);
  const path = segments.length ? `/${segments.map(encodeURIComponent).join('/')}` : '';
  const q = cfg ? `?cfg=${encodeURIComponent(cfg)}` : '';
  return `${base}${path}${q}`;
}

// Breadcrumb for parts pages. The stock Breadcrumb builds hrefs into the
// manuals catch-all; parts segments must link back into /parts with the
// active configuration preserved.
export function PartsBreadcrumb({ brand, year, model, path = [], cfg = '' }) {
  const encodedBrand = encodeURIComponent(brand);
  const encodedModel = encodeURIComponent(model);
  const items = [
    { label: 'خودروهای فعال', href: '/browse' },
    { label: brand, href: `/${encodedBrand}` },
    { label: year, href: `/${encodedBrand}/${year}` },
    { label: model, href: `/${encodedBrand}/${year}/${encodedModel}` },
    { label: PARTS_LABEL, href: partsHref(brand, year, model, [], cfg) },
    ...path.map((p, index) => ({
      label: p,
      href: partsHref(brand, year, model, path.slice(0, index + 1), cfg),
    })),
  ];
  return (
    <div className="breadcrumb">
      {items.map((item, index) => (
        <span key={index} style={{ display: 'inline-flex', alignItems: 'center', gap: 10 }}>
          {index > 0 && <span className="sep">/</span>}
          {/* <bdi>: catalog labels are English inside RTL chrome, and one that
              ends in a neutral character (")", "/") would otherwise be
              reordered by the bidi algorithm. */}
          {index === items.length - 1 ? (
            <b><bdi>{item.label}</bdi></b>
          ) : (
            <Link href={item.href}><bdi>{item.label}</bdi></Link>
          )}
        </span>
      ))}
    </div>
  );
}

// Config (frame) picker — pure links, no client JS. Shown only when the
// vehicle maps to more than one source configuration.
export function ConfigPicker({ brand, year, model, frames, active }) {
  if (!frames || frames.length <= 1) return null;
  // Switching configuration returns to the catalog root: group trees differ per
  // frame, so a deep path may not exist in the next one.
  // Server components cannot hand a function to a client component, so the
  // picker gets the catalogue root and builds its own links.
  return <PartsConfigPicker frames={frames} active={active} base={partsBase(brand, year, model)} />;
}

// EPC period codes arrive as raw YYYYMM ("202109") — show them as 2021/09.
function period(code) {
  const s = String(code || '').trim();
  return /^\d{6}$/.test(s) ? `${s.slice(0, 4)}/${s.slice(4)}` : s;
}

// One-line spec strip for the active configuration.
export function FrameInfo({ frame }) {
  if (!frame) return null;
  // The picker above already names the configuration and its engine/steering/
  // market, so this strip carries only what it does not: how big the catalogue
  // is for this frame, and the production window it covers.
  const fa = (n) => Number(n ?? 0).toLocaleString('fa-IR');
  const bits = [
    frame.n_groups != null && `${fa(frame.n_groups)} گروه قطعه`,
    frame.n_parts != null && `${fa(frame.n_parts)} قطعه`,
    frame.date_from && `تولید از ${period(frame.date_from)}`
      + (frame.date_to ? ` تا ${period(frame.date_to)}` : ' تاکنون'),
    frame.transmission && `گیربکس ${frame.transmission}`,
  ].filter(Boolean);
  return (
    <div className="parts-frame-info">
      {bits.map((b, i) => <span key={i} className="parts-frame-bit">{b}</span>)}
    </div>
  );
}
