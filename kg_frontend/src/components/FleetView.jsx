'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { motion } from 'motion/react';
import { fetchGrantedFleet, getPortalUser, logActivity, portalRefreshMe } from '../utils/api';
import RecommendationsWidget from './RecommendationsWidget';
import { useVehicleFilter } from './VehicleFilter';

const MotionLink = motion.create(Link);

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
      // The session token is an HttpOnly cookie and unreadable from JS, so the
      // stored user snapshot is what tells us a session exists. The real check
      // is the 401 handling below.
      if (!getPortalUser()) {
        router.replace('/login');
        return;
      }
      try {
        const me = await portalRefreshMe();
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

  const { filtered, bar } = useVehicleFilter(cars, { searchPlaceholder: 'جستجوی خودرو…' });

  if (loading) {
    return <div className="empty-state">در حال بارگذاری خودروهای فعال…</div>;
  }

  if (error) {
    return <div className="pform-error">{error}</div>;
  }

  return (
    <div>
      {cars.length > 0 && <RecommendationsWidget />}
      {/* No bar on a small fleet — the tour engine skips steps whose target is
          absent, so the guided tour must not find an empty placeholder here. */}
      {bar && <div data-tour="model-filter">{bar}</div>}

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
            {/* has_parts is additive backend data — older payloads simply
                render no chip. Parts-only vehicles say what they open into. */}
            {c.has_parts && (
              <div className="fleet-parts-chip">کاتالوگ قطعات</div>
            )}
            <div className="yrs">
              {c.has_parts && c.has_manual === false
                ? 'مشاهده کاتالوگ قطعات ←'
                : 'مشاهده مستندات ←'}
            </div>
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
