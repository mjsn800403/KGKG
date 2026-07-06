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
import { adminApi, adminLogin, adminLogout, getAdminToken, getAdminUser, setAdminToken } from '@/utils/api';
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
  const [needToken, setNeedToken] = useState(true);
  const [adminUser, setAdminUser] = useState(null);
  const [authReady, setAuthReady] = useState(false);
  const [loginForm, setLoginForm] = useState({ username: '', password: '' });
  const [loginBusy, setLoginBusy] = useState(false);
  const [flash, setFlash] = useState('');
  const [companyPrefill, setCompanyPrefill] = useState(null);

  useEffect(() => {
    const token = getAdminToken();
    setNeedToken(!token);
    setAdminUser(getAdminUser());
    setAuthReady(true);
  }, []);

  const guard = useCallback(async (fn) => {
    try {
      return await fn();
    } catch (e) {
      if (e?.unauthorized) { setNeedToken(true); setAdminUser(null); return null; }
      setFlash(e?.message || 'خطای نامشخص');
      setTimeout(() => setFlash(''), 5000);
      return null;
    }
  }, []);

  const handleLogout = () => {
    adminLogout();
    setNeedToken(true);
    setAdminUser(null);
  };

  return (
    <div className="screen fade" id="admin-panel">
      <div className="shell">
        <aside className="sidebar">
          <Link className="sb-brand" href="/admin">
            <img src="/logo.png" alt="KGtechvault" />
            <span>پنل مدیریت</span>
          </Link>
          {SECTIONS.map((s) => (
            <button
              key={s.id}
              type="button"
              className={`sb-link${section === s.id ? ' active' : ''}`}
              onClick={() => setSection(s.id)}
            >
              <Icon name={s.icon} /> {s.label}
            </button>
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
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <div className="userchip">
                <div className="avatar">AD</div>
                {adminUser?.username ? `${adminUser.username} — ادمین` : 'KGTECHVAULT — ادمین'}
              </div>
              {!needToken && (
                <button className="btn" onClick={handleLogout}>خروج</button>
              )}
            </div>
          </div>

          {flash && <div className="pform-error" style={{ marginBottom: 16 }}>{flash}</div>}

          {!authReady ? (
            <div className="empty-state">در حال بارگذاری…</div>
          ) : needToken ? (
            <div className="card glass" style={{ maxWidth: 480, padding: 24 }}>
              <h3 style={{ marginTop: 0 }}>ورود ادمین</h3>
              <p style={{ color: 'var(--text-dim)', fontSize: 14 }}>
                نام کاربری و رمز عبور مدیر سامانه (توسعه: admin / admin)
              </p>
              <form
                onSubmit={async (e) => {
                  e.preventDefault();
                  if (loginBusy) return;
                  setLoginBusy(true);
                  try {
                    await adminLogin(loginForm.username.trim(), loginForm.password);
                    setNeedToken(false);
                    setAdminUser(getAdminUser());
                  } catch (err) {
                    setFlash(err.message || 'ورود ناموفق');
                  } finally {
                    setLoginBusy(false);
                  }
                }}
              >
              <div className="field">
                <label>نام کاربری</label>
                <input dir="ltr" placeholder="admin" value={loginForm.username} onChange={(e) => setLoginForm({ ...loginForm, username: e.target.value })} />
              </div>
              <div className="field">
                <label>رمز عبور</label>
                <input type="password" dir="ltr" placeholder="••••••" value={loginForm.password} onChange={(e) => setLoginForm({ ...loginForm, password: e.target.value })} />
              </div>
              <button className="btn btn-accent" type="submit" disabled={loginBusy}>
                {loginBusy ? 'در حال ورود…' : 'ورود'}
              </button>
              </form>
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
