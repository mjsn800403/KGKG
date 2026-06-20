'use client';

import { useState, useMemo, useEffect, useRef } from 'react';
import Link from 'next/link';

// Fleet view — the prototype's dashboard fleet screen, but the picker
// dropdowns and the fleet-grid are driven by REAL cars from the backend.
export default function FleetView({ cars }) {
  const [brand, setBrand] = useState('');     // '' = all
  const [year, setYear] = useState('');       // '' = all
  const [open, setOpen] = useState('');        // which dropdown is open
  const rootRef = useRef(null);

  const brands = useMemo(() => [...new Set(cars.map((c) => c.brand_name))].sort(), [cars]);
  const years = useMemo(
    () => [...new Set(cars.filter((c) => !brand || c.brand_name === brand).map((c) => c.year))].sort((a, b) => b - a),
    [cars, brand]
  );
  const filtered = useMemo(
    () => cars.filter((c) => (!brand || c.brand_name === brand) && (!year || String(c.year) === String(year))),
    [cars, brand, year]
  );

  useEffect(() => {
    function onDoc(e) {
      if (rootRef.current && !rootRef.current.contains(e.target)) setOpen('');
    }
    document.addEventListener('click', onDoc);
    return () => document.removeEventListener('click', onDoc);
  }, []);

  const toggle = (id) => setOpen((o) => (o === id ? '' : id));

  return (
    <div ref={rootRef}>
      <div className="picker-row">
        <div className={`dropdown${open === 'brand' ? ' open' : ''}`}>
          <div className="dd-btn" onClick={() => toggle('brand')}>
            <span>{brand || 'همه برندها'}</span><span className="arr">▾</span>
          </div>
          <div className="dd-menu glass">
            <div className="dd-item" onClick={() => { setBrand(''); setYear(''); setOpen(''); }}>همه برندها</div>
            {brands.map((b) => (
              <div key={b} className="dd-item" onClick={() => { setBrand(b); setYear(''); setOpen(''); }}>{b}</div>
            ))}
          </div>
        </div>

        <div className={`dropdown${open === 'year' ? ' open' : ''}`}>
          <div className="dd-btn" onClick={() => toggle('year')}>
            <span>{year || 'همه سال‌ها'}</span><span className="arr">▾</span>
          </div>
          <div className="dd-menu glass">
            <div className="dd-item" onClick={() => { setYear(''); setOpen(''); }}>همه سال‌ها</div>
            {years.map((y) => (
              <div key={y} className="dd-item" onClick={() => { setYear(String(y)); setOpen(''); }}>{y}</div>
            ))}
          </div>
        </div>
      </div>

      <div className="fleet-grid">
        {filtered.map((c) => (
          <Link
            key={`${c.brand_name}-${c.year}-${c.car_name}`}
            href={`/${encodeURIComponent(c.brand_name)}/${c.year}/${encodeURIComponent(c.car_name)}`}
            className="fleet-card glass"
          >
            <span className="badge"></span>
            <div className="tag">{String(c.brand_name).toUpperCase()} / {c.year}</div>
            <h4>{c.car_name}</h4>
            <div className="yrs">مشاهده مستندات ←</div>
          </Link>
        ))}
        {filtered.length === 0 && <div className="empty-state">خودرویی مطابق فیلتر یافت نشد.</div>}
      </div>
    </div>
  );
}
