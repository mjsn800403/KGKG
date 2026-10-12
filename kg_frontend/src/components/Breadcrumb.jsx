'use client';

// Dashboard topbar breadcrumb. Deep manual paths are collapsed to
// «vehicles · brand · year · vehicle · … · parent · current» so the trail stays on one
// line; the «…» expands the full trail in place.
import { useState } from 'react';
import Link from 'next/link';
import { buildNodeHref } from '@/utils/api';

const KEEP_TAIL = 2;   // parent + current page

export default function Breadcrumb({ brand, year, model, path = [] }) {
  const [expanded, setExpanded] = useState(false);
  const encodedBrand = encodeURIComponent(brand);
  const encodedModel = encodeURIComponent(model);

  const items = [
    { label: 'خودروهای فعال', href: '/browse' },
    { label: brand, href: `/${encodedBrand}` },
    ...(year ? [{ label: year, href: `/${encodedBrand}/${year}` }] : []),
    ...(model ? [{ label: model, href: `/${encodedBrand}/${year}/${encodedModel}`, car: true }] : []),
    ...path.map((p, index) => ({
      label: p,
      href: buildNodeHref(brand, year, model, path.slice(0, index + 1)),
    })),
  ].map((it, i) => ({ ...it, i }));

  // Always keep everything up to the vehicle itself, then the last two levels.
  const carIndex = Math.max(items.findIndex((it) => it.car), 1);
  const collapsible = !expanded && items.length > carIndex + 1 + KEEP_TAIL + 1;
  const visible = collapsible
    ? items.filter((it) => it.i <= carIndex || it.i >= items.length - KEEP_TAIL)
    : items;
  const hidden = collapsible ? items.filter((it) => !visible.includes(it)) : [];

  const out = [];
  visible.forEach((item, n) => {
    const prev = visible[n - 1];
    if (prev && item.i - prev.i > 1) out.push({ gap: true, key: `gap${item.i}` });
    out.push({ ...item, key: `i${item.i}` });
  });

  return (
    <nav className="breadcrumb" aria-label="مسیر">
      {out.map((item, index) => (
        <span key={item.key} className="bc-item">
          {index > 0 && <span className="sep" aria-hidden="true">/</span>}
          {item.gap ? (
            <button
              type="button"
              className="bc-more"
              onClick={() => setExpanded(true)}
              title={hidden.map((h) => h.label).join(' / ')}
              aria-label={`نمایش ${hidden.length} سطح پنهان مسیر`}
            >
              …
            </button>
          ) : item.i === items.length - 1 ? (
            <b aria-current="page">{item.label}</b>
          ) : (
            <Link href={item.href}>{item.label}</Link>
          )}
        </span>
      ))}
    </nav>
  );
}
