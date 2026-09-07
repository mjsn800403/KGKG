'use client';

// The card-grid form of a vehicle list: same cards CardGrid draws, with the
// shared vehicle filter on top. Server components (the brand/year browse step,
// the assistant's car picker) render this instead of CardGrid so a fleet of
// hundreds is narrowed by brand/model/year rather than scrolled.

import { useEffect, useMemo, useRef } from 'react';
import Link from 'next/link';
import Icon from './Icon';
import { useVehicleFilter } from './VehicleFilter';

export default function VehicleCardGrid({
  vehicles = [],
  brand = '',
  year = '',
  hrefSuffix = '',
  go = 'مشاهده مستندات ←',
  emptyLabel = 'موردی در این بخش یافت نشد.',
}) {
  // Brand/year live on the route for the browse step and on each row for the
  // assistant picker — fold both into the shape the filter reads.
  const rows = useMemo(
    () => vehicles.map((v) => ({
      ...v,
      brand: v.brand ?? v.brand_name ?? brand,
      model: v.model ?? v.car_name ?? '',
      year: v.year ?? year,
    })),
    [vehicles, brand, year]
  );

  const { filtered, bar } = useVehicleFilter(rows, { searchPlaceholder: 'جستجوی خودرو…' });

  return (
    <>
      {bar}
      <Grid items={filtered} hrefSuffix={hrefSuffix} go={go}
        emptyLabel={vehicles.length ? 'خودرویی مطابق فیلتر یافت نشد.' : emptyLabel} />
    </>
  );
}

function Grid({ items, hrefSuffix, go, emptyLabel }) {
  const gridRef = useRef(null);

  // Staggered reveal, capped: a 200-card fleet must not take 18 seconds to
  // finish appearing, so only the leading cards stagger.
  useEffect(() => {
    const cards = gridRef.current ? gridRef.current.querySelectorAll('.doc-card') : [];
    const timers = [];
    cards.forEach((c) => c.classList.remove('show'));
    cards.forEach((c, i) => {
      timers.push(setTimeout(() => c.classList.add('show'), Math.min(i, 8) * 90));
    });
    return () => timers.forEach(clearTimeout);
  }, [items]);

  if (!items.length) return <div className="empty-state">{emptyLabel}</div>;

  return (
    <div className="doc-grid" ref={gridRef}>
      {items.map((v) => {
        const href = `/${encodeURIComponent(v.brand)}/${v.year}/${encodeURIComponent(v.model)}${hrefSuffix}`;
        return (
          <Link key={href} href={href} className="doc-card explode glass">
            <div className="icon"><Icon name="car" /></div>
            <div>
              <h4>{v.display_name || v.model}</h4>
              <div className="doc-card-sub" dir="ltr">
                {String(v.brand).toUpperCase()} / {v.year}
              </div>
            </div>
            <div className="go">{go}</div>
          </Link>
        );
      })}
    </div>
  );
}
