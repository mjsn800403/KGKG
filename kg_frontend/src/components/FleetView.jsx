'use client';

import { useState, useMemo, useEffect, useRef } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { motion } from 'motion/react';
import { fetchGrantedFleet, getPortalToken, logActivity, portalRefreshMe } from '../utils/api';
import RecommendationsWidget from './RecommendationsWidget';

const MotionLink = motion.create(Link);

// Model families whose name spans more than one word — checked before the
// default "first word" rule so "Land Cruiser Base" groups under "Land Cruiser"
// and "Corolla Cross Hybrid S" under "Corolla Cross" (not "Land"/"Corolla").
const MULTIWORD_FAMILIES = ['Land Cruiser', 'Corolla Cross', 'Highlander Hybrid'];

// "bZ4X Limited, AWD" -> "bZ4X"; "RAV4 Hybrid SE, 2.5L …" -> "RAV4"; "NX 350h" -> "NX"
export function familyOf(carName) {
  const base = String(carName || '').split(',')[0].trim();
  const hit = MULTIWORD_FAMILIES.find(
    (f) => base.toLowerCase().startsWith(f.toLowerCase() + ' ') || base.toLowerCase() === f.toLowerCase()
  );
  if (hit) return hit;
  return base.split(/\s+/)[0] || base;
}

// Fleet view — loads only the cars the admin granted to this portal seat,
// refreshed from the backend on every visit so grant/revoke takes effect
// immediately without forcing a re-login.
export default function FleetView() {
  const router = useRouter();
  const [cars, setCars] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!getPortalToken()) {
        router.replace('/login');
        return;
      }
      try {
        await portalRefreshMe();
        const items = await fetchGrantedFleet();
        if (cancelled) return;
        setCars(items);
        if (items.length) logActivity('view_fleet', 'مشاهده فهرست خودروهای فعال');
      } catch (e) {
        if (cancelled) return;
        if (e?.unauthorized) {
          router.replace('/login');
          return;
        }
        setError(e?.message || 'بارگذاری خودروها ناموفق بود. لطفاً دوباره وارد شوید.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [router]);

  const [brand, setBrand] = useState('');
  const [year, setYear] = useState('');
  const [family, setFamily] = useState('');
  const [open, setOpen] = useState('');
  const rootRef = useRef(null);

  const brands = useMemo(() => [...new Set(cars.map((c) => c.brand_name))].sort(), [cars]);
  const years = useMemo(
    () => [...new Set(cars.filter((c) => !brand || c.brand_name === brand).map((c) => c.year))].sort((a, b) => b - a),
    [cars, brand]
  );
  const families = useMemo(() => {
    const counts = new Map();
    cars
      .filter((c) => (!brand || c.brand_name === brand) && (!year || String(c.year) === String(year)))
      .forEach((c) => {
        const f = familyOf(c.car_name);
        counts.set(f, (counts.get(f) || 0) + 1);
      });
    return [...counts.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [cars, brand, year]);
  const filtered = useMemo(
    () => cars.filter((c) =>
      (!brand || c.brand_name === brand) &&
      (!year || String(c.year) === String(year)) &&
      (!family || familyOf(c.car_name) === family)
    ),
    [cars, brand, year, family]
  );

  useEffect(() => {
    if (family && !families.some(([f]) => f === family)) setFamily('');
  }, [families, family]);

  useEffect(() => {
    function onDoc(e) {
      if (rootRef.current && !rootRef.current.contains(e.target)) setOpen('');
    }
    document.addEventListener('click', onDoc);
    return () => document.removeEventListener('click', onDoc);
  }, []);

  const toggle = (id) => setOpen((o) => (o === id ? '' : id));

  if (loading) {
    return <div className="empty-state">در حال بارگذاری خودروهای فعال…</div>;
  }

  if (error) {
    return <div className="pform-error">{error}</div>;
  }

  return (
    <div ref={rootRef}>
      {cars.length > 0 && <RecommendationsWidget />}
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

      <div className="model-chips" data-tour="model-filter">
        <span className="chips-label">مدل:</span>
        <button className={`model-chip${family === '' ? ' active' : ''}`} onClick={() => setFamily('')}>
          همه مدل‌ها
        </button>
        {families.map(([f, cnt]) => (
          <button
            key={f}
            className={`model-chip${family === f ? ' active' : ''}`}
            onClick={() => setFamily(family === f ? '' : f)}
          >
            {f}<span className="cnt">{cnt}</span>
          </button>
        ))}
      </div>

      <div className="fleet-grid">
        {filtered.map((c, i) => (
          <MotionLink
            key={`${c.brand_name}-${c.year}-${c.car_name}`}
            href={`/${encodeURIComponent(c.brand_name)}/${c.year}/${encodeURIComponent(c.car_name)}`}
            className="fleet-card glass"
            initial={{ opacity: 0, y: 18 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, delay: Math.min(i * 0.04, 0.4), ease: [0.22, 1, 0.36, 1] }}
            whileHover={{ y: -5 }}
          >
            <span className="badge"></span>
            <div className="tag">{String(c.brand_name).toUpperCase()} / {c.year}</div>
            <h4>{c.car_name}</h4>
            <div className="yrs">مشاهده مستندات ←</div>
          </MotionLink>
        ))}
        {filtered.length === 0 && (
          <div className="empty-state">
            {cars.length === 0
              ? 'هنوز خودرویی برای این حساب تعریف نشده. با ادمین تماس بگیرید.'
              : 'خودرویی مطابق فیلتر یافت نشد.'}
          </div>
        )}
      </div>
    </div>
  );
}
