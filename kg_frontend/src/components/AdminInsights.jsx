'use client';
// Admin pages over the observability endpoints: audit trail, AI cost, search
// insights and the adoption funnel (api/audit.py, api/insights.py). Styling
// reuses the analytics classes (an-kpis / an-card / bars / adm-table).
import { Fragment, useCallback, useEffect, useState } from 'react';
import Icon from '@/components/Icon';
import { adminApi } from '@/utils/api';

const RANGES = [{ id: 7, label: '۷ روز' }, { id: 30, label: '۳۰ روز' }, { id: 90, label: '۹۰ روز' }];
const fa = (n, opts) => (n == null ? '—' : Number(n).toLocaleString('fa-IR', opts));
const money = (n) => (n == null ? '—' : Number(n).toLocaleString('fa-IR', { maximumFractionDigits: 4 }));
const ms = (n) => (n == null ? '—' : `${fa(Math.round(n / 100) / 10)} ث`);
const when = (iso) => {
  try { return new Date(iso).toLocaleString('fa-IR', { dateStyle: 'short', timeStyle: 'short' }); } catch { return iso; }
};

function useLoad(guard, fn, deps) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState('');
  useEffect(() => {
    let alive = true;
    setErr('');
    guard(fn).then((d) => { if (alive) { if (d) setData(d); else setErr('بارگذاری ناموفق بود.'); } });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return [data, err];
}

function Ranges({ value, onChange }) {
  return (
    <div className="range-chips" style={{ margin: '16px 0' }}>
      {RANGES.map((r) => (
        <button key={r.id} className={`range-chip${value === r.id ? ' active' : ''}`}
          onClick={() => onChange(r.id)}>{r.label}</button>
      ))}
    </div>
  );
}

function Kpi({ icon, value, label, hot }) {
  return (
    <div className="an-kpi glass" style={hot ? { outline: '1px solid var(--danger, #e5484d)' } : undefined}>
      <div className="an-kpi-ico"><Icon name={icon} /></div>
      <div><div className="an-kpi-val">{value}</div><div className="an-kpi-label">{label}</div></div>
    </div>
  );
}

function Bars({ rows, label, value, fmt = fa, alt }) {
  const max = Math.max(1, ...rows.map((r) => Number(value(r)) || 0));
  if (!rows.length) return <div className="muted">داده‌ای ثبت نشده است.</div>;
  return (
    <div className="bars">
      {rows.map((r, i) => (
        <div className="bar-row" key={i} title={`${label(r)}: ${value(r) ?? 0}`}>
          <span className="bar-label">{label(r)}</span>
          <div className="bar-track"><div className={`bar-fill${alt ? ' alt' : ''}`}
            style={{ width: `${((Number(value(r)) || 0) / max) * 100}%` }} /></div>
          <span className="bar-val">{fmt(value(r))}</span>
        </div>
      ))}
    </div>
  );
}

const Loading = ({ err }) => <div className="empty-state">{err || 'در حال بارگذاری…'}</div>;

// ---------------------------------------------------------------------------
// Audit log
// ---------------------------------------------------------------------------
const OUTCOME = { success: 'موفق', failure: 'خطا', denied: 'رد شده' };
const OUTCOME_COLOR = { success: 'var(--ok, #30a46c)', failure: 'var(--warn, #f5a524)', denied: 'var(--danger, #e5484d)' };

function actionLabel(a) {
  const map = {
    'auth.login': 'ورود کاربر', 'auth.verify_otp': 'کد تأیید ورود', 'auth.resend_otp': 'ارسال دوباره کد',
    'auth.logout': 'خروج', 'auth.recover_start': 'شروع بازیابی رمز', 'auth.recover_reset': 'تغییر رمز (بازیابی)',
    'admin.login': 'ورود ادمین', 'admin.verify_otp': 'کد تأیید ادمین',
    'access.user.update': 'تغییر دسترسی کاربر', 'access.company.update': 'تغییر دسترسی شرکت',
  };
  return map[a] || a;
}

function AccessDiff({ diff }) {
  const parts = [];
  const n = (o) => Object.keys(o || {}).length;
  if (n(diff.added)) parts.push(`+${fa(n(diff.added))} خودرو`);
  if (n(diff.removed)) parts.push(`−${fa(n(diff.removed))} خودرو`);
  if (n(diff.changed)) parts.push(`${fa(n(diff.changed))} تغییر لایه`);
  return <span>{parts.join(' · ') || 'بدون تغییر'}</span>;
}

export function AuditLogPanel({ guard }) {
  const [filters, setFilters] = useState({ action: '', actor: '', outcome: '', ip: '' });
  const [draft, setDraft] = useState(filters);
  const [pages, setPages] = useState([]);      // loaded pages of items
  const [next, setNext] = useState(null);
  const [open, setOpen] = useState(null);
  const [err, setErr] = useState('');

  const load = useCallback((before) => {
    const params = Object.fromEntries(Object.entries(filters).filter(([, v]) => v));
    if (before) params.before_id = before;
    params.limit = 100;
    return guard(() => adminApi.audit(params)).then((d) => {
      if (!d) { setErr('بارگذاری ناموفق بود.'); return; }
      setErr('');
      setPages((p) => (before ? [...p, ...d.items] : d.items));
      setNext(d.next_before_id);
    });
  }, [guard, filters]);
  useEffect(() => { load(); }, [load]);

  const field = (k, ph, ltr) => (
    <input className="input" placeholder={ph} value={draft[k]} dir={ltr ? 'ltr' : undefined}
      onChange={(e) => setDraft({ ...draft, [k]: e.target.value })}
      onKeyDown={(e) => e.key === 'Enter' && setFilters(draft)} style={{ minWidth: 140 }} />
  );

  return (
    <>
      <h1 className="page-title">گزارش ممیزی</h1>
      <div className="page-sub">ورودها (موفق و ناموفق) و همهٔ تغییرات انجام‌شده در سامانه — چه کسی، چه کاری، از کجا</div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, margin: '16px 0', alignItems: 'center' }}>
        {field('action', 'عملیات (مثلاً login)', true)}
        {field('actor', 'کاربر / ادمین', true)}
        {field('ip', 'IP', true)}
        <select className="input" value={draft.outcome} onChange={(e) => { const d = { ...draft, outcome: e.target.value }; setDraft(d); setFilters(d); }}>
          <option value="">همهٔ نتایج</option>
          <option value="success">موفق</option>
          <option value="denied">رد شده</option>
          <option value="failure">خطا</option>
        </select>
        <button className="btn" onClick={() => setFilters(draft)}><Icon name="search" size={14} /> جستجو</button>
      </div>

      {err && <div className="pform-error">{err}</div>}
      <div className="glass" style={{ overflowX: 'auto' }}>
        <table className="adm-table">
          <thead><tr><th>زمان</th><th>عملیات</th><th>انجام‌دهنده</th><th>هدف</th><th>نتیجه</th><th>IP</th><th /></tr></thead>
          <tbody>
            {pages.map((r) => (
              <Fragment key={r.id}>
                <tr>
                  <td>{when(r.at)}</td>
                  <td>{actionLabel(r.action)}{r.detail?.no_2fa && <b style={{ color: OUTCOME_COLOR.denied }}> — بدون رمز دوم</b>}</td>
                  <td dir="ltr">{r.actor || r.actor_type}</td>
                  <td dir="ltr">{r.target_type ? `${r.target_type} ${r.target_id}` : '—'}</td>
                  <td style={{ color: OUTCOME_COLOR[r.outcome] }}>
                    {OUTCOME[r.outcome] || r.outcome}{r.status ? ` (${r.status})` : ''}
                    {r.detail?.access_diff && <div className="muted"><AccessDiff diff={r.detail.access_diff} /></div>}
                  </td>
                  <td dir="ltr">{r.ip || '—'}</td>
                  <td><button className="btn" onClick={() => setOpen(open === r.id ? null : r.id)}>{open === r.id ? 'بستن' : 'جزئیات'}</button></td>
                </tr>
                {open === r.id && (
                  <tr><td colSpan={7}>
                    <pre dir="ltr" style={{ whiteSpace: 'pre-wrap', fontSize: 12, margin: 0, maxHeight: 320, overflow: 'auto' }}>
                      {JSON.stringify({ method: r.method, path: r.path, user_agent: r.user_agent, ...r.detail }, null, 2)}
                    </pre>
                  </td></tr>
                )}
              </Fragment>
            ))}
            {!pages.length && !err && <tr><td colSpan={7} className="muted">رکوردی یافت نشد.</td></tr>}
          </tbody>
        </table>
      </div>
      {next && <div style={{ textAlign: 'center', margin: 16 }}><button className="btn" onClick={() => load(next)}>موارد قدیمی‌تر</button></div>}
    </>
  );
}

// ---------------------------------------------------------------------------
// AI cost
// ---------------------------------------------------------------------------
export function AiCostPanel({ guard }) {
  const [days, setDays] = useState(30);
  const [data, err] = useLoad(guard, () => adminApi.aiCost(days), [guard, days]);
  return (
    <>
      <h1 className="page-title">هزینه و کارایی دستیار</h1>
      <div className="page-sub">هزینهٔ مدل زبانی (طبق گزارش Metis)، توکن‌ها و زمان پاسخ — فقط برای ادمین</div>
      <Ranges value={days} onChange={setDays} />
      {!data ? <Loading err={err} /> : (
        <>
          <div className="page-sub" style={{ marginTop: 8 }}>
            مدل فعلی Metis: <b dir="ltr">{data.model || 'نامشخص'}</b>
            {data.totals.backfilled > 0 && <> — {fa(data.totals.backfilled)} پرسش قدیمی از گزارش فعالیت بازیابی شده (بدون هزینه و پاسخ)</>}
          </div>
          <div className="an-kpis">
            <Kpi icon="chart" value={money(data.totals.cost)} label="هزینهٔ کل" />
            <Kpi icon="bot" value={fa(data.totals.answers)} label="پاسخ‌ها" />
            <Kpi icon="chart" value={money(data.totals.priced_answers ? data.totals.cost / data.totals.priced_answers : null)} label="میانگین هزینهٔ هر پاسخ" />
            <Kpi icon="clock" value={ms(data.totals.avg_latency_ms)} label="میانگین زمان پاسخ" />
            <Kpi icon="info" value={fa(data.totals.degraded)} label="پاسخ بدون مدل (پشتیبان)" hot={data.totals.degraded > 0} />
          </div>
          <div className="muted" style={{ margin: '8px 0 16px' }}>
            توکن ورودی {fa(data.totals.input_tokens)} · توکن خروجی {fa(data.totals.output_tokens)} ·
            زمان مدل {ms(data.totals.avg_llm_latency_ms)} · پاسخ بدون منبع {fa(data.totals.ungrounded)}
          </div>
          <div className="an-grid">
            <section className="an-card glass">
              <div className="an-card-head"><h3><Icon name="building" size={16} /> هزینه به تفکیک شرکت</h3></div>
              <Bars rows={data.by_company} label={(r) => r.company} value={(r) => r.cost} fmt={money} />
            </section>
            <section className="an-card glass">
              <div className="an-card-head"><h3><Icon name="chart" size={16} /> هزینهٔ روزانه</h3></div>
              <Bars rows={data.by_day} label={(r) => new Date(r.day).toLocaleDateString('fa-IR')} value={(r) => r.cost} fmt={money} alt />
            </section>
            <section className="an-card glass an-span">
              <div className="an-card-head"><h3><Icon name="users" size={16} /> پرمصرف‌ترین کاربران</h3></div>
              <table className="adm-table">
                <thead><tr><th>کاربر</th><th>شرکت</th><th>پاسخ‌ها</th><th>هزینه</th></tr></thead>
                <tbody>
                  {data.top_users.map((u) => (
                    <tr key={u.user + u.company}><td dir="ltr">{u.user}</td><td>{u.company}</td><td>{fa(u.answers)}</td><td>{money(u.cost)}</td></tr>
                  ))}
                  {!data.top_users.length && <tr><td colSpan={4} className="muted">هنوز پرسشی ثبت نشده است.</td></tr>}
                </tbody>
              </table>
            </section>
          </div>
        </>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Search insights
// ---------------------------------------------------------------------------
export function SearchInsightsPanel({ guard }) {
  const [days, setDays] = useState(30);
  const [data, err] = useLoad(guard, () => adminApi.searchInsights(days), [guard, days]);
  const pct = (x) => (x == null ? '—' : `${fa(Math.round(x * 1000) / 10)}٪`);
  const QueryTable = ({ rows, empty }) => (
    <table className="adm-table">
      <thead><tr><th>عبارت</th><th>تعداد</th><th>کاربران</th><th>آخرین بار</th></tr></thead>
      <tbody>
        {rows.map((q) => (<tr key={q.query}><td>{q.query}</td><td>{fa(q.count)}</td><td>{fa(q.users)}</td><td>{when(q.last)}</td></tr>))}
        {!rows.length && <tr><td colSpan={4} className="muted">{empty}</td></tr>}
      </tbody>
    </table>
  );
  return (
    <>
      <h1 className="page-title">جستجوها و کمبود محتوا</h1>
      <div className="page-sub">کاربران دنبال چه هستند و چه چیزی را پیدا نمی‌کنند</div>
      <Ranges value={days} onChange={setDays} />
      {!data ? <Loading err={err} /> : (
        <>
          <div className="an-kpis">
            <Kpi icon="search" value={fa(data.total_searches)} label="جستجوها" />
            <Kpi icon="users" value={fa(data.searchers)} label="جستجوکنندگان" />
            <Kpi icon="x" value={pct(data.zero_result_rate)} label="بدون نتیجه" hot={data.zero_result_rate > 0.2} />
            <Kpi icon="clock" value={ms(data.avg_latency_ms)} label="میانگین زمان جستجو" />
          </div>
          <div className="an-grid">
            <section className="an-card glass">
              <div className="an-card-head"><h3><Icon name="x" size={16} /> جستجوهای بی‌نتیجه (کمبود محتوا)</h3></div>
              <QueryTable rows={data.top_zero_result_queries} empty="هیچ جستجوی بی‌نتیجه‌ای نبوده است." />
            </section>
            <section className="an-card glass">
              <div className="an-card-head"><h3><Icon name="search" size={16} /> پرتکرارترین جستجوها</h3></div>
              <QueryTable rows={data.top_queries} empty="هنوز جستجویی ثبت نشده است." />
            </section>
            <section className="an-card glass" style={{ gridColumn: '1 / -1' }}>
              <div className="an-card-head"><h3><Icon name="chart" size={16} /> پربازدیدترین صفحات ({fa(data.total_views)} بازدید)</h3></div>
              <table className="adm-table">
                <thead><tr><th>صفحه</th><th>خودرو</th><th>بازدید</th><th>کاربران</th><th>آخرین بار</th></tr></thead>
                <tbody>
                  {data.top_viewed.map((r, i) => (<tr key={i}><td>{r.title}</td><td>{r.car || '—'}</td><td>{fa(r.count)}</td><td>{fa(r.users)}</td><td>{when(r.last)}</td></tr>))}
                  {!data.top_viewed.length && <tr><td colSpan={5} className="muted">بازدیدی در این بازه نیست.</td></tr>}
                </tbody>
              </table>
            </section>
            <section className="an-card glass">
              <div className="an-card-head"><h3><Icon name="car" size={16} /> جستجو به تفکیک خودرو</h3></div>
              <Bars rows={data.by_car} label={(r) => r.car || '—'} value={(r) => r.searches} />
            </section>
            <section className="an-card glass">
              <div className="an-card-head"><h3><Icon name="bot" size={16} /> پرسش‌های دستیار بدون منبع</h3></div>
              {data.assistant_ungrounded.length ? (
                <ul style={{ margin: 0, paddingInlineStart: 18 }}>
                  {data.assistant_ungrounded.map((q, i) => (
                    <li key={i} style={{ marginBottom: 6 }}>{q.question} <span className="muted">— {q.vehicle || 'بدون خودرو'} · {when(q.at)}</span></li>
                  ))}
                </ul>
              ) : <div className="muted">موردی نیست.</div>}
            </section>
          </div>
        </>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Funnel
// ---------------------------------------------------------------------------
const PR_STATUS = { new: 'جدید', reviewing: 'در حال بررسی', approved: 'تأییدشده', rejected: 'ردشده' };

export function FunnelPanel({ guard }) {
  const [days, setDays] = useState(30);
  const [data, err] = useLoad(guard, () => adminApi.funnel(days), [guard, days]);
  return (
    <>
      <h1 className="page-title">قیف جذب و فعال‌سازی</h1>
      <div className="page-sub">از بازدید سایت تا کاربر فعال؛ هر مرحله با درصد نسبت به مرحلهٔ قبل</div>
      <Ranges value={days} onChange={setDays} />
      {!data ? <Loading err={err} /> : (
        <div className="an-grid">
          <section className="an-card glass an-span">
            <div className="an-card-head"><h3><Icon name="chart" size={16} /> مراحل قیف</h3></div>
            <div className="bars">
              {data.stages.map((s, i) => {
                const max = Math.max(1, ...data.stages.slice(1).map((x) => x.count));
                const prev = i > 0 ? data.stages[i - 1].count : null;
                const conv = prev ? ` · ${fa(Math.round((s.count / prev) * 1000) / 10)}٪` : '';
                return (
                  <div className="bar-row" key={s.key}>
                    <span className="bar-label">{s.label}</span>
                    <div className="bar-track"><div className={`bar-fill${i === 0 ? ' alt' : ''}`}
                      style={{ width: `${i === 0 ? 100 : (s.count / max) * 100}%` }} /></div>
                    <span className="bar-val">{fa(s.count)}{i > 1 ? conv : ''}</span>
                  </div>
                );
              })}
            </div>
            <div className="muted" style={{ marginTop: 8 }}>
              بازدیدکننده‌ها روزانه یکتا شمرده می‌شوند و مقیاس جداگانه دارند؛ درصدها از مرحلهٔ «درخواست خرید» به بعد معنادارند.
            </div>
          </section>
          <section className="an-card glass">
            <div className="an-card-head"><h3><Icon name="cart" size={16} /> وضعیت درخواست‌های خرید</h3></div>
            <Bars rows={Object.entries(data.purchase_requests_by_status).map(([k, v]) => ({ k, v }))}
              label={(r) => PR_STATUS[r.k] || r.k} value={(r) => r.v} alt />
          </section>
          <section className="an-card glass">
            <div className="an-card-head"><h3><Icon name="users" size={16} /> حساب‌های نیازمند پیگیری</h3></div>
            <div className="an-kpis" style={{ margin: 0 }}>
              <Kpi icon="clock" value={fa(data.dormant_accounts)} label={`حساب فعالِ بدون ورود در ${fa(data.days)} روز`} hot={data.dormant_accounts > 0} />
              <Kpi icon="mail" value={fa(data.invited_not_accepted)} label="دعوت پذیرفته‌نشده" />
            </div>
          </section>
        </div>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Grafana log dashboards (ops/observability), embedded behind an admin-only
// ticket cookie — see api/grafanaauth.py.
// ---------------------------------------------------------------------------
const GRAFANA_DASHES = [
  { uid: 'kgkg-overview', label: 'لاگ‌ها' },
  { uid: 'kgkg-server', label: 'سرور و کانتینرها' },
  { uid: 'kgkg-business', label: 'کسب‌وکار' },
];
const grafanaSrc = (uid) => `/grafana/d/${uid}/?orgId=1&kiosk&theme=dark&refresh=1m`;

export function GrafanaPanel({ guard }) {
  const [ready, setReady] = useState(false);
  const [err, setErr] = useState('');
  const [nonce, setNonce] = useState(0);
  const [dash, setDash] = useState(GRAFANA_DASHES[0].uid);
  useEffect(() => {
    let alive = true;
    setReady(false);
    guard(adminApi.grafanaTicket).then((d) => {
      if (!alive) return;
      if (d?.ok) setReady(true); else setErr('دسترسی به داشبورد لاگ‌ها ممکن نشد.');
    });
    return () => { alive = false; };
  }, [guard, nonce]);
  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <div>
          <h1 className="page-title">داشبوردهای Grafana</h1>
          <div className="page-sub">لاگ‌ها و خطاها، منابع سرور و کانتینرها، و آمار کسب‌وکار (کاربران، ورود، هزینهٔ دستیار، جستجو)</div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn" onClick={() => setNonce((n) => n + 1)}><Icon name="refresh" size={14} /> بارگذاری دوباره</button>
          {ready && <a className="btn" href="/grafana/" target="_blank" rel="noopener noreferrer"><Icon name="link" size={14} /> باز کردن Grafana کامل</a>}
        </div>
      </div>
      <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
        {GRAFANA_DASHES.map((d) => (
          <button key={d.uid} className={`btn${dash === d.uid ? ' btn-primary' : ''}`} onClick={() => setDash(d.uid)}>{d.label}</button>
        ))}
      </div>
      {err && <div className="pform-error" style={{ marginTop: 12 }}>{err}</div>}
      {!ready && !err && <Loading />}
      {ready && (
        <iframe key={`${dash}-${nonce}`} title="Grafana" src={grafanaSrc(dash)}
          style={{ width: '100%', height: '78vh', border: 0, borderRadius: 12, marginTop: 16, background: '#111217' }} />
      )}
    </>
  );
}
