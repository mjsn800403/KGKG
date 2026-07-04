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

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import Icon from '@/components/Icon';
import { adminApi, getAdminToken, setAdminToken } from '@/utils/api';

const ROLES = [
  { id: 'after_sales_manager', label: 'مدیر خدمات پس از فروش' },
  { id: 'after_sales_head', label: 'رئیس خدمات پس از فروش' },
  { id: 'technical_expert', label: 'کارشناس فنی' },
  { id: 'after_sales_supervisor', label: 'سرپرست خدمات پس از فروش' },
  { id: 'technical_staff', label: 'پرسنل خدمات فنی' },
];

const DOCS = [
  { id: 'parts', label: 'فهرست قطعات' },
  { id: 'manual', label: 'منوال تعمیر' },
  { id: 'standard_time', label: 'زمان استاندارد' },
  { id: 'special_tools', label: 'ابزار مخصوص' },
  { id: 'full_spec', label: 'مشخصات کامل' },
];

const REQ_STATUS = {
  new: { label: 'جدید', cls: 'st-new' },
  reviewing: { label: 'در حال بررسی', cls: 'st-rev' },
  approved: { label: 'تأیید شده', cls: 'st-ok' },
  rejected: { label: 'رد شده', cls: 'st-no' },
};

const SECTIONS = [
  { id: 'overview', label: 'نمای کلی', icon: 'catalog' },
  { id: 'catalog', label: 'فهرست خودروها', icon: 'car' },
  { id: 'requests', label: 'درخواست‌های خرید', icon: 'cart' },
  { id: 'companies', label: 'شرکت‌ها و دسترسی‌ها', icon: 'info' },
  { id: 'users', label: 'کاربران', icon: 'gear' },
  { id: 'activity', label: 'گزارش فعالیت', icon: 'clock' },
];

function fmtDate(iso) {
  try {
    return new Date(iso).toLocaleString('fa-IR', { dateStyle: 'short', timeStyle: 'short' });
  } catch { return iso; }
}

export default function AdminPage() {
  const [section, setSection] = useState('overview');
  const [needToken, setNeedToken] = useState(false);
  const [tokenInput, setTokenInput] = useState('');
  const [flash, setFlash] = useState('');
  const [companyPrefill, setCompanyPrefill] = useState(null);

  const guard = useCallback(async (fn) => {
    try {
      return await fn();
    } catch (e) {
      if (e?.unauthorized) { setNeedToken(true); return null; }
      setFlash(e?.message || 'خطای نامشخص');
      setTimeout(() => setFlash(''), 5000);
      return null;
    }
  }, []);

  return (
    <div className="screen fade" id="admin-panel">
      <div className="shell">
        <aside className="sidebar">
          <Link className="sb-brand" href="/admin">
            <img src="/logo.png" alt="KGtechvault" />
            <span>پنل مدیریت</span>
          </Link>
          {SECTIONS.map((s) => (
            <a
              key={s.id}
              className={`sb-link${section === s.id ? ' active' : ''}`}
              onClick={() => setSection(s.id)}
              style={{ cursor: 'pointer' }}
            >
              <Icon name={s.icon} /> {s.label}
            </a>
          ))}
          <div style={{ marginTop: 'auto', paddingTop: 30 }}>
            <Link className="sb-link" href="/">
              <Icon name="logout" /> بازگشت به سایت
            </Link>
          </div>
        </aside>
        <main className="main">
          <div className="topbar">
            <div className="breadcrumb"><b>مدیریت سامانه</b></div>
            <div className="userchip"><div className="avatar">AD</div> KGTECHVAULT Company — ادمین</div>
          </div>

          {flash && <div className="pform-error" style={{ marginBottom: 16 }}>{flash}</div>}

          {needToken ? (
            <div className="card glass" style={{ maxWidth: 480, padding: 24 }}>
              <h3 style={{ marginTop: 0 }}>ورود ادمین</h3>
              <p style={{ color: 'var(--text-dim)', fontSize: 14 }}>
                توکن مدیریتی (KG_ADMIN_TOKEN) را وارد کنید.
              </p>
              <div className="field">
                <label>توکن مدیریتی</label>
                <input type="password" dir="ltr" value={tokenInput} onChange={(e) => setTokenInput(e.target.value)} />
              </div>
              <button
                className="btn btn-accent"
                onClick={() => { setAdminToken(tokenInput.trim()); setNeedToken(false); }}
              >
                ورود
              </button>
            </div>
          ) : (
            <>
              {section === 'overview' && <Overview guard={guard} go={setSection} />}
              {section === 'catalog' && <Catalog guard={guard} />}
              {section === 'requests' && (
                <Requests
                  guard={guard}
                  onCreateCompany={(prefill) => {
                    setCompanyPrefill(prefill);
                    setSection('companies');
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
              {section === 'activity' && <Activity guard={guard} />}
            </>
          )}
        </main>
      </div>
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
function Requests({ guard, onCreateCompany }) {
  const [items, setItems] = useState([]);
  const load = useCallback(() => {
    guard(adminApi.requests).then((d) => d && setItems(d.items));
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
              </div>
            </div>
          );
        })}
        {items.length === 0 && <div className="empty-state">درخواستی ثبت نشده است.</div>}
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Shared: pick cars + doc layers. `scope` limits selectable cars/docs (used for
// per-user grants so they can't exceed the company's purchase).
function AccessEditor({ cars, value, onChange, scope }) {
  const scoped = scope
    ? cars.filter((c) => scope.some((s) => s.car.id === c.id))
    : cars;

  const rowFor = (carId) => value.find((v) => v.car_id === carId);

  const toggleCar = (carId) => {
    if (rowFor(carId)) onChange(value.filter((v) => v.car_id !== carId));
    else onChange([...value, { car_id: carId, documents: [] }]);
  };

  const toggleDoc = (carId, doc) => {
    onChange(value.map((v) => {
      if (v.car_id !== carId) return v;
      const has = v.documents.includes(doc);
      return { ...v, documents: has ? v.documents.filter((d) => d !== doc) : [...v.documents, doc] };
    }));
  };

  const allowedDocs = (carId) => {
    if (!scope) return DOCS;
    const s = scope.find((x) => x.car.id === carId);
    if (!s || !s.documents || s.documents.length === 0) return DOCS;
    return DOCS.filter((d) => s.documents.includes(d.id));
  };

  return (
    <div style={{ display: 'grid', gap: 8 }}>
      {scoped.map((c) => {
        const row = rowFor(c.id);
        return (
          <div key={c.id} className="glass" style={{ padding: '10px 14px', borderRadius: 10 }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
              <input type="checkbox" checked={!!row} onChange={() => toggleCar(c.id)} />
              <b>{c.brand} {c.model}</b>
              <span style={{ color: 'var(--text-dim)' }}>{c.year}</span>
            </label>
            {row && (
              <div className="doc-chips" style={{ marginTop: 8 }}>
                {allowedDocs(c.id).map((d) => (
                  <button
                    key={d.id} type="button"
                    className={`doc-chip${row.documents.includes(d.id) ? ' active' : ''}`}
                    onClick={() => toggleDoc(c.id, d.id)}
                  >
                    <span className="tick">✓</span>{d.label}
                  </button>
                ))}
                <span style={{ fontSize: 12, color: 'var(--text-faint)', alignSelf: 'center' }}>
                  (خالی = همه لایه‌های مجاز)
                </span>
              </div>
            )}
          </div>
        );
      })}
      {scoped.length === 0 && <div className="empty-state">خودرویی در محدوده مجاز نیست.</div>}
    </div>
  );
}

// ---------------------------------------------------------------------------
function Companies({ guard, prefilled, onPrefillUsed }) {
  const [companies, setCompanies] = useState([]);
  const [cars, setCars] = useState([]);
  const [selected, setSelected] = useState(null);     // deep company dict
  const [accessDraft, setAccessDraft] = useState([]);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ name: '', reg_no: '', landline: '', mobile: '', employees_count: '', seats_count: '', is_demo: false, ai_assistant_enabled: false, note: '' });

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
    setSelected(d.company);
    setAccessDraft(d.company.accesses.map((a) => ({ car_id: a.car.id, documents: a.documents })));
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
      setForm({ name: '', reg_no: '', landline: '', mobile: '', employees_count: '', seats_count: '', is_demo: false, ai_assistant_enabled: false, note: '' });
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
              کاربران: {c.users_count} · صندلی: {c.seats_count ?? '—'} · پرسنل: {c.employees_count ?? '—'}
            </div>

            {selected?.id === c.id && (
              <div style={{ marginTop: 16 }} onClick={(e) => e.stopPropagation()}>
                <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
                  <button className="btn" onClick={() => toggleField('active')}>{selected.active ? 'غیرفعال‌سازی شرکت' : 'فعال‌سازی شرکت'}</button>
                  <button className="btn" onClick={() => toggleField('ai_assistant_enabled')}>{selected.ai_assistant_enabled ? 'حذف دستیار AI' : 'فعال‌سازی دستیار AI'}</button>
                  <button className="btn" onClick={() => toggleField('is_demo')}>{selected.is_demo ? 'خروج از حالت دمو' : 'تبدیل به دمو'}</button>
                </div>
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
  const [form, setForm] = useState({ company_id: '', username: '', display_name: '', role: 'technical_expert', ai_assistant_enabled: false });
  const [issued, setIssued] = useState(null);          // {username, password}
  const [editingAccess, setEditingAccess] = useState(null); // user id
  const [accessDraft, setAccessDraft] = useState([]);
  const [companyScope, setCompanyScope] = useState(null);

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
      setForm({ company_id: '', username: '', display_name: '', role: 'technical_expert', ai_assistant_enabled: false });
      load();
    }
  };

  const openAccess = async (u) => {
    const d = await guard(() => adminApi.companyDetail(u.company_id));
    if (!d) return;
    setCompanyScope(d.company.accesses);
    setAccessDraft(u.accesses.map((a) => ({ car_id: a.car.id, documents: a.documents })));
    setEditingAccess(u.id);
  };

  const saveAccess = async () => {
    const d = await guard(() => adminApi.setUserAccess(editingAccess, accessDraft));
    if (d) { setEditingAccess(null); load(); }
  };

  const patch = async (id, payload) => {
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
          </div>
          <div className="doc-chips" style={{ margin: '10px 0' }}>
            <button type="button" className={`doc-chip${form.ai_assistant_enabled ? ' active' : ''}`}
              onClick={() => setForm({ ...form, ai_assistant_enabled: !form.ai_assistant_enabled })}>
              <span className="tick">✓</span>دستیار هوش مصنوعی (در صورت فعال بودن برای شرکت)
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
                {u.ai_assistant_enabled && <span className="adm-status st-ok">AI</span>}
                <span className={`adm-status ${u.active ? 'st-ok' : 'st-no'}`}>{u.active ? 'فعال' : 'غیرفعال'}</span>
              </div>
            </div>
            <div style={{ fontSize: 13, color: 'var(--text-dim)', marginTop: 6 }}>
              دسترسی: {u.accesses.length ? u.accesses.map((a) => `${a.car.brand} ${a.car.model} ${a.car.year}`).join('، ') : 'هیچ خودرویی'}
              {u.last_login_at && <> · آخرین ورود: {fmtDate(u.last_login_at)}</>}
            </div>
            <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
              <button className="btn" onClick={() => openAccess(u)}>ویرایش دسترسی</button>
              <button className="btn" onClick={() => patch(u.id, { active: !u.active })}>{u.active ? 'غیرفعال‌سازی' : 'فعال‌سازی'}</button>
              <button className="btn" onClick={() => patch(u.id, { reset_password: true })}>بازنشانی رمز</button>
              <button className="btn" onClick={() => patch(u.id, { ai_assistant_enabled: !u.ai_assistant_enabled })}>
                {u.ai_assistant_enabled ? 'حذف AI' : 'فعال‌سازی AI'}
              </button>
            </div>

            {editingAccess === u.id && (
              <div style={{ marginTop: 14 }}>
                <div className="pform-section">دسترسی این کاربر (زیرمجموعه خرید شرکت)</div>
                <AccessEditor cars={cars} value={accessDraft} onChange={setAccessDraft} scope={companyScope} />
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
            <tr><th>زمان</th><th>کاربر</th><th>شرکت</th><th>نقش</th><th>عملیات</th><th>جزئیات</th></tr>
          </thead>
          <tbody>
            {items.map((a) => (
              <tr key={a.id}>
                <td>{fmtDate(a.created_at)}</td>
                <td dir="ltr">{a.user}</td>
                <td>{a.company}</td>
                <td>{a.role_label}</td>
                <td>{a.action}</td>
                <td>{a.detail}</td>
              </tr>
            ))}
            {items.length === 0 && (
              <tr><td colSpan={6} style={{ textAlign: 'center', color: 'var(--text-dim)' }}>فعالیتی ثبت نشده است.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}
