'use client';

import { useCallback, useEffect, useState } from 'react';
import Icon from './Icon';
import { adminApi } from '../utils/api';
import { csatFace, faNum, fmtHours, fmtMinutes, ratio, sourceLabel } from '../lib/support';
import { friendlyError } from '../lib/friendlyError';

// Three admin panels: the support KPIs, the product-feedback feed, and the
// knowledge-base authoring desk.
//
// Every figure the KPI panel shows is defined in
// audit-evidence/16-improvement-programme/METRIC_DEFINITIONS.md with its source
// column and a query that reproduces it. Where the API returns null — no
// measurement, as opposed to a measurement of zero — these panels render an em
// dash. A dashboard that prints 0٪ compliance because nothing has been decided
// yet is worse than one that admits it does not know.

const RANGES = [7, 30, 90];

function Stat({ label, value, hint, tone }) {
  return (
    <div className={`sup-stat${tone ? ` sup-stat-${tone}` : ''}`}>
      <div className="sup-stat-v">{value}</div>
      <div className="sup-stat-l">{label}</div>
      {hint && <div className="sup-stat-h">{hint}</div>}
    </div>
  );
}

function useRanged(fetcher, days) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState('');
  const load = useCallback(() => {
    fetcher(days).then((d) => { setData(d); setErr(''); }).catch((e) => setErr(friendlyError(e)));
  }, [fetcher, days]);
  useEffect(() => { load(); }, [load]);
  return { data, err, reload: load };
}

// ---------------------------------------------------------------------------

export function SupportMetricsPanel() {
  const [days, setDays] = useState(30);
  const { data, err } = useRanged(adminApi.supportMetrics, days);

  if (err) return <div className="pform-error">{err}</div>;
  if (!data) return <div className="inbox-empty glass">در حال بارگذاری…</div>;

  const t = data.totals || {};
  const sla = data.sla || {};
  const csat = data.csat || {};
  const k = data.knowledge || {};
  const b = data.backlog || {};

  return (
    <div className="sup">
      <div className="inbox-filters">
        <span className="inbox-flabel">بازه:</span>
        {RANGES.map((d) => (
          <button key={d} className={`inbox-fbtn${days === d ? ' on' : ''}`} onClick={() => setDays(d)}>
            {faNum(d)} روز
          </button>
        ))}
      </div>

      <h3 className="sup-h">حجم کار</h3>
      <div className="sup-stats">
        <Stat label="درخواست ثبت‌شده" value={faNum(t.created ?? 0)} />
        <Stat label="باز" value={faNum(t.open ?? 0)} />
        <Stat label="بسته‌شده" value={faNum(t.closed ?? 0)} />
        <Stat label="بازگشایی‌شده" value={faNum(t.reopened ?? 0)}
          hint="مشتری گفته مشکل حل نشده" tone={t.reopened ? 'warn' : null} />
        <Stat label="ارجاع فوری" value={faNum(t.escalated ?? 0)} />
      </div>

      <h3 className="sup-h">زمان پاسخ و رسیدگی</h3>
      <div className="sup-stats">
        <Stat label="میانگین پاسخ اول" value={fmtMinutes(data.first_response?.avg_minutes)}
          hint={`اندازه‌گیری‌شده: ${faNum(data.first_response?.measured ?? 0)} از ${faNum(t.created ?? 0)}`} />
        <Stat label="صدک ۹۰ پاسخ اول" value={fmtMinutes(data.first_response?.p90_minutes)} />
        <Stat label="میانگین رسیدگی" value={fmtHours(data.resolution?.avg_hours)} />
        <Stat label="صدک ۹۰ رسیدگی" value={fmtHours(data.resolution?.p90_hours)} />
      </div>

      <h3 className="sup-h">پایبندی به مهلت (SLA)</h3>
      <p className="sup-note">
        «در انتظار» از مخرج بیرون است: درخواستی که مهلتش نگذشته، موفقیت نیست.
        مهلت‌ها ساعت تقویمی‌اند، نه ساعت کاری.
      </p>
      <div className="sup-stats">
        <Stat label="پایبندی پاسخ اول" value={ratio(sla.response?.compliance)}
          hint={`در مهلت ${faNum(sla.response?.met ?? 0)} · گذشته ${faNum(sla.response?.breached ?? 0)} · در انتظار ${faNum(sla.response?.pending ?? 0)}`}
          tone={sla.response?.breached ? 'warn' : null} />
        <Stat label="پایبندی رسیدگی" value={ratio(sla.resolution?.compliance)}
          hint={`در مهلت ${faNum(sla.resolution?.met ?? 0)} · گذشته ${faNum(sla.resolution?.breached ?? 0)} · در انتظار ${faNum(sla.resolution?.pending ?? 0)}`}
          tone={sla.resolution?.breached ? 'warn' : null} />
      </div>

      <h3 className="sup-h">کار باقی‌مانده (وضعیت همین لحظه)</h3>
      <div className="sup-stats">
        <Stat label="باز" value={faNum(b.open ?? 0)} />
        <Stat label="بدون مسئول" value={faNum(b.unassigned ?? 0)}
          tone={b.unassigned ? 'bad' : null} hint="صف بی‌صاحب" />
        <Stat label="از مهلت گذشته" value={faNum(b.breaching_now ?? 0)}
          tone={b.breaching_now ? 'bad' : null} />
        <Stat label="قدیمی‌ترین" value={b.oldest_days == null ? '—' : `${faNum(Math.round(b.oldest_days))} روز`} />
      </div>

      <h3 className="sup-h">رضایت مشتری</h3>
      <div className="sup-stats">
        <Stat label="میانگین امتیاز" value={csat.avg == null ? '—' : `${csatFace(Math.round(csat.avg))} ${faNum(csat.avg.toFixed(1))}`} />
        <Stat label="تعداد امتیاز" value={faNum(csat.responses ?? 0)} />
        <Stat label="نرخ پاسخ به نظرسنجی" value={ratio(csat.response_rate)}
          hint="از درخواست‌هایی که در این بازه بسته شدند" />
      </div>
      {csat.distribution && (
        <div className="sup-dist">
          {[5, 4, 3, 2, 1].map((s) => (
            <div className="sup-dist-row" key={s}>
              <span className="sup-dist-k">{csatFace(s)} {faNum(s)}</span>
              <span className="sup-dist-bar">
                <i style={{ width: `${csat.responses ? (csat.distribution[String(s)] / csat.responses) * 100 : 0}%` }} />
              </span>
              <span className="sup-dist-n">{faNum(csat.distribution[String(s)] ?? 0)}</span>
            </div>
          ))}
        </div>
      )}

      <h3 className="sup-h">کانال ورود درخواست</h3>
      <p className="sup-note">
        سهم «تلفن» در برابر «سامانه» همان عددی است که نشان می‌دهد بازخورد از تلفن
        به کانال دیجیتال منتقل شده یا نه.
      </p>
      <div className="sup-chips">
        {Object.entries(data.by_source || {}).length === 0 && <span className="sup-chip">—</span>}
        {Object.entries(data.by_source || {}).map(([s, n]) => (
          <span className="sup-chip" key={s}>{sourceLabel(s)}: <b>{faNum(n)}</b></span>
        ))}
      </div>

      <h3 className="sup-h">بازخورد محصول</h3>
      <div className="sup-stats">
        <Stat label="بازخورد دریافتی" value={faNum(data.feedback?.submissions ?? 0)} />
        <Stat label="میانگین امتیاز صفحه‌ها"
          value={data.feedback?.avg_rating == null ? '—' : faNum(data.feedback.avg_rating.toFixed(1))} />
        <Stat label="همراه با توضیح" value={faNum(data.feedback?.with_comment ?? 0)} />
      </div>

      <h3 className="sup-h">دانش‌نامه</h3>
      <div className="sup-stats">
        <Stat label="مقاله" value={faNum(k.articles ?? 0)} hint={`منتشرشده ${faNum(k.published ?? 0)}`} />
        <Stat label="نیازمند بازبینی" value={faNum(k.stale ?? 0)} tone={k.stale ? 'warn' : null}
          hint="از دورهٔ بازبینی خودش گذشته" />
        <Stat label="بدون مالک" value={faNum(k.unowned ?? 0)} tone={k.unowned ? 'bad' : null} />
        <Stat label="برآمده از تیکت" value={faNum(k.from_tickets ?? 0)}
          hint="دانشی که از کار واقعی پشتیبانی درآمده" />
        <Stat label="جستجوی بی‌نتیجه" value={ratio(k.zero_result_rate)}
          hint={`${faNum(k.zero_result_searches ?? 0)} از ${faNum(k.searches ?? 0)} جستجو`} />
      </div>
      {(k.top_misses || []).length > 0 && (
        <>
          <div className="sup-sub">پرتکرارترین جستجوهای بی‌نتیجه — فهرست کاری: هر سطر، مقاله‌ای است که باید نوشته شود</div>
          <ul className="sup-misses">
            {k.top_misses.map((m) => (
              <li key={m.query}><b>{faNum(m.count)}×</b> {m.query}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------

export function ProductFeedbackPanel() {
  const [days, setDays] = useState(30);
  const { data, err } = useRanged(adminApi.productFeedback, days);

  if (err) return <div className="pform-error">{err}</div>;
  if (!data) return <div className="inbox-empty glass">در حال بارگذاری…</div>;
  const items = data.items || [];

  return (
    <div className="sup">
      <div className="inbox-filters">
        <span className="inbox-flabel">بازه:</span>
        {RANGES.map((d) => (
          <button key={d} className={`inbox-fbtn${days === d ? ' on' : ''}`} onClick={() => setDays(d)}>
            {faNum(d)} روز
          </button>
        ))}
      </div>
      <div className="sup-stats">
        <Stat label="بازخورد" value={faNum(data.totals?.submissions ?? 0)} />
        <Stat label="میانگین امتیاز"
          value={data.totals?.avg_rating == null ? '—' : faNum(data.totals.avg_rating.toFixed(1))} />
        <Stat label="همراه با توضیح" value={faNum(data.totals?.with_comment ?? 0)} />
      </div>

      {(data.by_page || []).length > 0 && (
        <>
          <h3 className="sup-h">به تفکیک صفحه</h3>
          <ul className="sup-misses">
            {data.by_page.map((p) => (
              <li key={p.page || '—'}>
                <b>{faNum(p.submissions)}×</b> <span dir="ltr">{p.page || '—'}</span>
                {p.avg_rating != null && <> — میانگین {faNum(p.avg_rating.toFixed(1))}</>}
              </li>
            ))}
          </ul>
        </>
      )}

      <h3 className="sup-h">بازخوردها</h3>
      {items.length === 0 ? (
        <div className="inbox-empty glass">بازخوردی در این بازه ثبت نشده است.</div>
      ) : (
        <ul className="inbox-list">
          {items.map((f) => (
            <li key={f.id} className="inbox-item glass">
              <div className="inbox-item-head">
                {f.rating ? <span className="tkt-csat">{csatFace(f.rating)} {faNum(f.rating)}/۵</span> : null}
                <b className="inbox-subject" dir="ltr">{f.page || '—'}</b>
                <span className="inbox-kind">{f.company || '—'}</span>
                <span className="inbox-when">
                  {new Date(f.created_at).toLocaleString('fa-IR', { dateStyle: 'short', timeStyle: 'short' })}
                </span>
              </div>
              {f.comment && <p className="inbox-body">{f.comment}</p>}
              {f.user && <div className="inbox-meta"><span>کاربر: {f.user}</span></div>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------

const STATUS_LABELS = { draft: 'پیش‌نویس', published: 'منتشرشده', archived: 'بایگانی' };
const AUDIENCE_LABELS = { customer: 'مشتری', internal: 'داخلی' };

export function KnowledgeAdmin() {
  const [data, setData] = useState(null);
  const [staleOnly, setStaleOnly] = useState(false);
  const [status, setStatus] = useState('');
  const [sel, setSel] = useState(null);         // {article, revisions}
  const [showNew, setShowNew] = useState(false);
  const [err, setErr] = useState('');

  const load = useCallback(() => {
    const params = {};
    if (status) params.status = status;
    if (staleOnly) params.stale = '1';
    adminApi.kb(params).then((d) => { setData(d); setErr(''); }).catch((e) => setErr(friendlyError(e)));
  }, [status, staleOnly]);
  useEffect(() => { load(); }, [load]);

  const open = async (id) => {
    try { setSel(await adminApi.kbArticle(id)); }
    catch (e) { setErr(friendlyError(e)); }
  };

  if (sel) {
    return (
      <ArticleEditor
        bundle={sel}
        owners={data?.owners || []}
        onBack={() => { setSel(null); load(); }}
        onSaved={async (id) => { await open(id); load(); }}
      />
    );
  }

  const articles = data?.articles || [];
  return (
    <div className="sup">
      <div className="inbox-filters">
        {['', 'draft', 'published', 'archived'].map((s) => (
          <button key={s || 'all'} className={`inbox-fbtn${status === s ? ' on' : ''}`} onClick={() => setStatus(s)}>
            {s ? STATUS_LABELS[s] : 'همه'}
          </button>
        ))}
        <button className={`inbox-fbtn${staleOnly ? ' on' : ''}`} onClick={() => setStaleOnly((v) => !v)}>
          <Icon name="clock" size={14} /> فقط نیازمند بازبینی
        </button>
        <button className="btn inbox-act" onClick={() => setShowNew((v) => !v)}>
          <Icon name="plus" size={14} /> مقالهٔ جدید
        </button>
      </div>

      {err && <div className="pform-error">{err}</div>}

      {showNew && (
        <NewArticleForm onDone={() => { setShowNew(false); load(); }} />
      )}

      {articles.length === 0 ? (
        <div className="inbox-empty glass">مقاله‌ای در این نما نیست.</div>
      ) : (
        <ul className="inbox-list">
          {articles.map((a) => (
            <li key={a.id} className="inbox-item glass">
              <div className="inbox-item-head">
                <span className={`rt-pill rt-pill-${a.status === 'published' ? 'ok' : a.status === 'draft' ? 'warn' : 'bad'}`}>
                  {STATUS_LABELS[a.status] || a.status}
                </span>
                <b className="inbox-subject">{a.title}</b>
                <span className="inbox-kind">{AUDIENCE_LABELS[a.audience] || a.audience}</span>
                {a.category && <span className="guide-kb-cat">{a.category}</span>}
                {a.is_stale && <span className="tkt-esc">نیازمند بازبینی</span>}
                {a.source_request_id && <span className="tkt-reopen">از تیکت #{faNum(a.source_request_id)}</span>}
                <span className="inbox-when">v{faNum(a.version)}</span>
              </div>
              <div className="inbox-meta">
                <span>مالک: <b>{a.owner?.name || '— بدون مالک —'}</b></span>
                <span>دورهٔ بازبینی: {faNum(a.review_interval_days)} روز</span>
                <span>بازدید {faNum(a.views)} · 👍 {faNum(a.helpful)} · 👎 {faNum(a.unhelpful)}</span>
              </div>
              <p className="inbox-body">{a.excerpt}</p>
              <div className="inbox-actions">
                <button className="btn inbox-act" onClick={() => open(a.id)}>
                  <Icon name="edit" size={14} /> ویرایش
                </button>
                {a.status !== 'published' && (
                  <button className="btn inbox-act inbox-act-ok"
                    onClick={async () => { await adminApi.kbUpdate(a.id, { status: 'published' }); load(); }}>
                    انتشار
                  </button>
                )}
                {a.is_stale && (
                  <button className="btn inbox-act inbox-act-info"
                    onClick={async () => { await adminApi.kbUpdate(a.id, { reviewed: true }); load(); }}>
                    بازبینی شد
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function NewArticleForm({ onDone }) {
  const [f, setF] = useState({
    title: '', slug: '', body: '', category: '', audience: 'customer', status: 'draft',
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const set = (k) => (e) => setF((x) => ({ ...x, [k]: e.target.value }));

  const submit = async () => {
    if (!f.title.trim() || !f.slug.trim() || !f.body.trim()) {
      setErr('عنوان، شناسه و متن الزامی است.'); return;
    }
    setBusy(true); setErr('');
    try { await adminApi.kbCreate(f); onDone?.(); }
    catch (e) { setErr(friendlyError(e, 'ساخت مقاله ناموفق بود.')); }
    finally { setBusy(false); }
  };

  return (
    <div className="reqform glass">
      <div className="reqform-row">
        <label htmlFor="kb-title">عنوان</label>
        <input id="kb-title" value={f.title} onChange={set('title')} />
      </div>
      <div className="reqform-row">
        <label htmlFor="kb-slug">شناسهٔ لاتین (slug)</label>
        <input id="kb-slug" value={f.slug} onChange={set('slug')} dir="ltr" />
      </div>
      <div className="reqform-row">
        <label htmlFor="kb-cat">دسته</label>
        <input id="kb-cat" value={f.category} onChange={set('category')} />
      </div>
      <div className="reqform-row">
        <label htmlFor="kb-aud">مخاطب</label>
        <select id="kb-aud" value={f.audience} onChange={set('audience')}>
          <option value="customer">مشتری</option>
          <option value="internal">داخلی (فقط تیم پلتفرم)</option>
        </select>
      </div>
      <div className="reqform-row">
        <label htmlFor="kb-body">متن</label>
        <textarea id="kb-body" rows={8} value={f.body} onChange={set('body')}
          placeholder="پاسخ، مرحله به مرحله. یک خط خالی، پاراگراف تازه می‌سازد." />
      </div>
      {err && <div className="pform-error">{err}</div>}
      <div className="reqform-actions">
        <button className="btn btn-accent" disabled={busy} onClick={submit}>
          {busy ? 'در حال ساخت…' : 'ساخت پیش‌نویس'}
        </button>
      </div>
    </div>
  );
}

// A text change appends a revision and bumps the version; a review, a status
// change or a reassignment does not — the backend decides that, and the editor
// says so rather than implying every save is a new version.
function ArticleEditor({ bundle, owners, onBack, onSaved }) {
  const a = bundle.article;
  const [title, setTitle] = useState(a.title);
  const [body, setBody] = useState(a.body);
  const [category, setCategory] = useState(a.category || '');
  const [status, setStatus] = useState(a.status);
  const [audience, setAudience] = useState(a.audience);
  const [ownerId, setOwnerId] = useState(a.owner?.id || '');
  const [interval, setInterval_] = useState(a.review_interval_days);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [msg, setMsg] = useState('');

  const save = async (extra = {}) => {
    setBusy(true); setErr(''); setMsg('');
    try {
      await adminApi.kbUpdate(a.id, {
        title, body, category, status, audience,
        owner_id: ownerId ? Number(ownerId) : null,
        review_interval_days: Number(interval) || undefined,
        ...extra,
      });
      setMsg('ذخیره شد.');
      await onSaved?.(a.id);
    } catch (e) { setErr(friendlyError(e, 'ذخیره ناموفق بود.')); }
    finally { setBusy(false); }
  };

  return (
    <div className="sup">
      <button type="button" className="guide-back" onClick={onBack}>
        <Icon name="chevron" /> فهرست مقاله‌ها
      </button>
      <h3 className="sup-h">
        ویرایش «{a.title}» — نسخهٔ {faNum(a.version)}
        {a.is_stale && <span className="tkt-esc"> نیازمند بازبینی</span>}
      </h3>
      <p className="sup-note">
        تغییر متن یا عنوان، نسخهٔ تازه و یک رکورد در تاریخچه می‌سازد. تغییر وضعیت،
        مالک، دسته یا ثبت بازبینی، نسخهٔ تازه نمی‌سازد.
      </p>

      <div className="reqform glass">
        <div className="reqform-row">
          <label htmlFor="kbe-title">عنوان</label>
          <input id="kbe-title" value={title} onChange={(e) => setTitle(e.target.value)} />
        </div>
        <div className="reqform-row">
          <label htmlFor="kbe-body">متن</label>
          <textarea id="kbe-body" rows={12} value={body} onChange={(e) => setBody(e.target.value)} />
        </div>
        <div className="reqform-row">
          <label htmlFor="kbe-cat">دسته</label>
          <input id="kbe-cat" value={category} onChange={(e) => setCategory(e.target.value)} />
        </div>
        <div className="reqform-row">
          <label htmlFor="kbe-owner">مالک (مسئول نگه‌داری)</label>
          <select id="kbe-owner" value={ownerId} onChange={(e) => setOwnerId(e.target.value)}>
            <option value="">— بدون مالک —</option>
            {owners.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
          </select>
        </div>
        <div className="reqform-row">
          <label htmlFor="kbe-interval">دورهٔ بازبینی (روز)</label>
          <input id="kbe-interval" type="number" min="1" value={interval}
            onChange={(e) => setInterval_(e.target.value)} />
        </div>
        <div className="reqform-row">
          <label htmlFor="kbe-status">وضعیت</label>
          <select id="kbe-status" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="draft">پیش‌نویس</option>
            <option value="published">منتشرشده</option>
            <option value="archived">بایگانی</option>
          </select>
        </div>
        <div className="reqform-row">
          <label htmlFor="kbe-aud">مخاطب</label>
          <select id="kbe-aud" value={audience} onChange={(e) => setAudience(e.target.value)}>
            <option value="customer">مشتری</option>
            <option value="internal">داخلی</option>
          </select>
        </div>
        {err && <div className="pform-error">{err}</div>}
        {msg && <div className="sup-ok">{msg}</div>}
        <div className="reqform-actions">
          <button className="btn" disabled={busy} onClick={() => save({ reviewed: true })}>
            ثبت بازبینی
          </button>
          <button className="btn btn-accent" disabled={busy} onClick={() => save()}>
            {busy ? 'در حال ذخیره…' : 'ذخیره'}
          </button>
        </div>
      </div>

      <h3 className="sup-h">تاریخچهٔ نسخه‌ها</h3>
      <ul className="sup-misses">
        {(bundle.revisions || []).slice().reverse().map((r) => (
          <li key={r.version}>
            <b>v{faNum(r.version)}</b> — {r.editor || '—'} ·{' '}
            {new Date(r.created_at).toLocaleString('fa-IR', { dateStyle: 'short', timeStyle: 'short' })}
            {r.note ? ` · ${r.note}` : ''}
          </li>
        ))}
      </ul>
    </div>
  );
}
