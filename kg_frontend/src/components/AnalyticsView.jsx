'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { motion, MotionConfig, useReducedMotion } from 'motion/react';
import Icon from './Icon';
import { teamApi, portalRefreshMe, getPortalToken } from '../utils/api';

const RANGES = [
  { id: '7', label: '۷ روز' },
  { id: '30', label: '۳۰ روز' },
  { id: '90', label: '۹۰ روز' },
];

// count-up hook (respects reduced motion)
function useCountUp(target, reduce) {
  const [val, setVal] = useState(reduce ? target : 0);
  const raf = useRef(0);
  useEffect(() => {
    if (reduce) { setVal(target); return; }
    const start = performance.now();
    const dur = 700;
    const from = 0;
    const tick = (now) => {
      const t = Math.min(1, (now - start) / dur);
      const eased = 1 - Math.pow(1 - t, 3);
      setVal(Math.round(from + (target - from) * eased));
      if (t < 1) raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf.current);
  }, [target, reduce]);
  return val;
}

function CountUp({ value }) {
  const reduce = useReducedMotion();
  const v = useCountUp(Number(value) || 0, !!reduce);
  return <>{v.toLocaleString('fa-IR')}</>;
}

export default function AnalyticsView() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [data, setData] = useState(null);
  const [range, setRange] = useState('30');
  const [memberId, setMemberId] = useState('');

  const fetchData = async (r, mid) => {
    const params = { range: r };
    if (mid) params.member_id = mid;
    const d = await teamApi.analytics(params);
    setData(d);
  };

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!getPortalToken()) { router.replace('/login'); return; }
      try {
        await portalRefreshMe();
        await fetchData(range, memberId);
      } catch (e) {
        if (cancelled) return;
        if (e?.unauthorized) { router.replace('/login'); return; }
        if (e?.forbidden) { router.replace('/browse'); return; }
        setError(e?.message || 'بارگذاری تحلیل‌ها ناموفق بود.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router]);

  const changeRange = async (r) => { setRange(r); setLoading(true); try { await fetchData(r, memberId); } finally { setLoading(false); } };
  const drill = async (mid) => { setMemberId(mid); setLoading(true); try { await fetchData(range, mid); } finally { setLoading(false); } };

  if (loading && !data) return <AnalyticsSkeleton />;
  if (error) return <div className="pform-error">{error}</div>;
  if (!data) return null;

  const focusedMember = memberId ? data.members.find((m) => String(m.id) === String(memberId)) : null;
  const maxCat = Math.max(1, ...data.categories.map((c) => c.count));
  const maxMember = Math.max(1, ...data.members.map((m) => m.events));
  const maxCar = Math.max(1, ...(data.top_cars || []).map((c) => c.count));
  const topCat = data.categories.slice().sort((a, b) => b.count - a.count)[0];

  return (
    <MotionConfig reducedMotion="user">
      <div className="analytics-wrap">
        <div className="an-toolbar">
          <div className="range-chips">
            {RANGES.map((r) => (
              <button key={r.id} className={`range-chip${range === r.id ? ' active' : ''}`} onClick={() => changeRange(r.id)}>{r.label}</button>
            ))}
          </div>
          {focusedMember && (
            <button className="btn an-clear" onClick={() => drill('')}>
              <Icon name="x" size={14} /> نمایش همه ({focusedMember.name})
            </button>
          )}
        </div>

        <div className="an-kpis">
          <Kpi icon="chart" label="کل فعالیت‌ها" value={data.total_events} />
          <Kpi icon="users" label="کاربران فعال" value={data.active_members} />
          <Kpi icon="sparkles" label="پرکاربردترین حوزه" text={topCat && topCat.count ? topCat.label : '—'} />
        </div>

        <div className="an-grid">
          <section className="an-card glass">
            <div className="an-card-head"><h3><Icon name="chart" size={16} /> استفاده به تفکیک حوزه فنی</h3>
              <span className="an-hint">کدام بخش‌ها بیشترین مراجعه را دارند</span></div>
            <div className="bars">
              {data.categories.map((c, i) => (
                <div className="bar-row" key={c.id} title={`${c.label}: ${c.count}`}>
                  <span className="bar-label">{c.label}</span>
                  <div className="bar-track">
                    <motion.div className="bar-fill" initial={{ width: 0 }} animate={{ width: `${(c.count / maxCat) * 100}%` }}
                      transition={{ duration: 0.7, delay: Math.min(i * 0.05, 0.4), ease: [0.22, 1, 0.36, 1] }} />
                  </div>
                  <span className="bar-val">{c.count.toLocaleString('fa-IR')}</span>
                </div>
              ))}
              {data.categories.every((c) => !c.count) && <div className="muted">هنوز داده‌ای برای این بازه ثبت نشده است.</div>}
            </div>
          </section>

          <section className="an-card glass">
            <div className="an-card-head"><h3><Icon name="clock" size={16} /> روند فعالیت روزانه</h3></div>
            <TrendArea series={data.series} />
          </section>

          <section className="an-card glass an-span">
            <div className="an-card-head"><h3><Icon name="users" size={16} /> فعالیت هر کارمند</h3>
              <span className="an-hint">برای مشاهده جزئیات یک نفر روی او کلیک کنید</span></div>
            <div className="member-usage">
              {data.members.map((m) => (
                <button key={m.id} className={`mu-row${String(m.id) === String(memberId) ? ' active' : ''}`} onClick={() => drill(String(m.id))}>
                  <span className="mu-name">{m.name}<small>{m.role_label}</small></span>
                  <div className="mu-track"><motion.div className="mu-fill" initial={{ width: 0 }} animate={{ width: `${(m.events / maxMember) * 100}%` }} transition={{ duration: 0.6 }} /></div>
                  <span className="mu-val">{m.events.toLocaleString('fa-IR')}</span>
                </button>
              ))}
              {data.members.length === 0 && <div className="muted">کارمندی یافت نشد.</div>}
            </div>
          </section>

          {(data.top_cars || []).length > 0 && (
            <section className="an-card glass an-span">
              <div className="an-card-head"><h3><Icon name="car" size={16} /> پرمراجعه‌ترین خودروها</h3></div>
              <div className="bars">
                {data.top_cars.map((c, i) => (
                  <div className="bar-row" key={c.car_id} title={`${c.label}: ${c.count}`}>
                    <span className="bar-label ltr">{c.label}</span>
                    <div className="bar-track"><motion.div className="bar-fill alt" initial={{ width: 0 }} animate={{ width: `${(c.count / maxCar) * 100}%` }} transition={{ duration: 0.7, delay: Math.min(i * 0.05, 0.4) }} /></div>
                    <span className="bar-val">{c.count.toLocaleString('fa-IR')}</span>
                  </div>
                ))}
              </div>
            </section>
          )}
        </div>
      </div>
    </MotionConfig>
  );
}

function Kpi({ icon, label, value, text }) {
  return (
    <motion.div className="an-kpi glass" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }}>
      <div className="an-kpi-ico"><Icon name={icon} /></div>
      <div>
        <div className="an-kpi-val">{text != null ? text : <CountUp value={value} />}</div>
        <div className="an-kpi-label">{label}</div>
      </div>
    </motion.div>
  );
}

// Single-series area chart (daily events). One hue, gradient fill, recessive axis.
function TrendArea({ series }) {
  if (!series || series.length === 0) return <div className="muted" style={{ padding: 12 }}>داده‌ای برای نمایش نیست.</div>;
  const W = 640, H = 180, P = 8;
  const max = Math.max(1, ...series.map((s) => s.count));
  const n = series.length;
  const x = (i) => P + (n <= 1 ? 0 : (i * (W - 2 * P)) / (n - 1));
  const y = (v) => H - P - (v / max) * (H - 2 * P);
  const pts = series.map((s, i) => `${x(i)},${y(s.count)}`);
  const line = `M${pts.join(' L')}`;
  const area = `M${x(0)},${H - P} L${pts.join(' L')} L${x(n - 1)},${H - P} Z`;
  return (
    <div className="trend-wrap">
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="trend-svg" role="img" aria-label="روند فعالیت روزانه">
        <defs>
          <linearGradient id="trendFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.35" />
            <stop offset="100%" stopColor="var(--accent)" stopOpacity="0" />
          </linearGradient>
        </defs>
        <motion.path d={area} fill="url(#trendFill)" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.8 }} />
        <motion.path d={line} fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round"
          initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 1, ease: 'easeInOut' }} />
      </svg>
      <div className="trend-axis"><span>{series[0].date}</span><span>{series[series.length - 1].date}</span></div>
    </div>
  );
}

function AnalyticsSkeleton() {
  return (
    <div className="analytics-wrap">
      <div className="an-kpis">{[0, 1, 2].map((i) => <div key={i} className="an-kpi glass shimmer" style={{ height: 80 }} />)}</div>
      <div className="an-grid">{[0, 1, 2].map((i) => <div key={i} className="an-card glass shimmer" style={{ height: 240 }} />)}</div>
    </div>
  );
}
