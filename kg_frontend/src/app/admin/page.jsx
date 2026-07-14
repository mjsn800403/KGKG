'use client';

// KGtechvault admin panel.
//
// The platform admin sees EVERYTHING: every purchase/demo request (with company
// size + requested seats), the full car catalog, every company, every issued
// user, and what those users are doing. The core workflow mirrors the business:
//   request comes in  ->  admin reviews & approves  ->  admin defines a company
//   ->  grants the company the cars/doc-layers it bought  ->  issues role-based
//   users (after-sales manager, technical expert, ...)  ->  narrows each user's
//   access to a subset of the company's purchase.
//
// Server-side everything is gated by KG_ADMIN_TOKEN (open in DEBUG for local
// dev). If the backend rejects us we prompt for the token.

import { Fragment, useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { AnimatePresence, motion, MotionConfig } from 'motion/react';
import Icon from '@/components/Icon';
import AdminDashboard from '@/components/AdminDashboard';
import RequestsInbox from '@/components/RequestsInbox';
import { adminApi, adminLogout, getAdminToken, getAdminUser } from '@/utils/api';
import { DEPARTMENT_PRESETS, PACKAGES, ROLES, packageLabel, roleWithDepartment } from '@/lib/packages';

const DOCS = PACKAGES.map((p) => ({ id: p.id, label: p.label }));
const ALL_DOC_IDS = DOCS.map((d) => d.id);

const ACCESS_PRESETS = [
  { id: 'all', label: 'همه پکیج‌ها', docs: ALL_DOC_IDS },
  { id: 'manager', label: 'مدیر (همه)', docs: ALL_DOC_IDS },
  { id: 'specialist', label: 'کارشناس (راهنما+قطعات)', docs: ['manual', 'parts'] },
  { id: 'parts_only', label: 'فقط قطعات', docs: ['parts'] },
];

const REQ_STATUS = {
  new: { label: 'جدید', cls: 'st-new' },
  reviewing: { label: 'در حال بررسی', cls: 'st-rev' },
  approved: { label: 'تأیید شده', cls: 'st-ok' },
  rejected: { label: 'رد شده', cls: 'st-no' },
};

const SECTIONS = [
  { id: 'dashboard', label: 'داشبورد بلادرنگ', icon: 'chart', desc: 'وضعیت زندهٔ پلتفرم، پردازش و رویدادها' },
  { id: 'overview', label: 'نمای کلی', icon: 'catalog', desc: 'خلاصه وضعیت کل پلتفرم در یک نگاه' },
  { id: 'catalog', label: 'فهرست خودروها', icon: 'car', desc: 'خودروهای ثبت‌شده و وضعیت دیتابیس هرکدام' },
  { id: 'requests', label: 'درخواست‌های خرید', icon: 'cart', desc: 'درخواست‌های جدید مشتریان و صدور دسترسی' },
  { id: 'company-requests', label: 'درخواست‌های شرکت‌ها', icon: 'cart', desc: 'درخواست‌های مدیران شرکت‌ها و رسیدگی به آن‌ها' },
  { id: 'companies', label: 'شرکت‌ها و دسترسی‌ها', icon: 'building', desc: 'تعریف شرکت و دامنه خرید هرکدام' },
  { id: 'users', label: 'کاربران', icon: 'users', desc: 'صدور و مدیریت حساب‌های شرکتی' },
  { id: 'analytics', label: 'تحلیل کل پلتفرم', icon: 'chart', desc: 'میزان استفاده به تفکیک شرکت و حوزه فنی' },
  { id: 'activity', label: 'گزارش فعالیت', icon: 'clock', desc: 'ریز رویدادهای کاربران در سامانه' },
  { id: 'dataquality', label: 'سلامت داده‌ها', icon: 'shield', desc: 'ممیزی کامل بودن و کیفیت مستندات هر خودرو' },
  { id: 'pipeline', label: 'پردازش داده‌ها', icon: 'refresh', desc: 'ایندکس RAG و پردازش داده‌های جدید' },
  { id: 'system', label: 'پایش سیستم', icon: 'gear', desc: 'منابع سرور، ترافیک و هشدارهای عملیاتی' },
];

// The hub groups the sections so the admin lands on a calm "desk", not the
// full firehose — a section's tools appear only after entering it.
const SECTION_GROUPS = [
  { title: 'بلادرنگ', tag: '// REALTIME', ids: ['dashboard', 'company-requests'] },
  { title: 'مشتریان و فروش', tag: '// CUSTOMERS', ids: ['requests', 'companies', 'users'] },
  { title: 'گزارش و تحلیل', tag: '// INSIGHTS', ids: ['overview', 'analytics', 'activity'] },
  { title: 'داده و عملیات', tag: '// OPERATIONS', ids: ['catalog', 'dataquality', 'pipeline', 'system'] },
];

function fmtDate(iso) {
  try {
    return new Date(iso).toLocaleString('fa-IR', { dateStyle: 'short', timeStyle: 'short' });
  } catch { return iso; }
}

const EASE = [0.22, 1, 0.36, 1];
const SPRING = { type: 'spring', stiffness: 380, damping: 32, mass: 0.75 };

function readHashSection() {
  if (typeof window === 'undefined') return null;
  const id = (window.location.hash || '').replace('#', '');
  return SECTIONS.some((s) => s.id === id) ? id : null;
}

export default function AdminPage() {
  const router = useRouter();
  // null = the hub (the admin's "desk"); a section id = inside that section.
  const [section, setSection] = useState(null);
  const [adminUser, setAdminUser] = useState(null);
  const [authReady, setAuthReady] = useState(false);
  const [flash, setFlash] = useState('');
  const [companyPrefill, setCompanyPrefill] = useState(null);

  useEffect(() => {
    if (!getAdminToken()) { router.replace('/admin/login'); return; }
    setAdminUser(getAdminUser());
    setSection(readHashSection());
    setAuthReady(true);
    const onHash = () => setSection(readHashSection());
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, [router]);

  const go = useCallback((id) => {
    setSection(id);
    try {
      if (id) window.history.replaceState(null, '', `#${id}`);
      else window.history.replaceState(null, '', window.location.pathname);
    } catch { /* history unavailable */ }
  }, []);

  const guard = useCallback(async (fn) => {
    try {
      return await fn();
    } catch (e) {
      if (e?.unauthorized) { adminLogout(); router.replace('/admin/login'); return null; }
      setFlash(e?.message || 'خطای نامشخص');
      setTimeout(() => setFlash(''), 5000);
      return null;
    }
  }, [router]);

  const handleLogout = () => {
    adminLogout();
    router.replace('/admin/login');
  };

  if (!authReady) {
    return <div className="screen fade" id="admin-panel"><div className="empty-state">در حال بارگذاری…</div></div>;
  }

  const current = SECTIONS.find((s) => s.id === section);

  return (
    <MotionConfig reducedMotion="user">
    <div className="screen fade" id="admin-panel">
      <div className={`shell${section ? '' : ' hub-mode'}`}>
        <AnimatePresence>
          {section && (
            <motion.aside
              className="sidebar"
              initial={{ x: 60, opacity: 0 }}
              animate={{ x: 0, opacity: 1 }}
              exit={{ x: 60, opacity: 0 }}
              transition={SPRING}
            >
              <a className="sb-brand" onClick={() => go(null)} style={{ cursor: 'pointer' }}>
                <img src="/logo.png" alt="KGtechvault" />
                <span>پنل مدیریت</span>
              </a>
              <button type="button" className="sb-link" onClick={() => go(null)}>
                <Icon name="home" /> میز مدیریت
              </button>
              {SECTIONS.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  className={`sb-link${section === s.id ? ' active' : ''}`}
                  onClick={() => go(s.id)}
                >
                  <Icon name={s.icon} /> {s.label}
                </button>
              ))}
              <div style={{ marginTop: 'auto', paddingTop: 30 }}>
                <Link className="sb-link" href="/">
                  <Icon name="logout" /> بازگشت به سایت
                </Link>
              </div>
            </motion.aside>
          )}
        </AnimatePresence>
        <main className="main">
          <div className="topbar">
            <div className="breadcrumb">
              {section ? (
                <>
                  <a onClick={() => go(null)} style={{ cursor: 'pointer' }}>میز مدیریت</a>
                  <span className="crumb-sep"> / </span>
                  <b>{current?.label}</b>
                </>
              ) : (
                <b>میز مدیریت سامانه</b>
              )}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <div className="userchip">
                <div className="avatar">AD</div>
                {adminUser?.username ? `${adminUser.username} — ادمین` : 'KGTECHVAULT — ادمین'}
              </div>
              <button className="btn" onClick={handleLogout}>خروج</button>
            </div>
          </div>

          {flash && <div className="pform-error" style={{ marginBottom: 16 }}>{flash}</div>}

          <AnimatePresence mode="wait">
            <motion.div
              key={section || 'hub'}
              initial={{ opacity: 0, y: 18, filter: 'blur(4px)' }}
              animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
              exit={{ opacity: 0, y: -12, filter: 'blur(4px)' }}
              transition={{ duration: 0.32, ease: EASE }}
            >
              {!section && <AdminHub guard={guard} go={go} adminUser={adminUser} />}
              {section === 'dashboard' && <AdminDashboard go={go} />}
              {section === 'company-requests' && <RequestsInbox />}
              {section === 'overview' && <Overview guard={guard} go={go} />}
              {section === 'catalog' && <Catalog guard={guard} />}
              {section === 'requests' && (
                <Requests
                  guard={guard}
                  onCreateCompany={(prefill) => {
                    setCompanyPrefill(prefill);
                    go('companies');
                  }}
                />
              )}
              {section === 'companies' && (
                <Companies
                  guard={guard}
                  prefilled={companyPrefill}
                  onPrefillUsed={() => setCompanyPrefill(null)}
                />
              )}
              {section === 'users' && <Users guard={guard} />}
              {section === 'analytics' && <PlatformAnalytics guard={guard} />}
              {section === 'activity' && <Activity guard={guard} />}
              {section === 'dataquality' && <DataQuality guard={guard} />}
              {section === 'pipeline' && <Pipeline guard={guard} />}
              {section === 'system' && <SystemMonitor guard={guard} />}
            </motion.div>
          </AnimatePresence>
        </main>
      </div>
    </div>
    </MotionConfig>
  );
}

// ---------------------------------------------------------------------------
// The hub — the admin's landing "desk". A calm overview + grouped doors into
// each section, instead of dropping the admin straight into everything.
// ---------------------------------------------------------------------------
function AdminHub({ guard, go, adminUser }) {
  const [data, setData] = useState(null);
  useEffect(() => { guard(adminApi.overview).then((d) => d && setData(d)); }, [guard]);

  const quickStats = data ? [
    { label: 'درخواست‌های جدید', value: data.requests_new, to: 'requests', hot: (data.requests_new || 0) > 0 },
    { label: 'شرکت‌ها', value: data.companies, to: 'companies' },
    { label: 'کاربران', value: data.users, to: 'users' },
    { label: 'فعالیت امروز', value: data.activities_today, to: 'activity' },
  ] : [];

  const container = { hidden: {}, show: { transition: { staggerChildren: 0.05 } } };
  const item = {
    hidden: { opacity: 0, y: 18, scale: 0.97 },
    show: { opacity: 1, y: 0, scale: 1, transition: { duration: 0.45, ease: EASE } },
  };

  return (
    <div className="admin-hub">
      <motion.div
        className="hub-hero"
        initial={{ opacity: 0, y: 14 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: EASE }}
      >
        <h1>سلام{adminUser?.username ? `، ${adminUser.username}` : ''} 👋</h1>
        <p>از میز مدیریت وارد هر بخش شوید؛ همه‌چیز سر جای خودش است.</p>
      </motion.div>

      <motion.div className="hub-stats" variants={container} initial="hidden" animate="show">
        {quickStats.map((s) => (
          <motion.button key={s.label} className={`hub-stat glass${s.hot ? ' hot' : ''}`}
            variants={item} whileHover={{ y: -4 }} whileTap={{ scale: 0.97 }}
            onClick={() => go(s.to)}>
            <span className="hs-val">{(s.value ?? 0).toLocaleString('fa-IR')}</span>
            <span className="hs-label">{s.label}</span>
            {s.hot && <span className="hs-pulse" />}
          </motion.button>
        ))}
        {!data && [0, 1, 2, 3].map((i) => (
          <div key={i} className="hub-stat glass shimmer" style={{ height: 86 }} />
        ))}
      </motion.div>

      {SECTION_GROUPS.map((group, gi) => (
        <div className="hub-group" key={group.title}>
          <motion.div
            className="hub-group-head"
            initial={{ opacity: 0, x: 14 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.45, ease: EASE, delay: 0.1 + gi * 0.06 }}
          >
            <h2>{group.title}</h2>
            <span className="tag">{group.tag}</span>
          </motion.div>
          <motion.div className="hub-cards" variants={container} initial="hidden"
            whileInView="show" viewport={{ once: true, amount: 0.15 }}>
            {group.ids.map((id) => {
              const s = SECTIONS.find((x) => x.id === id);
              return (
                <motion.button
                  key={id}
                  className="hub-card glass"
                  variants={item}
                  whileHover={{ y: -6 }}
                  whileTap={{ scale: 0.98 }}
                  onClick={() => go(id)}
                >
                  <span className="hc-ico"><Icon name={s.icon} size={22} /></span>
                  <span className="hc-title">{s.label}</span>
                  <span className="hc-desc">{s.desc}</span>
                  <span className="hc-go"><Icon name="back" size={15} /></span>
                </motion.button>
              );
            })}
          </motion.div>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
function Overview({ guard, go }) {
  const [data, setData] = useState(null);
  useEffect(() => { guard(adminApi.overview).then((d) => d && setData(d)); }, [guard]);

  const stats = data ? [
    { label: 'درخواست‌های جدید', value: data.requests_new, section: 'requests' },
    { label: 'کل درخواست‌ها', value: data.requests_total, section: 'requests' },
    { label: 'شرکت‌ها', value: data.companies, section: 'companies' },
    { label: 'کاربران', value: data.users, section: 'users' },
    { label: 'خودروهای موجود', value: data.cars, section: 'catalog' },
    { label: 'فعالیت امروز', value: data.activities_today, section: 'activity' },
  ] : [];

  return (
    <>
      <h1 className="page-title">نمای کلی</h1>
      <div className="page-sub">// ADMIN_OVERVIEW</div>
      <div className="grid3" style={{ marginTop: 20 }}>
        {stats.map((s) => (
          <div key={s.label} className="card glass" style={{ cursor: 'pointer' }} onClick={() => go(s.section)}>
            <div className="num">{s.value}</div>
            <h3>{s.label}</h3>
          </div>
        ))}
        {!data && <div className="empty-state">در حال بارگذاری…</div>}
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
function Catalog({ guard }) {
  const [cars, setCars] = useState([]);
  const [q, setQ] = useState('');

  useEffect(() => {
    guard(adminApi.cars).then((d) => d && setCars(d.items));
  }, [guard]);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return cars;
    return cars.filter((c) =>
      `${c.brand} ${c.model} ${c.year}`.toLowerCase().includes(needle)
    );
  }, [cars, q]);

  return (
    <>
      <h1 className="page-title">فهرست کامل خودروها</h1>
      <div className="page-sub">// FULL_CATALOG — ادمین به همه پکیج‌ها دسترسی دارد</div>
      <p style={{ color: 'var(--text-dim)', fontSize: 14, marginTop: 12, maxWidth: 720 }}>
        این فهرست همه خودروهای موجود در پایگاه کار را نشان می‌دهد. درخواست خرید ممکن است برای خودرویی
        باشد که هنوز در این فهرست نیست — پس از تأیید، خودرو را به دسترسی شرکت اضافه کنید.
      </p>
      <div style={{ margin: '18px 0', maxWidth: 360 }}>
        <input
          placeholder="جستجو برند / مدل / سال…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          style={{ width: '100%' }}
        />
      </div>
      <div className="card glass" style={{ padding: 0, overflow: 'hidden' }}>
        <table className="adm-table">
          <thead>
            <tr><th>#</th><th>برند</th><th>مدل</th><th>سال</th></tr>
          </thead>
          <tbody>
            {filtered.map((c, i) => (
              <tr key={c.id}>
                <td>{i + 1}</td>
                <td>{c.brand}</td>
                <td>{c.model}</td>
                <td dir="ltr">{c.year}</td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr><td colSpan={4} style={{ textAlign: 'center', color: 'var(--text-dim)' }}>خودرویی یافت نشد.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
function SeatPlanTable({ plan }) {
  if (!plan?.length) return null;
  return (
    <table className="seat-plan-table adm-table">
      <thead>
        <tr><th>نقش</th><th>واحد</th><th>تعداد</th><th>توضیح</th></tr>
      </thead>
      <tbody>
        {plan.map((row, i) => {
          const role = ROLES.find((r) => r.id === row.role);
          const label = roleWithDepartment(role?.label || row.role, row.department);
          return (
            <tr key={i}>
              <td>{label}</td>
              <td>{row.department || '—'}</td>
              <td dir="ltr">{row.count}</td>
              <td style={{ color: 'var(--text-dim)' }}>{row.note || '—'}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function IssueUsersWizard({ request, companies, guard, onDone }) {
  const [companyId, setCompanyId] = useState('');
  const [drafts, setDrafts] = useState([]);
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState([]);

  useEffect(() => {
    const match = companies.find((c) => c.name === request.company);
    const cid = match?.id ? String(match.id) : '';
    setCompanyId(cid);
    const rows = [];
    (request.seat_plan || []).forEach((row, ri) => {
      const slug = (request.company || 'co').replace(/\s+/g, '_').slice(0, 12).toLowerCase();
      for (let i = 0; i < (row.count || 0); i += 1) {
        rows.push({
          key: `${ri}-${i}`,
          username: `${slug}_${row.role}_${ri + 1}_${i + 1}`,
          display_name: '',
          role: row.role,
          department: row.department || '',
          note: row.note || '',
        });
      }
    });
    setDrafts(rows);
    setResults([]);
  }, [request, companies]);

  const issue = async () => {
    if (!companyId) return;
    setBusy(true);
    const out = [];
    for (const d of drafts) {
      if (!d.username.trim()) continue;
      const r = await guard(() => adminApi.createUser({
        company_id: Number(companyId),
        username: d.username.trim(),
        display_name: d.display_name.trim(),
        role: d.role,
      }));
      if (r) out.push({ username: r.user.username, password: r.password });
    }
    setResults(out);
    setBusy(false);
    if (out.length) onDone?.();
  };

  if (!request.seat_plan?.length) {
    return <p style={{ color: 'var(--text-dim)', fontSize: 13 }}>این درخواست برنامه صندلی ندارد.</p>;
  }

  return (
    <div className="admin-edit-panel glass" style={{ padding: 14, marginTop: 12 }}>
      <div className="pform-section">صدور سریع کاربران از برنامه سازمانی</div>
      <div className="field" style={{ maxWidth: 360, marginBottom: 12 }}>
        <label>شرکت</label>
        <select className="adm-select" value={companyId} onChange={(e) => setCompanyId(e.target.value)}>
          <option value="">انتخاب شرکت…</option>
          {companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </div>
      {drafts.map((d, idx) => (
        <div key={d.key} className="wizard-user-row pform-grid">
          <div className="field">
            <label>نام کاربری</label>
            <input dir="ltr" value={d.username}
              onChange={(e) => setDrafts((prev) => prev.map((x, i) => i === idx ? { ...x, username: e.target.value } : x))} />
          </div>
          <div className="field">
            <label>نام نمایشی</label>
            <input value={d.display_name}
              onChange={(e) => setDrafts((prev) => prev.map((x, i) => i === idx ? { ...x, display_name: e.target.value } : x))} />
          </div>
          <div className="field">
            <label>نقش</label>
            <select className="adm-select" value={d.role}
              onChange={(e) => setDrafts((prev) => prev.map((x, i) => i === idx ? { ...x, role: e.target.value } : x))}>
              {ROLES.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
            </select>
          </div>
        </div>
      ))}
      <button className="btn btn-accent" disabled={busy || !companyId || !drafts.length} onClick={issue}>
        {busy ? 'در حال صدور…' : `صدور ${drafts.length} کاربر`}
      </button>
      {results.length > 0 && (
        <div style={{ marginTop: 12, fontSize: 13 }}>
          <b>رمزهای صادرشده:</b>
          {results.map((r) => (
            <div key={r.username} dir="ltr" style={{ fontFamily: 'monospace', marginTop: 4 }}>
              {r.username} / {r.password}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
function Requests({ guard, onCreateCompany }) {
  const [items, setItems] = useState([]);
  const [companies, setCompanies] = useState([]);
  const [wizardFor, setWizardFor] = useState(null);
  const load = useCallback(() => {
    guard(adminApi.requests).then((d) => d && setItems(d.items));
    guard(adminApi.companies).then((d) => d && setCompanies(d.items));
  }, [guard]);
  useEffect(load, [load]);

  const setStatus = async (id, status) => {
    await guard(() => adminApi.setRequestStatus(id, status));
    load();
  };

  return (
    <>
      <h1 className="page-title">درخواست‌های خرید و دمو</h1>
      <div className="page-sub">// PURCHASE_AND_DEMO_REQUESTS</div>
      <div style={{ display: 'grid', gap: 14, marginTop: 20 }}>
        {items.map((r) => {
          const st = REQ_STATUS[r.status] || REQ_STATUS.new;
          return (
            <div key={r.id} className="card glass" style={{ padding: 18 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
                <div>
                  <b>{r.company}</b>
                  <span style={{ color: 'var(--text-dim)', marginRight: 10 }}>
                    {r.brand} {r.model} {r.year}
                  </span>
                </div>
                <span className={`adm-status ${st.cls}`}>{st.label}</span>
              </div>
              <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap', marginTop: 10, fontSize: 13.5, color: 'var(--text-dim)' }}>
                <span>پرسنل: <b>{r.employees_count ?? '—'}</b></span>
                <span>کاربر درخواستی: <b>{r.seats_count ?? '—'}</b></span>
                <span>دمو: <b>{r.wants_demo ? 'بله' : 'خیر'}</b></span>
                <span>دستیار هوش مصنوعی: <b>{r.wants_ai_assistant ? 'بله' : 'خیر'}</b></span>
                <span dir="ltr">{r.mobile} / {r.landline}</span>
                <span>ثبت: {r.reg_no}</span>
                <span>{fmtDate(r.created_at)}</span>
              </div>
              <div style={{ marginTop: 8, fontSize: 13.5 }}>
                مستندات: {(r.documents || []).map((d) => DOCS.find((x) => x.id === d)?.label || d).join('، ') || '—'}
                {r.note && <div style={{ color: 'var(--text-dim)', marginTop: 4 }}>یادداشت: {r.note}</div>}
              </div>
              {(r.seat_plan?.length > 0) && (
                <div style={{ marginTop: 10 }}>
                  <div className="pform-section">برنامه صندلی سازمان</div>
                  <SeatPlanTable plan={r.seat_plan} />
                </div>
              )}
              <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
                {['reviewing', 'approved', 'rejected'].filter((s) => s !== r.status).map((s) => (
                  <button key={s} className="btn" onClick={() => setStatus(r.id, s)}>
                    {REQ_STATUS[s].label}
                  </button>
                ))}
                <button
                  className="btn btn-accent"
                  onClick={() => onCreateCompany?.({
                    name: r.company,
                    reg_no: r.reg_no,
                    landline: r.landline,
                    mobile: r.mobile,
                    employees_count: r.employees_count ?? '',
                    seats_count: r.seats_count ?? '',
                    is_demo: r.wants_demo,
                    ai_assistant_enabled: r.wants_ai_assistant,
                    note: `درخواست: ${r.brand} ${r.model} ${r.year}${r.note ? ` — ${r.note}` : ''}`,
                  })}
                >
                  تعریف شرکت از این درخواست
                </button>
                {r.seat_plan?.length > 0 && (
                  <button className="btn" onClick={() => setWizardFor(wizardFor === r.id ? null : r.id)}>
                    {wizardFor === r.id ? 'بستن صدور سریع' : 'صدور سریع کاربران'}
                  </button>
                )}
              </div>
              {wizardFor === r.id && (
                <IssueUsersWizard request={r} companies={companies} guard={guard} onDone={load} />
              )}
            </div>
          );
        })}
        {items.length === 0 && <div className="empty-state">درخواستی ثبت نشده است.</div>}
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Access editor — admin has full catalog; explicit doc selection (no empty=all).
function AccessEditor({ cars, value, onChange, copyFromUsers = [], onCopyFrom }) {
  const [q, setQ] = useState('');

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return cars;
    return cars.filter((c) => `${c.brand} ${c.model} ${c.year}`.toLowerCase().includes(needle));
  }, [cars, q]);

  const rowFor = (carId) => value.find((v) => v.car_id === carId);

  const toggleCar = (carId) => {
    if (rowFor(carId)) onChange(value.filter((v) => v.car_id !== carId));
    else onChange([...value, { car_id: carId, documents: [...ALL_DOC_IDS] }]);
  };

  const setDocs = (carId, documents) => {
    onChange(value.map((v) => (v.car_id === carId ? { ...v, documents } : v)));
  };

  const toggleDoc = (carId, doc) => {
    const row = rowFor(carId);
    if (!row) return;
    const has = row.documents.includes(doc);
    setDocs(carId, has ? row.documents.filter((d) => d !== doc) : [...row.documents, doc]);
  };

  const applyPreset = (carId, docs) => setDocs(carId, [...docs]);

  return (
    <div>
      <input
        className="access-editor-search"
        placeholder="جستجو برند / مدل / سال…"
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      {copyFromUsers?.length > 0 && onCopyFrom && (
        <div className="field" style={{ marginBottom: 12, maxWidth: 360 }}>
          <label>کپی دسترسی از کاربر دیگر</label>
          <select className="adm-select" defaultValue="" onChange={(e) => {
            const u = copyFromUsers.find((x) => String(x.id) === e.target.value);
            if (u) onCopyFrom(u.accesses.map((a) => ({ car_id: a.car.id, documents: a.documents?.length ? a.documents : [...ALL_DOC_IDS] })));
            e.target.value = '';
          }}>
            <option value="">انتخاب کاربر…</option>
            {copyFromUsers.map((u) => (
              <option key={u.id} value={u.id}>{u.username}{u.display_name ? ` (${u.display_name})` : ''}</option>
            ))}
          </select>
        </div>
      )}
      <div className="access-editor-presets">
        {ACCESS_PRESETS.map((p) => (
          <button key={p.id} type="button" className="btn" style={{ fontSize: 12 }}
            onClick={() => onChange(value.map((v) => ({ ...v, documents: [...p.docs] })))}
            disabled={!value.length}>
            {p.label} — همه خودروهای انتخاب‌شده
          </button>
        ))}
      </div>
      <div style={{ display: 'grid', gap: 8 }}>
        {filtered.map((c) => {
          const row = rowFor(c.id);
          const docs = row?.documents || [];
          const allOn = ALL_DOC_IDS.every((d) => docs.includes(d));
          return (
            <div key={c.id} className="glass" style={{ padding: '10px 14px', borderRadius: 10 }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
                <input type="checkbox" checked={!!row} onChange={() => toggleCar(c.id)} />
                <b>{c.brand} {c.model}</b>
                <span style={{ color: 'var(--text-dim)' }}>{c.year}</span>
              </label>
              {row && (
                <>
                  <div className="doc-chips" style={{ marginTop: 8 }}>
                    <button type="button"
                      className={`doc-chip${allOn ? ' active' : ''}`}
                      onClick={() => setDocs(c.id, allOn ? [] : [...ALL_DOC_IDS])}>
                      <span className="tick">✓</span>همه پکیج‌ها
                    </button>
                    {DOCS.map((d) => (
                      <button key={d.id} type="button"
                        className={`doc-chip${docs.includes(d.id) ? ' active' : ''}`}
                        onClick={() => toggleDoc(c.id, d.id)}>
                        <span className="tick">✓</span>{d.label}
                      </button>
                    ))}
                  </div>
                  <div className="access-editor-car-actions">
                    {ACCESS_PRESETS.map((p) => (
                      <button key={p.id} type="button" className="btn"
                        onClick={() => applyPreset(c.id, p.docs)}>{p.label}</button>
                    ))}
                    <button type="button" className="btn" onClick={() => setDocs(c.id, [])}>پاک کردن</button>
                  </div>
                </>
              )}
            </div>
          );
        })}
        {filtered.length === 0 && <div className="empty-state">خودرویی یافت نشد.</div>}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
function Companies({ guard, prefilled, onPrefillUsed }) {
  const [companies, setCompanies] = useState([]);
  const [cars, setCars] = useState([]);
  const [selected, setSelected] = useState(null);
  const [accessDraft, setAccessDraft] = useState([]);
  const [editForm, setEditForm] = useState(null);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ name: '', department_label: 'خدمات پس از فروش', reg_no: '', landline: '', mobile: '', employees_count: '', seats_count: '', is_demo: false, ai_assistant_enabled: false, note: '' });

  useEffect(() => {
    if (!prefilled) return;
    setForm((f) => ({ ...f, ...prefilled }));
    setCreating(true);
    setSelected(null);
    onPrefillUsed?.();
  }, [prefilled, onPrefillUsed]);

  const load = useCallback(() => {
    guard(adminApi.companies).then((d) => d && setCompanies(d.items));
    guard(adminApi.cars).then((d) => d && setCars(d.items));
  }, [guard]);
  useEffect(load, [load]);

  const openCompany = async (id) => {
    const d = await guard(() => adminApi.companyDetail(id));
    if (!d) return;
    const co = d.company;
    setSelected(co);
    setAccessDraft(co.accesses.map((a) => ({
      car_id: a.car.id,
      documents: a.documents?.length ? a.documents : [...ALL_DOC_IDS],
    })));
    setEditForm({
      name: co.name,
      department_label: co.department_label || 'خدمات پس از فروش',
      reg_no: co.reg_no || '',
      landline: co.landline || '',
      mobile: co.mobile || '',
      employees_count: co.employees_count ?? '',
      seats_count: co.seats_count ?? '',
      note: co.note || '',
    });
  };

  const saveCompanyDetails = async () => {
    if (!selected || !editForm) return;
    const payload = {
      ...editForm,
      employees_count: Number(editForm.employees_count) || null,
      seats_count: Number(editForm.seats_count) || null,
    };
    const d = await guard(() => adminApi.updateCompany(selected.id, payload));
    if (d) { setSelected(d.company); load(); }
  };

  const saveAccess = async () => {
    const d = await guard(() => adminApi.setCompanyAccess(selected.id, accessDraft));
    if (d) { setSelected(d.company); load(); }
  };

  const toggleField = async (field) => {
    const d = await guard(() => adminApi.updateCompany(selected.id, { [field]: !selected[field] }));
    if (d) { setSelected(d.company); load(); }
  };

  const create = async () => {
    const payload = {
      ...form,
      employees_count: Number(form.employees_count) || null,
      seats_count: Number(form.seats_count) || null,
    };
    const d = await guard(() => adminApi.createCompany(payload));
    if (d) {
      setCreating(false);
      setForm({ name: '', department_label: 'خدمات پس از فروش', reg_no: '', landline: '', mobile: '', employees_count: '', seats_count: '', is_demo: false, ai_assistant_enabled: false, note: '' });
      load();
      setSelected(d.company);
      setAccessDraft([]);
    }
  };

  return (
    <>
      <h1 className="page-title">شرکت‌ها و دسترسی‌ها</h1>
      <div className="page-sub">// COMPANIES_AND_ACCESS</div>

      <div style={{ display: 'flex', gap: 10, margin: '18px 0' }}>
        <button className="btn btn-accent" onClick={() => { setCreating((v) => !v); setSelected(null); }}>
          {creating ? 'بستن فرم' : '+ تعریف شرکت جدید'}
        </button>
      </div>

      {creating && (
        <div className="card glass" style={{ padding: 18, marginBottom: 20 }}>
          <div className="pform-grid">
            <div className="field"><label>نام شرکت *</label>
              <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
            <div className="field"><label>نام واحد سازمانی</label>
              <select className="adm-select" value={form.department_label} onChange={(e) => setForm({ ...form, department_label: e.target.value })}>
                {DEPARTMENT_PRESETS.map((d) => <option key={d} value={d}>{d}</option>)}
              </select>
            </div>
            <div className="field"><label>شماره ثبتی</label>
              <input dir="ltr" value={form.reg_no} onChange={(e) => setForm({ ...form, reg_no: e.target.value })} /></div>
            <div className="field"><label>تلفن ثابت</label>
              <input dir="ltr" value={form.landline} onChange={(e) => setForm({ ...form, landline: e.target.value })} /></div>
            <div className="field"><label>تلفن همراه</label>
              <input dir="ltr" value={form.mobile} onChange={(e) => setForm({ ...form, mobile: e.target.value })} /></div>
            <div className="field"><label>تعداد پرسنل</label>
              <input type="number" dir="ltr" value={form.employees_count} onChange={(e) => setForm({ ...form, employees_count: e.target.value })} /></div>
            <div className="field"><label>تعداد صندلی (کاربر)</label>
              <input type="number" dir="ltr" value={form.seats_count} onChange={(e) => setForm({ ...form, seats_count: e.target.value })} /></div>
          </div>
          <div className="doc-chips" style={{ margin: '10px 0' }}>
            <button type="button" className={`doc-chip${form.is_demo ? ' active' : ''}`} onClick={() => setForm({ ...form, is_demo: !form.is_demo })}>
              <span className="tick">✓</span>نسخه دمو
            </button>
            <button type="button" className={`doc-chip${form.ai_assistant_enabled ? ' active' : ''}`} onClick={() => setForm({ ...form, ai_assistant_enabled: !form.ai_assistant_enabled })}>
              <span className="tick">✓</span>دستیار هوش مصنوعی
            </button>
          </div>
          <button className="btn btn-accent" onClick={create}>ثبت شرکت</button>
        </div>
      )}

      <div style={{ display: 'grid', gap: 12 }}>
        {companies.map((c) => (
          <div key={c.id} className="card glass" style={{ padding: 16, cursor: 'pointer', outline: selected?.id === c.id ? '1px solid var(--accent)' : 'none' }}
            onClick={() => (selected?.id === c.id ? setSelected(null) : openCompany(c.id))}>
            <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
              <b>{c.name}</b>
              <div style={{ display: 'flex', gap: 8, fontSize: 12.5 }}>
                {c.is_demo && <span className="adm-status st-rev">دمو</span>}
                {c.ai_assistant_enabled && <span className="adm-status st-ok">AI</span>}
                <span className={`adm-status ${c.active ? 'st-ok' : 'st-no'}`}>{c.active ? 'فعال' : 'غیرفعال'}</span>
              </div>
            </div>
            <div style={{ fontSize: 13, color: 'var(--text-dim)', marginTop: 6 }}>
              واحد: {c.department_label || 'خدمات پس از فروش'} · کاربران: {c.users_count} · صندلی: {c.seats_count ?? '—'} · پرسنل: {c.employees_count ?? '—'}
            </div>

            {selected?.id === c.id && (
              <div style={{ marginTop: 16 }} onClick={(e) => e.stopPropagation()}>
                <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
                  <button className="btn" onClick={() => toggleField('active')}>{selected.active ? 'غیرفعال‌سازی شرکت' : 'فعال‌سازی شرکت'}</button>
                  <button className="btn" onClick={() => toggleField('ai_assistant_enabled')}>{selected.ai_assistant_enabled ? 'حذف دستیار AI' : 'فعال‌سازی دستیار AI'}</button>
                  <button className="btn" onClick={() => toggleField('is_demo')}>{selected.is_demo ? 'خروج از حالت دمو' : 'تبدیل به دمو'}</button>
                </div>
                {editForm && (
                  <div className="admin-edit-panel">
                    <div className="pform-section">ویرایش مشخصات شرکت</div>
                    <div className="pform-grid">
                      <div className="field"><label>نام شرکت</label>
                        <input value={editForm.name} onChange={(e) => setEditForm({ ...editForm, name: e.target.value })} /></div>
                      <div className="field"><label>واحد سازمانی</label>
                        <select className="adm-select" value={editForm.department_label}
                          onChange={(e) => setEditForm({ ...editForm, department_label: e.target.value })}>
                          {DEPARTMENT_PRESETS.map((d) => <option key={d} value={d}>{d}</option>)}
                        </select></div>
                      <div className="field"><label>شماره ثبتی</label>
                        <input dir="ltr" value={editForm.reg_no} onChange={(e) => setEditForm({ ...editForm, reg_no: e.target.value })} /></div>
                      <div className="field"><label>تلفن ثابت</label>
                        <input dir="ltr" value={editForm.landline} onChange={(e) => setEditForm({ ...editForm, landline: e.target.value })} /></div>
                      <div className="field"><label>تلفن همراه</label>
                        <input dir="ltr" value={editForm.mobile} onChange={(e) => setEditForm({ ...editForm, mobile: e.target.value })} /></div>
                      <div className="field"><label>تعداد پرسنل</label>
                        <input type="number" dir="ltr" value={editForm.employees_count}
                          onChange={(e) => setEditForm({ ...editForm, employees_count: e.target.value })} /></div>
                      <div className="field"><label>تعداد صندلی</label>
                        <input type="number" dir="ltr" value={editForm.seats_count}
                          onChange={(e) => setEditForm({ ...editForm, seats_count: e.target.value })} /></div>
                    </div>
                    <div className="field"><label>یادداشت</label>
                      <textarea value={editForm.note} onChange={(e) => setEditForm({ ...editForm, note: e.target.value })} /></div>
                    <button className="btn btn-accent" style={{ marginTop: 8 }} onClick={saveCompanyDetails}>ذخیره مشخصات شرکت</button>
                  </div>
                )}
                <div className="pform-section">خودروها و لایه‌های خریداری‌شده</div>
                <AccessEditor cars={cars} value={accessDraft} onChange={setAccessDraft} />
                <button className="btn btn-accent" style={{ marginTop: 12 }} onClick={saveAccess}>ذخیره دسترسی شرکت</button>
              </div>
            )}
          </div>
        ))}
        {companies.length === 0 && <div className="empty-state">هنوز شرکتی تعریف نشده است.</div>}
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
function Users({ guard }) {
  const [users, setUsers] = useState([]);
  const [companies, setCompanies] = useState([]);
  const [cars, setCars] = useState([]);
  const [companyFilter, setCompanyFilter] = useState('');
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ company_id: '', username: '', display_name: '', role: 'after_sales_specialist', ai_assistant_enabled: false, access_expires_at: '' });
  const [issued, setIssued] = useState(null);
  const [editingAccess, setEditingAccess] = useState(null);
  const [editingProfile, setEditingProfile] = useState(null);
  const [profileDraft, setProfileDraft] = useState(null);
  const [accessDraft, setAccessDraft] = useState([]);

  const load = useCallback(() => {
    guard(() => adminApi.users(companyFilter || undefined)).then((d) => d && setUsers(d.items));
    guard(adminApi.companies).then((d) => d && setCompanies(d.items));
    guard(adminApi.cars).then((d) => d && setCars(d.items));
  }, [guard, companyFilter]);
  useEffect(load, [load]);

  const create = async () => {
    const d = await guard(() => adminApi.createUser(form));
    if (d) {
      setIssued({ username: d.user.username, password: d.password });
      setCreating(false);
      setForm({ company_id: '', username: '', display_name: '', role: 'after_sales_specialist', ai_assistant_enabled: false, access_expires_at: '' });
      load();
    }
  };

  const openAccess = async (u) => {
    setAccessDraft(u.accesses.map((a) => ({
      car_id: a.car.id,
      documents: a.documents?.length ? a.documents : [...ALL_DOC_IDS],
    })));
    setEditingAccess(u.id);
    setEditingProfile(null);
  };

  const openProfile = (u) => {
    setEditingProfile(u.id);
    setEditingAccess(null);
    setProfileDraft({
      role: u.role,
      display_name: u.display_name || '',
      access_expires_at: u.access_expires_at
        ? new Date(u.access_expires_at).toISOString().slice(0, 16)
        : '',
    });
  };

  const saveProfile = async (id) => {
    if (!profileDraft) return;
    const payload = {
      role: profileDraft.role,
      display_name: profileDraft.display_name,
      access_expires_at: profileDraft.access_expires_at
        ? new Date(profileDraft.access_expires_at).toISOString()
        : null,
    };
    const d = await guard(() => adminApi.updateUser(id, payload));
    if (d) { setEditingProfile(null); load(); }
  };

  const saveAccess = async () => {
    const d = await guard(() => adminApi.setUserAccess(editingAccess, accessDraft, true));
    if (d) { setEditingAccess(null); load(); }
  };

  const patch = async (id, payload) => {
    if (payload.delete) {
      await guard(() => adminApi.deleteUser(id));
      load();
      return;
    }
    const d = await guard(() => adminApi.updateUser(id, payload));
    if (d?.password) setIssued({ username: d.user.username, password: d.password });
    load();
  };

  return (
    <>
      <h1 className="page-title">کاربران شرکت‌ها</h1>
      <div className="page-sub">// COMPANY_USERS_AND_GRANTS</div>

      <div style={{ display: 'flex', gap: 10, margin: '18px 0', flexWrap: 'wrap', alignItems: 'center' }}>
        <button className="btn btn-accent" onClick={() => setCreating((v) => !v)}>
          {creating ? 'بستن فرم' : '+ صدور کاربر جدید'}
        </button>
        <select className="adm-select" value={companyFilter} onChange={(e) => setCompanyFilter(e.target.value)}>
          <option value="">همه شرکت‌ها</option>
          {companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </div>

      {issued && (
        <div className="card glass" style={{ padding: 16, marginBottom: 16, borderColor: 'var(--accent)' }}>
          <b>اطلاعات ورود صادر شد — همین حالا به شرکت تحویل دهید (دیگر نمایش داده نمی‌شود):</b>
          <div dir="ltr" style={{ fontFamily: 'monospace', marginTop: 8 }}>
            user: {issued.username} &nbsp; pass: {issued.password}
          </div>
          <button className="btn" style={{ marginTop: 10 }} onClick={() => setIssued(null)}>باشه، ذخیره کردم</button>
        </div>
      )}

      {creating && (
        <div className="card glass" style={{ padding: 18, marginBottom: 20 }}>
          <div className="pform-grid">
            <div className="field"><label>شرکت *</label>
              <select className="adm-select" value={form.company_id} onChange={(e) => setForm({ ...form, company_id: e.target.value })}>
                <option value="">انتخاب شرکت…</option>
                {companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>
            <div className="field"><label>نقش سازمانی *</label>
              <select className="adm-select" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
                {ROLES.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
              </select>
            </div>
            <div className="field"><label>نام کاربری *</label>
              <input dir="ltr" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} placeholder="e.g. gostar_manager_01" /></div>
            <div className="field"><label>نام نمایشی</label>
              <input value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} /></div>
            <div className="field"><label>انقضای دسترسی (اختیاری)</label>
              <input type="datetime-local" dir="ltr" value={form.access_expires_at}
                onChange={(e) => setForm({ ...form, access_expires_at: e.target.value ? new Date(e.target.value).toISOString() : '' })} /></div>
          </div>
          <div className="doc-chips" style={{ margin: '10px 0' }}>
            <button type="button" className={`doc-chip${form.ai_assistant_enabled ? ' active' : ''}`}
              onClick={() => setForm({ ...form, ai_assistant_enabled: !form.ai_assistant_enabled })}>
              <span className="tick">✓</span>دستیار AI (نیازمند پکیج راهنمای تعمیرات)
            </button>
          </div>
          <button className="btn btn-accent" onClick={create} disabled={!form.company_id || !form.username}>
            صدور کاربر (رمز خودکار)
          </button>
        </div>
      )}

      <div style={{ display: 'grid', gap: 12 }}>
        {users.map((u) => (
          <div key={u.id} className="card glass" style={{ padding: 16 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
              <div>
                <b dir="ltr">{u.username}</b>
                {u.display_name && <span style={{ marginRight: 8 }}>({u.display_name})</span>}
                <span style={{ color: 'var(--text-dim)', marginRight: 10 }}>{u.company} · {u.role_label}</span>
              </div>
              <div style={{ display: 'flex', gap: 8, fontSize: 12.5 }}>
                {u.ai_eligible && <span className="adm-status st-ok">AI فعال</span>}
                {u.ai_assistant_enabled && !u.ai_eligible && <span className="adm-status st-rev">AI (بدون مجوز)</span>}
                {u.locked && <span className="adm-status st-no">قفل</span>}
                <span className={`adm-status ${u.active ? 'st-ok' : 'st-no'}`}>{u.active ? 'فعال' : 'غیرفعال'}</span>
              </div>
            </div>
            <div style={{ fontSize: 13, color: 'var(--text-dim)', marginTop: 6 }}>
              پکیج‌ها: {(u.packages || []).map(packageLabel).join('، ') || '—'}
              · دسترسی خودرو: {u.accesses.length ? u.accesses.map((a) => `${a.car.brand} ${a.car.model}`).join('، ') : 'هیچ'}
              {u.access_expires_at && <> · انقضا: {fmtDate(u.access_expires_at)}</>}
              {u.last_login_at && <> · آخرین ورود: {fmtDate(u.last_login_at)}</>}
            </div>
            <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
              <button className="btn" onClick={() => openProfile(u)}>ویرایش پروفایل</button>
              <button className="btn" onClick={() => openAccess(u)}>ویرایش دسترسی</button>
              <button className="btn" onClick={() => patch(u.id, { active: !u.active })}>{u.active ? 'غیرفعال' : 'فعال'}</button>
              <button className="btn" onClick={() => patch(u.id, { locked: !u.locked })}>{u.locked ? 'باز کردن قفل' : 'قفل حساب'}</button>
              <button className="btn" onClick={() => patch(u.id, { reset_password: true })}>بازنشانی رمز</button>
              <button className="btn" onClick={() => patch(u.id, { ai_assistant_enabled: !u.ai_assistant_enabled })}>
                {u.ai_assistant_enabled ? 'حذف AI' : 'فعال‌سازی AI'}
              </button>
              <button className="btn" style={{ color: '#e5484d' }} onClick={() => {
                if (window.confirm(`حذف کاربر ${u.username}؟`)) patch(u.id, { delete: true });
              }}>حذف</button>
            </div>

            {editingProfile === u.id && profileDraft && (
              <div className="admin-edit-panel">
                <div className="pform-section">ویرایش پروفایل کاربر</div>
                <div className="pform-grid">
                  <div className="field"><label>نقش سازمانی</label>
                    <select className="adm-select" value={profileDraft.role}
                      onChange={(e) => setProfileDraft({ ...profileDraft, role: e.target.value })}>
                      {ROLES.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
                    </select></div>
                  <div className="field"><label>نام نمایشی</label>
                    <input value={profileDraft.display_name}
                      onChange={(e) => setProfileDraft({ ...profileDraft, display_name: e.target.value })} /></div>
                  <div className="field"><label>انقضای دسترسی</label>
                    <input type="datetime-local" dir="ltr" value={profileDraft.access_expires_at}
                      onChange={(e) => setProfileDraft({ ...profileDraft, access_expires_at: e.target.value })} /></div>
                </div>
                <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                  <button className="btn btn-accent" onClick={() => saveProfile(u.id)}>ذخیره</button>
                  <button className="btn" onClick={() => setEditingProfile(null)}>انصراف</button>
                </div>
              </div>
            )}

            {editingAccess === u.id && (
              <div className="admin-edit-panel">
                <div className="pform-section">پکیج‌ها و خودروها — دسترسی کامل ادمین</div>
                <AccessEditor
                  cars={cars}
                  value={accessDraft}
                  onChange={setAccessDraft}
                  copyFromUsers={users.filter((x) => x.company_id === u.company_id && x.id !== u.id)}
                  onCopyFrom={setAccessDraft}
                />
                <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
                  <button className="btn btn-accent" onClick={saveAccess}>ذخیره</button>
                  <button className="btn" onClick={() => setEditingAccess(null)}>انصراف</button>
                </div>
              </div>
            )}
          </div>
        ))}
        {users.length === 0 && <div className="empty-state">کاربری صادر نشده است.</div>}
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
function Activity({ guard }) {
  const [items, setItems] = useState([]);
  const [companies, setCompanies] = useState([]);
  const [companyFilter, setCompanyFilter] = useState('');

  useEffect(() => {
    guard(adminApi.companies).then((d) => d && setCompanies(d.items));
  }, [guard]);
  useEffect(() => {
    const params = companyFilter ? { company_id: companyFilter } : {};
    guard(() => adminApi.activity(params)).then((d) => d && setItems(d.items));
  }, [guard, companyFilter]);

  return (
    <>
      <h1 className="page-title">گزارش فعالیت کاربران</h1>
      <div className="page-sub">// USER_ACTIVITY_REPORT</div>
      <div style={{ margin: '18px 0' }}>
        <select className="adm-select" value={companyFilter} onChange={(e) => setCompanyFilter(e.target.value)}>
          <option value="">همه شرکت‌ها</option>
          {companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </div>
      <div className="card glass" style={{ padding: 0, overflow: 'hidden' }}>
        <table className="adm-table">
          <thead>
            <tr><th>زمان</th><th>کاربر</th><th>شرکت</th><th>نقش</th><th>عملیات</th><th>حوزه</th><th>جزئیات</th></tr>
          </thead>
          <tbody>
            {items.map((a) => (
              <tr key={a.id}>
                <td>{fmtDate(a.created_at)}</td>
                <td dir="ltr">{a.user}</td>
                <td>{a.company}</td>
                <td>{a.role_label}</td>
                <td>{a.action}</td>
                <td>{a.category_label || '—'}</td>
                <td>{a.detail}</td>
              </tr>
            ))}
            {items.length === 0 && (
              <tr><td colSpan={7} style={{ textAlign: 'center', color: 'var(--text-dim)' }}>فعالیتی ثبت نشده است.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Platform-wide usage analytics (cross-company). Same visual language as the
// company manager's dashboard, but aggregated across every company.
const AN_RANGES = [{ id: '7', label: '۷ روز' }, { id: '30', label: '۳۰ روز' }, { id: '90', label: '۹۰ روز' }];

function PlatformAnalytics({ guard }) {
  const [data, setData] = useState(null);
  const [range, setRange] = useState('30');

  useEffect(() => {
    guard(() => adminApi.analytics({ range })).then((d) => d && setData(d));
  }, [guard, range]);

  if (!data) return <div className="empty-state">در حال بارگذاری تحلیل‌ها…</div>;
  const maxCat = Math.max(1, ...data.categories.map((c) => c.count));
  const maxCompany = Math.max(1, ...data.companies_usage.map((c) => c.events));
  const maxUser = Math.max(1, ...data.top_users.map((u) => u.events));

  return (
    <>
      <h1 className="page-title">تحلیل استفاده کل پلتفرم</h1>
      <div className="page-sub">// PLATFORM_ANALYTICS</div>

      <div className="range-chips" style={{ margin: '16px 0' }}>
        {AN_RANGES.map((r) => (
          <button key={r.id} className={`range-chip${range === r.id ? ' active' : ''}`} onClick={() => setRange(r.id)}>{r.label}</button>
        ))}
      </div>

      <div className="an-kpis">
        <div className="an-kpi glass"><div className="an-kpi-ico"><Icon name="chart" /></div><div><div className="an-kpi-val">{(data.totals.events || 0).toLocaleString('fa-IR')}</div><div className="an-kpi-label">کل فعالیت‌ها</div></div></div>
        <div className="an-kpi glass"><div className="an-kpi-ico"><Icon name="building" /></div><div><div className="an-kpi-val">{(data.totals.companies || 0).toLocaleString('fa-IR')}</div><div className="an-kpi-label">شرکت‌ها</div></div></div>
        <div className="an-kpi glass"><div className="an-kpi-ico"><Icon name="users" /></div><div><div className="an-kpi-val">{(data.totals.active_users || 0).toLocaleString('fa-IR')}</div><div className="an-kpi-label">کاربران فعال</div></div></div>
      </div>

      <div className="an-grid">
        <section className="an-card glass">
          <div className="an-card-head"><h3><Icon name="chart" size={16} /> استفاده به تفکیک حوزه فنی</h3></div>
          <div className="bars">
            {data.categories.map((c) => (
              <div className="bar-row" key={c.id} title={`${c.label}: ${c.count}`}>
                <span className="bar-label">{c.label}</span>
                <div className="bar-track"><div className="bar-fill" style={{ width: `${(c.count / maxCat) * 100}%` }} /></div>
                <span className="bar-val">{c.count.toLocaleString('fa-IR')}</span>
              </div>
            ))}
          </div>
        </section>

        <section className="an-card glass">
          <div className="an-card-head"><h3><Icon name="building" size={16} /> استفاده به تفکیک شرکت</h3></div>
          <div className="bars">
            {data.companies_usage.slice(0, 12).map((c) => (
              <div className="bar-row" key={c.company_id} title={`${c.company}: ${c.events}`}>
                <span className="bar-label">{c.company}</span>
                <div className="bar-track"><div className="bar-fill alt" style={{ width: `${(c.events / maxCompany) * 100}%` }} /></div>
                <span className="bar-val">{c.events.toLocaleString('fa-IR')}</span>
              </div>
            ))}
            {data.companies_usage.length === 0 && <div className="muted">داده‌ای ثبت نشده است.</div>}
          </div>
        </section>

        <section className="an-card glass an-span">
          <div className="an-card-head"><h3><Icon name="users" size={16} /> فعال‌ترین کاربران (همه شرکت‌ها)</h3></div>
          <div className="member-usage">
            {data.top_users.map((u) => (
              <div className="mu-row" key={u.user_id} style={{ cursor: 'default' }}>
                <span className="mu-name">{u.user}<small>{u.company}</small></span>
                <div className="mu-track"><div className="mu-fill" style={{ width: `${(u.events / maxUser) * 100}%` }} /></div>
                <span className="mu-val">{u.events.toLocaleString('fa-IR')}</span>
              </div>
            ))}
            {data.top_users.length === 0 && <div className="muted">داده‌ای ثبت نشده است.</div>}
          </div>
        </section>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Data quality — which vehicles are complete, which have missing sections,
// duplicates, and which pipeline processes are still pending per vehicle.
// ---------------------------------------------------------------------------
const DQ_STATUS = {
  complete: { label: 'کامل', cls: 'st-ok' },
  incomplete: { label: 'ناقص', cls: 'st-rev' },
  duplicate: { label: 'تکراری', cls: 'st-no' },
  corrupt: { label: 'خراب', cls: 'st-no' },
};

function DataQuality({ guard }) {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [expanded, setExpanded] = useState(null);
  const [filter, setFilter] = useState('all');

  const load = useCallback(() => {
    guard(adminApi.dataQuality).then((d) => d && setData(d));
  }, [guard]);
  useEffect(() => { load(); }, [load]);

  // While a refresh runs, poll until it lands.
  useEffect(() => {
    if (!data?.running) return undefined;
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [data?.running, load]);

  const refresh = async (fix) => {
    setBusy(true);
    try {
      await guard(() => adminApi.dataQualityRefresh(fix));
      setData((d) => ({ ...(d || {}), running: true }));
    } finally { setBusy(false); }
  };

  const report = data?.report;
  const vehicles = useMemo(() => {
    const items = report?.vehicles || [];
    if (filter === 'all') return items;
    if (filter === 'issues') return items.filter((v) => v.status !== 'complete');
    return items.filter((v) => v.status === filter);
  }, [report, filter]);

  const s = report?.summary;
  return (
    <>
      <h1 className="page-title">سلامت داده‌های خودروها</h1>
      <div className="page-sub">// DATA_QUALITY — کامل بودن بخش‌ها، تکراری‌ها و فرایندهای درانتظار</div>

      <div style={{ display: 'flex', gap: 10, margin: '16px 0', flexWrap: 'wrap' }}>
        <button className="btn btn-accent" disabled={busy || data?.running} onClick={() => refresh(false)}>
          <Icon name="refresh" size={14} /> {data?.running ? 'در حال بررسی…' : 'بررسی مجدد انبار داده'}
        </button>
        <button
          className="btn"
          disabled={busy || data?.running}
          onClick={() => refresh(true)}
          title="موارد امن به‌صورت خودکار اصلاح می‌شوند (فایل‌های خراب و نسخه‌های تکراری قرنطینه می‌شوند)"
        >
          بررسی + اصلاح خودکار
        </button>
        {report?.finished_at && (
          <span style={{ color: 'var(--text-dim)', fontSize: 13, alignSelf: 'center' }}>
            آخرین بررسی: {fmtDate(report.finished_at)}
          </span>
        )}
      </div>

      {!report && !data?.running && (
        <div className="empty-state">هنوز بررسی‌ای انجام نشده است — روی «بررسی مجدد» بزنید.</div>
      )}
      {data?.running && !report && <div className="empty-state">در حال بررسی انبار داده…</div>}

      {s && (
        <div className="grid3" style={{ marginBottom: 18 }}>
          <div className="card glass"><div className="num">{s.total_dbs}</div><h3>کل خودروها (فایل داده)</h3></div>
          <div className="card glass"><div className="num" style={{ color: '#22c55e' }}>{s.complete}</div><h3>کامل</h3></div>
          <div className="card glass"><div className="num" style={{ color: '#eab308' }}>{s.incomplete}</div><h3>ناقص</h3></div>
          <div className="card glass"><div className="num" style={{ color: '#ef4444' }}>{(s.duplicates || []).length}</div><h3>تکراری</h3></div>
          <div className="card glass"><div className="num" style={{ color: '#ef4444' }}>{s.corrupt}</div><h3>فایل خراب</h3></div>
          <div className="card glass"><div className="num">{s.rag_indexed}/{s.total_dbs}</div><h3>ایندکس هوشمند (RAG)</h3></div>
        </div>
      )}

      {(s?.duplicates || []).length > 0 && (
        <div className="card glass" style={{ marginBottom: 18 }}>
          <h3 style={{ marginTop: 0 }}>خودروهای تکراری شناسایی‌شده</h3>
          {s.duplicates.map((d, i) => (
            <div key={i} style={{ fontSize: 14, marginBottom: 6 }} dir="ltr">
              <b>{d.remove.join(', ')}</b>
              {d.keep ? <> ← نسخهٔ اصلی: <b>{d.keep}</b> {d.fingerprint ? '(محتوای یکسان تأیید شد)' : ''}</> : ' (نسخهٔ اصلی یافت نشد)'}
              {d.note ? <span style={{ color: 'var(--text-dim)' }}> — {d.note}</span> : null}
            </div>
          ))}
          <p style={{ color: 'var(--text-dim)', fontSize: 13, marginBottom: 0 }}>
            «بررسی + اصلاح خودکار» نسخهٔ تکراری را با نسخهٔ اصلی ادغام و فایل آن را قرنطینه می‌کند (حذف نمی‌شود).
          </p>
        </div>
      )}

      {report && (
        <>
          <div style={{ display: 'flex', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
            {[['all', 'همه'], ['issues', 'دارای مشکل'], ['complete', 'کامل'], ['incomplete', 'ناقص'], ['corrupt', 'خراب'], ['duplicate', 'تکراری']].map(([id, label]) => (
              <button
                key={id}
                className={`btn${filter === id ? ' btn-accent' : ''}`}
                style={{ padding: '4px 12px', fontSize: 13 }}
                onClick={() => setFilter(id)}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="card glass" style={{ padding: 0, overflow: 'hidden' }}>
            <table className="adm-table">
              <thead>
                <tr><th>خودرو</th><th>وضعیت</th><th>بخش‌ها</th><th>حجم</th><th>کاتالوگ</th><th>RAG</th><th>عیب‌یاب</th><th>تصاویر</th><th>درانتظار</th></tr>
              </thead>
              <tbody>
                {vehicles.map((v) => {
                  const st = DQ_STATUS[v.status] || { label: v.status, cls: '' };
                  const issues = (v.missing_sections || []).length + (v.empty_sections || []).length;
                  const isOpen = expanded === v.stem;
                  return (
                    <Fragment key={v.stem}>
                      <tr onClick={() => setExpanded(isOpen ? null : v.stem)} style={{ cursor: 'pointer' }}>
                        <td dir="ltr">{v.stem}</td>
                        <td><span className={`st-badge ${st.cls}`}>{st.label}</span></td>
                        <td>{(v.sections || []).length}{issues > 0 ? ` (${issues} مشکل)` : ''}</td>
                        <td dir="ltr">{v.size_mb ? `${Math.round(v.size_mb)}MB` : '—'}</td>
                        <td>{v.cataloged ? '✓' : '✗'}</td>
                        <td>{v.rag_indexed ? '✓' : '✗'}</td>
                        <td>{v.diag_indexed ? '✓' : '✗'}</td>
                        <td>{v.static_assets ? '✓' : '✗'}</td>
                        <td style={{ fontSize: 12, color: 'var(--text-dim)' }} dir="ltr">{(v.pending_processes || []).join('، ') || '—'}</td>
                      </tr>
                      {isOpen && (
                        <tr>
                          <td colSpan={9}>
                            {v.error && <div style={{ color: '#ef4444', marginBottom: 8 }} dir="ltr">error: {v.error}</div>}
                            {(v.missing_sections || []).length > 0 && (
                              <div style={{ marginBottom: 6 }}>بخش‌های غایب: <b dir="ltr">{v.missing_sections.join(', ')}</b></div>
                            )}
                            {(v.empty_sections || []).length > 0 && (
                              <div style={{ marginBottom: 6 }}>بخش‌های خالی: <b dir="ltr">{v.empty_sections.join(', ')}</b></div>
                            )}
                            {(v.shared_content_with || []).length > 0 && (
                              <div style={{ marginBottom: 6, color: 'var(--text-dim)' }}>
                                محتوای یکسان با (تریم‌های هم‌خانواده — طبیعی): <span dir="ltr">{v.shared_content_with.join(', ')}</span>
                              </div>
                            )}
                            <table className="adm-table" style={{ fontSize: 13 }}>
                              <thead><tr><th>بخش</th><th>تعداد صفحات</th><th>صفحات دارای محتوا</th><th>حجم محتوا</th></tr></thead>
                              <tbody>
                                {(v.sections || []).map((sec) => (
                                  <tr key={sec.normalized}>
                                    <td dir="ltr">{sec.title}</td>
                                    <td>{sec.nodes}</td>
                                    <td style={sec.content_leaves === 0 ? { color: '#ef4444' } : undefined}>{sec.content_leaves}</td>
                                    <td dir="ltr">{sec.mb}MB</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
                {vehicles.length === 0 && (
                  <tr><td colSpan={9} style={{ textAlign: 'center', color: 'var(--text-dim)' }}>موردی یافت نشد.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// System monitoring — live server health, alerts, and traffic analytics.
// ---------------------------------------------------------------------------
const SEV = {
  critical: { label: 'بحرانی', color: '#ef4444' },
  warning: { label: 'هشدار', color: '#eab308' },
  info: { label: 'اطلاع', color: '#3b82f6' },
};

function SystemMonitor({ guard }) {
  const [sys, setSys] = useState(null);
  const [traffic, setTraffic] = useState(null);
  const [range, setRange] = useState(7);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    guard(adminApi.system).then((d) => d && setSys(d));
  }, [guard]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    guard(() => adminApi.traffic(range)).then((d) => d && setTraffic(d));
  }, [guard, range]);

  const checkNow = async () => {
    setBusy(true);
    try { await guard(adminApi.checkAlerts); load(); } finally { setBusy(false); }
  };

  const snap = sys?.snapshot;
  const fmtUptime = (sec) => {
    if (!sec && sec !== 0) return '—';
    const d = Math.floor(sec / 86400);
    const h = Math.floor((sec % 86400) / 3600);
    const m = Math.floor((sec % 3600) / 60);
    if (d > 0) return `${d}روز ${h}ساعت`;
    if (h > 0) return `${h}ساعت ${m}دقیقه`;
    return `${m}دقیقه`;
  };
  const maxDay = Math.max(1, ...((traffic?.series || []).map((x) => x.requests || 0)));

  return (
    <>
      <h1 className="page-title">پایش سیستم و ترافیک</h1>
      <div className="page-sub">// SYSTEM_MONITOR — سلامت سرور، هشدارها و آمار بازدید</div>

      <div style={{ display: 'flex', gap: 10, margin: '16px 0' }}>
        <button className="btn" onClick={load}><Icon name="refresh" size={14} /> به‌روزرسانی</button>
        <button className="btn" disabled={busy} onClick={checkNow}>ارزیابی هشدارها الان</button>
      </div>

      {!snap ? <div className="empty-state">در حال بارگذاری…</div> : (
        <div className="grid3" style={{ marginBottom: 18 }}>
          <div className="card glass">
            <div className="num" style={{ color: snap.disk.used_pct > 85 ? '#ef4444' : undefined }}>{snap.disk.used_pct}%</div>
            <h3>دیسک ({snap.disk.free_gb}GB آزاد از {snap.disk.total_gb}GB)</h3>
          </div>
          <div className="card glass">
            <div className="num" style={{ color: (snap.memory.used_pct || 0) > 90 ? '#ef4444' : undefined }}>{snap.memory.used_pct ?? '—'}%</div>
            <h3>حافظه ({snap.memory.available_mb ? Math.round(snap.memory.available_mb / 1024) : '—'}GB آزاد)</h3>
          </div>
          <div className="card glass">
            <div className="num">{snap.load_avg ? snap.load_avg[0].toFixed(1) : '—'}</div>
            <h3>بار پردازنده ({snap.cpu_count} هسته)</h3>
          </div>
          <div className="card glass"><div className="num">{fmtUptime(snap.uptime_s)}</div><h3>مدت فعال بودن سرویس</h3></div>
          <div className="card glass">
            <div className="num" style={{ color: snap.db_ok ? '#22c55e' : '#ef4444' }}>{snap.db_ok ? '✓' : '✗'}</div>
            <h3>پایگاه‌داده اصلی ({snap.main_db_mb}MB)</h3>
          </div>
          <div className="card glass">
            <div className="num" style={{ color: snap.rag_index.present ? '#22c55e' : '#ef4444' }}>{snap.rag_index.present ? '✓' : '✗'}</div>
            <h3>ایندکس هوشمند ({snap.rag_index.size_mb}MB)</h3>
          </div>
        </div>
      )}

      <div className="card glass" style={{ marginBottom: 18 }}>
        <h3 style={{ marginTop: 0 }}><Icon name="bell" size={16} /> هشدارهای فعال</h3>
        {(sys?.alerts_open || []).length === 0 && <div className="muted">هشداری فعال نیست — همه‌چیز سالم است. ✓</div>}
        {(sys?.alerts_open || []).map((a) => {
          const sev = SEV[a.severity] || SEV.info;
          return (
            <div key={a.id} style={{ display: 'flex', gap: 10, alignItems: 'baseline', marginBottom: 8 }}>
              <span className="st-badge" style={{ background: `${sev.color}22`, color: sev.color }}>{sev.label}</span>
              <span>{a.message}</span>
              <small style={{ color: 'var(--text-dim)' }}>{fmtDate(a.last_seen)}</small>
            </div>
          );
        })}
      </div>

      <div style={{ display: 'flex', gap: 8, marginBottom: 10, alignItems: 'center' }}>
        <b>آمار ترافیک</b>
        {[7, 30, 90].map((r) => (
          <button
            key={r}
            className={`btn${range === r ? ' btn-accent' : ''}`}
            style={{ padding: '4px 12px', fontSize: 13 }}
            onClick={() => setRange(r)}
          >
            {r} روز
          </button>
        ))}
      </div>

      {traffic && (
        <>
          <div className="grid3" style={{ marginBottom: 18 }}>
            <div className="card glass"><div className="num">{(traffic.totals.requests || 0).toLocaleString('fa-IR')}</div><h3>کل درخواست‌ها</h3></div>
            <div className="card glass"><div className="num">{(traffic.totals.unique_visitors || 0).toLocaleString('fa-IR')}</div><h3>بازدیدکنندگان یکتا</h3></div>
            <div className="card glass"><div className="num">{traffic.totals.avg_ms}ms</div><h3>میانگین زمان پاسخ</h3></div>
            <div className="card glass"><div className="num" style={{ color: (traffic.totals.errors_5xx || 0) > 0 ? '#ef4444' : undefined }}>{traffic.totals.errors_5xx || 0}</div><h3>خطاهای سرور (5xx)</h3></div>
          </div>

          <div className="card glass" style={{ marginBottom: 18 }}>
            <h3 style={{ marginTop: 0 }}>روند روزانه درخواست‌ها</h3>
            <div style={{ display: 'flex', alignItems: 'flex-end', gap: 4, height: 120, direction: 'ltr' }}>
              {(traffic.series || []).map((d) => (
                <div
                  key={d.date}
                  title={`${d.date}: ${d.requests} درخواست، ${d.unique_visitors} بازدیدکننده`}
                  style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'flex-end', height: '100%' }}
                >
                  <div style={{ background: 'var(--acc1, #6366f1)', opacity: 0.85, borderRadius: 3, height: `${Math.max(3, ((d.requests || 0) / maxDay) * 100)}%` }} />
                </div>
              ))}
              {(traffic.series || []).length === 0 && <div className="muted">داده‌ای ثبت نشده است.</div>}
            </div>
          </div>

          <div className="card glass" style={{ padding: 0, overflow: 'hidden', marginBottom: 18 }}>
            <table className="adm-table">
              <thead><tr><th>بخش</th><th>درخواست‌ها</th><th>میانگین پاسخ</th><th>بیشینه</th><th>4xx</th><th>5xx</th></tr></thead>
              <tbody>
                {(traffic.endpoints || []).map((e) => (
                  <tr key={e.endpoint}>
                    <td dir="ltr">{e.endpoint}</td>
                    <td>{(e.requests || 0).toLocaleString('fa-IR')}</td>
                    <td dir="ltr">{e.avg_ms}ms</td>
                    <td dir="ltr">{e.max_ms}ms</td>
                    <td>{e.errors_4xx || 0}</td>
                    <td style={(e.errors_5xx || 0) > 0 ? { color: '#ef4444' } : undefined}>{e.errors_5xx || 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="card glass">
            <h3 style={{ marginTop: 0 }}>استفاده از امکانات (کاربران واردشده)</h3>
            {Object.entries(traffic.feature_usage || {}).map(([action, n]) => (
              <div key={action} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 14, marginBottom: 4 }}>
                <span dir="ltr">{action}</span><b>{n.toLocaleString('fa-IR')}</b>
              </div>
            ))}
            {Object.keys(traffic.feature_usage || {}).length === 0 && <div className="muted">داده‌ای ثبت نشده است.</div>}
          </div>
        </>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Data processing pipeline — one-button server-side processing with live
// progress, scheduling, auto-mode and resume. The worker runs detached on the
// server: closing this page never interrupts it.
// ---------------------------------------------------------------------------
const JOB_STATUS = {
  pending: { label: 'در صف اجرا', color: '#3b82f6' },
  scheduled: { label: 'زمان‌بندی‌شده', color: '#3b82f6' },
  running: { label: 'در حال اجرا', color: '#22c55e' },
  paused: { label: 'متوقف‌شده (قابل ادامه)', color: '#eab308' },
  stalled: { label: 'قطع‌شده (قابل ادامه)', color: '#eab308' },
  done: { label: 'کامل شد', color: '#22c55e' },
  failed: { label: 'با خطا تمام شد', color: '#ef4444' },
  canceled: { label: 'لغو شد', color: '#9ca3af' },
};
const STAGE_STATUS = {
  pending: 'در انتظار', running: 'در حال اجرا', done: 'انجام شد',
  skipped: 'لازم نبود', failed: 'خطا',
};

function fmtDur(sec) {
  if (sec == null || Number.isNaN(sec)) return '—';
  const h = Math.floor(sec / 3600), m = Math.round((sec % 3600) / 60);
  if (h > 0) return `${h} ساعت و ${m} دقیقه`;
  if (m > 0) return `${m} دقیقه`;
  return 'کمتر از یک دقیقه';
}

function StageRow({ stage }) {
  const pct = stage.items_total > 0
    ? Math.min(100, Math.round((stage.items_done / stage.items_total) * 100))
    : (stage.status === 'done' || stage.status === 'skipped' ? 100 : 0);
  const color = stage.status === 'failed' ? '#ef4444'
    : stage.status === 'running' ? 'var(--acc1, #6366f1)'
    : stage.status === 'done' ? '#22c55e' : '#9ca3af';
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 14, marginBottom: 4 }}>
        <span>{stage.label}</span>
        <span style={{ color: 'var(--text-dim)' }}>
          {stage.items_total > 0 && stage.status !== 'skipped'
            ? `${(stage.items_done || 0).toLocaleString('fa-IR')} از ${stage.items_total.toLocaleString('fa-IR')} — `
            : ''}
          {STAGE_STATUS[stage.status] || stage.status}
        </span>
      </div>
      <div style={{ background: 'rgba(120,120,160,.15)', borderRadius: 6, height: 8, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 6, transition: 'width .6s' }} />
      </div>
      {stage.error && (
        <div style={{ color: '#ef4444', fontSize: 12, marginTop: 4 }} dir="ltr">{stage.error}</div>
      )}
    </div>
  );
}

function Pipeline({ guard }) {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [showSchedule, setShowSchedule] = useState(false);
  const [scheduleAt, setScheduleAt] = useState('');
  const [flash, setFlash] = useState('');

  const load = useCallback(() => {
    guard(adminApi.pipeline).then((d) => d && setData(d));
  }, [guard]);
  useEffect(() => { load(); }, [load]);

  const jobActive = data?.job && ['pending', 'running'].includes(data.job.status);
  useEffect(() => {
    if (!jobActive) return undefined;
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, [jobActive, load]);

  const act = async (payload, okMsg) => {
    setBusy(true);
    setFlash('');
    try {
      await guard(() => adminApi.pipelineAction(payload));
      if (okMsg) setFlash(okMsg);
      load();
    } catch (e) {
      setFlash(e.message || 'خطا');
    } finally {
      setBusy(false);
    }
  };

  const job = data?.job;
  const st = job ? (JOB_STATUS[job.status] || {}) : {};
  const prog = job?.progress || {};
  const pending = data?.pending;
  const loadLevelFa = { low: 'کم', medium: 'متوسط', high: 'زیاد' }[data?.load?.level] || '—';

  return (
    <>
      <h1 className="page-title">پردازش داده‌ها</h1>
      <div className="page-sub">// DATA_PIPELINE — پردازش خودکار داده‌های خودروها روی سرور</div>

      {flash && <div className="pform-error" style={{ margin: '12px 0' }}>{flash}</div>}

      {!data ? <div className="empty-state">در حال بارگذاری…</div> : (
        <>
          {/* Recommendation + pending work */}
          <div className="card glass" style={{ margin: '16px 0' }}>
            <h3 style={{ marginTop: 0 }}><Icon name="sparkles" size={16} /> وضعیت و توصیه</h3>
            <p style={{ fontSize: 14, lineHeight: 1.9, margin: '6px 0' }}>{data.recommendation}</p>
            <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap', fontSize: 13, color: 'var(--text-dim)' }}>
              <span>بار فعلی سرور: <b style={{ color: data.load.level === 'high' ? '#ef4444' : data.load.level === 'medium' ? '#eab308' : '#22c55e' }}>{loadLevelFa}</b> ({data.load.load1} روی {data.load.cores} هسته)</span>
              {pending?.has_work && <span>زمان تقریبی کل: <b>{fmtDur(data.estimate_s)}</b></span>}
            </div>
            {pending?.has_work && (
              <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', marginTop: 10, fontSize: 13 }}>
                {pending.need_catalog.length > 0 && <span className="st-badge st-rev">{pending.need_catalog.length} خودرو خارج از کاتالوگ</span>}
                {pending.need_rag_ingest.length > 0 && <span className="st-badge st-rev">{pending.need_rag_ingest.length} خودرو بدون ایندکس</span>}
                {pending.pages_to_embed > 0 && <span className="st-badge st-rev">{pending.pages_to_embed.toLocaleString('fa-IR')} صفحه در انتظار پردازش هوشمند</span>}
                {pending.need_diag.length > 0 && <span className="st-badge st-rev">{pending.need_diag.length} خودرو بدون موتور عیب‌یابی</span>}
              </div>
            )}
            {!pending?.has_work && !jobActive && (
              <div style={{ color: '#22c55e', fontSize: 14, marginTop: 6 }}>✓ همه پردازش‌ها انجام شده است.</div>
            )}
          </div>

          {/* Controls */}
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 16 }}>
            <button className="btn btn-accent" disabled={busy || jobActive || !pending?.has_work}
              onClick={() => act({ action: 'start' }, 'پردازش شروع شد — می‌توانید این صفحه را ببندید؛ اجرا روی سرور ادامه می‌یابد.')}>
              <Icon name="check" size={14} /> شروع پردازش الان
            </button>
            <button className="btn" disabled={busy || jobActive || !pending?.has_work}
              onClick={() => setShowSchedule((v) => !v)}>
              زمان‌بندی برای بعد
            </button>
            {job?.resumable && (
              <button className="btn btn-accent" disabled={busy}
                onClick={() => act({ action: 'resume', job_id: job.id }, 'ادامه پردازش از همان نقطه شروع شد.')}>
                ادامه از همان نقطه
              </button>
            )}
            {jobActive && (
              <button className="btn" disabled={busy}
                onClick={() => act({ action: 'cancel', job_id: job.id }, 'درخواست توقف ثبت شد؛ پیشرفت ذخیره می‌شود و بعداً قابل ادامه است.')}>
                توقف (با حفظ پیشرفت)
              </button>
            )}
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: 'var(--text-dim)' }}>
              <input type="checkbox" checked={!!data.settings?.auto_enabled}
                onChange={(e) => act({ action: 'settings', auto_enabled: e.target.checked })} />
              پردازش خودکار داده‌های جدید در ساعات کم‌بار
            </label>
          </div>

          {showSchedule && (
            <div className="card glass" style={{ marginBottom: 16, display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
              <span style={{ fontSize: 14 }}>اجرا در:</span>
              <input type="datetime-local" dir="ltr" value={scheduleAt}
                onChange={(e) => setScheduleAt(e.target.value)} />
              <button className="btn btn-accent" disabled={busy || !scheduleAt}
                onClick={() => { act({ action: 'schedule', at: scheduleAt }, 'زمان‌بندی ثبت شد؛ در زمان مقرر خودکار اجرا می‌شود.'); setShowSchedule(false); }}>
                ثبت زمان‌بندی
              </button>
              <span style={{ fontSize: 12, color: 'var(--text-dim)' }}>
                پیشنهاد: ساعات بامداد که ترافیک سایت کم است.
              </span>
            </div>
          )}

          {/* Active / last job */}
          {job && (
            <div className="card glass" style={{ marginBottom: 16 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', flexWrap: 'wrap', gap: 8 }}>
                <h3 style={{ margin: 0 }}>
                  کار #{job.id}{' '}
                  <span className="st-badge" style={{ background: `${st.color}22`, color: st.color }}>{st.label}</span>
                  {job.status === 'running' && job.worker_alive === false && (
                    <span style={{ color: '#eab308', fontSize: 12, marginRight: 8 }}>(در حال بررسی وضعیت اجرا…)</span>
                  )}
                </h3>
                <span style={{ fontSize: 13, color: 'var(--text-dim)' }}>
                  {job.scheduled_for ? `زمان اجرا: ${fmtDate(job.scheduled_for)}` : `شروع: ${job.started_at ? fmtDate(job.started_at) : '—'}`}
                </span>
              </div>

              {/* Overall bar */}
              <div style={{ margin: '14px 0 6px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 14, marginBottom: 4 }}>
                  <b>پیشرفت کل: {Math.round(prog.overall_pct || 0)}٪</b>
                  <span style={{ color: 'var(--text-dim)' }}>
                    {prog.eta_s != null && job.status === 'running' ? `زمان باقی‌مانده: ~${fmtDur(prog.eta_s)}` : ''}
                    {prog.rate_pps ? ` — سرعت: ${prog.rate_pps} صفحه/ثانیه` : ''}
                  </span>
                </div>
                <div style={{ background: 'rgba(120,120,160,.15)', borderRadius: 8, height: 14, overflow: 'hidden' }}>
                  <div style={{ width: `${Math.min(100, prog.overall_pct || 0)}%`, height: '100%', background: st.color || 'var(--acc1, #6366f1)', borderRadius: 8, transition: 'width .6s' }} />
                </div>
              </div>

              {prog.current_item && job.status === 'running' && (
                <div style={{ fontSize: 13, color: 'var(--text-dim)', marginBottom: 8 }}>
                  در حال پردازش: <b dir="ltr">{prog.current_item}</b>
                </div>
              )}

              <div style={{ marginTop: 14 }}>
                {(job.stages || []).map((s) => <StageRow key={s.key} stage={s} />)}
              </div>

              {job.log_tail && (
                <details style={{ marginTop: 10 }}>
                  <summary style={{ cursor: 'pointer', fontSize: 13, color: 'var(--text-dim)' }}>جزئیات فنی (گزارش اجرا)</summary>
                  <pre dir="ltr" style={{ fontSize: 11, maxHeight: 220, overflow: 'auto', background: 'rgba(0,0,0,.25)', padding: 10, borderRadius: 8, whiteSpace: 'pre-wrap' }}>{job.log_tail}</pre>
                </details>
              )}
              {job.error && <div style={{ color: '#ef4444', fontSize: 13, marginTop: 8 }}>خطا در مراحل: {job.error}</div>}
              {['paused', 'stalled'].includes(job.status) && (
                <div style={{ color: '#eab308', fontSize: 13, marginTop: 8 }}>
                  پیشرفت ذخیره شده است — با دکمه «ادامه از همان نقطه» دقیقاً از جای قبلی ادامه می‌یابد (سیستم به‌صورت خودکار هم تلاش می‌کند).
                </div>
              )}
            </div>
          )}

          {/* History */}
          {(data.history || []).length > 0 && (
            <div className="card glass" style={{ padding: 0, overflow: 'hidden' }}>
              <table className="adm-table">
                <thead><tr><th>#</th><th>وضعیت</th><th>نوع شروع</th><th>ایجاد</th><th>پایان</th><th>پیشرفت</th></tr></thead>
                <tbody>
                  {data.history.map((h) => {
                    const hs = JOB_STATUS[h.status] || {};
                    return (
                      <tr key={h.id}>
                        <td>{h.id}</td>
                        <td><span className="st-badge" style={{ background: `${hs.color}22`, color: hs.color }}>{hs.label || h.status}</span></td>
                        <td>{{ manual: 'دستی', auto: 'خودکار', schedule: 'زمان‌بندی' }[h.trigger] || h.trigger}</td>
                        <td>{fmtDate(h.created_at)}</td>
                        <td>{h.finished_at ? fmtDate(h.finished_at) : '—'}</td>
                        <td dir="ltr">{h.overall_pct != null ? `${Math.round(h.overall_pct)}%` : '—'}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </>
  );
}
