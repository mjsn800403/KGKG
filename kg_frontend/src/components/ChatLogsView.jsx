'use client';

// Assistant chat logs, shared by the platform-admin panel (every company) and
// the company /team/chats page (the manager's org-graph reach only — the
// backend enforces the scope; this view just renders what it is given).
import { useEffect, useState } from 'react';
import Icon from './Icon';

const fa = (n) => Number(n || 0).toLocaleString('fa-IR');

function fmtDate(iso) {
  try {
    return new Date(iso).toLocaleString('fa-IR', { dateStyle: 'short', timeStyle: 'short' });
  } catch { return iso; }
}

const MODE_LABEL = { assist: 'جستجو', diagnose: 'عیب‌یابی', clarify: 'پرسش تکمیلی' };
const PREVIEW = 320;

function Badge({ children, tone }) {
  const color = tone === 'bad' ? 'var(--danger, #e5484d)' : tone === 'ok' ? 'var(--success, #30a46c)' : 'var(--text-dim)';
  return (
    <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 999, border: `1px solid ${color}`, color }}>
      {children}
    </span>
  );
}

function ChatItem({ it, showCompany }) {
  const [open, setOpen] = useState(false);
  const long = (it.answer || '').length > PREVIEW;
  const answer = open || !long ? it.answer : `${it.answer.slice(0, PREVIEW)}…`;
  return (
    <div className="card glass" style={{ padding: '16px 18px', marginBottom: 12 }}>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', fontSize: 13, color: 'var(--text-dim)' }}>
        <Icon name="user" />
        <b style={{ color: 'var(--text)' }}>{it.name || it.user}</b>
        {it.name && <span dir="ltr">{it.user}</span>}
        {showCompany && <span>· {it.company}</span>}
        {it.vehicle && <span>· {it.vehicle}</span>}
        <span style={{ marginInlineStart: 'auto' }}>{fmtDate(it.created_at)}</span>
      </div>
      <div style={{ display: 'flex', gap: 6, marginTop: 8, flexWrap: 'wrap' }}>
        {it.mode && <Badge>{MODE_LABEL[it.mode] || it.mode}</Badge>}
        <Badge tone={it.grounded ? 'ok' : 'bad'}>{it.grounded ? 'مستند به داده' : 'بدون منبع'}</Badge>
        {it.degraded && <Badge tone="bad">پاسخ بدون هوش مصنوعی</Badge>}
      </div>
      <div style={{ marginTop: 12, fontWeight: 600, whiteSpace: 'pre-wrap' }}>
        <Icon name="question" /> {it.question}
      </div>
      <div style={{ marginTop: 10, whiteSpace: 'pre-wrap', lineHeight: 1.9, color: 'var(--text)' }}>
        <Icon name="bot" /> {answer || '—'}
      </div>
      {long && (
        <button type="button" className="adm-select" style={{ cursor: 'pointer', marginTop: 8 }}
          onClick={() => setOpen((v) => !v)}>
          {open ? 'نمایش کوتاه' : 'نمایش کامل پاسخ'}
        </button>
      )}
      {open && it.sources?.length > 0 && (
        <div style={{ marginTop: 10, fontSize: 13, display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {it.sources.map((s, i) => (s.href
            ? <a key={i} href={s.href} target="_blank" rel="noreferrer" className="adm-select">{s.title || s.href}</a>
            : <span key={i} className="adm-select">{s.title}</span>))}
        </div>
      )}
    </div>
  );
}

/**
 * fetcher(params) -> Promise<{items,total,page,pages,users}> (or undefined when
 * the caller's guard handled an auth error). companies: [{id,name}] shows the
 * company filter (platform admin only).
 */
export default function ChatLogsView({ fetcher, companies = null }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState('');
  const [company, setCompany] = useState('');
  const [user, setUser] = useState('');
  const [q, setQ] = useState('');
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(1);

  useEffect(() => {
    let alive = true;
    const params = { page };
    if (company) params.company_id = company;
    if (user) params.user_id = user;
    if (query) params.q = query;
    setErr('');
    Promise.resolve(fetcher(params))
      .then((d) => { if (alive && d) setData(d); })
      .catch((e) => { if (alive) setErr(e?.message || 'بارگذاری گفتگوها ناموفق بود.'); });
    return () => { alive = false; };
  }, [fetcher, company, user, query, page]);

  const submit = (e) => { e.preventDefault(); setPage(1); setQuery(q.trim()); };

  return (
    <>
      <form onSubmit={submit} style={{ margin: '18px 0', display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        {companies && (
          <select className="adm-select" value={company}
            onChange={(e) => { setCompany(e.target.value); setUser(''); setPage(1); }}>
            <option value="">همه شرکت‌ها</option>
            {companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        )}
        <select className="adm-select" value={user} onChange={(e) => { setUser(e.target.value); setPage(1); }}>
          <option value="">همه کاربران</option>
          {(data?.users || []).map((u) => (
            <option key={u.id} value={u.id}>{u.name || u.user} ({fa(u.n)})</option>
          ))}
        </select>
        <input className="adm-select" value={q} onChange={(e) => setQ(e.target.value)}
          placeholder="جستجو در پرسش و پاسخ…" style={{ minWidth: 220 }} />
        <button type="submit" className="adm-select" style={{ cursor: 'pointer' }}>
          <Icon name="search" /> جستجو
        </button>
        {data && <span style={{ color: 'var(--text-dim)', fontSize: 13 }}>{fa(data.total)} گفتگو</span>}
      </form>

      {err && <div className="card glass" style={{ padding: 16, color: 'var(--danger, #e5484d)' }}>{err}</div>}
      {!err && !data && <div style={{ color: 'var(--text-dim)' }}>در حال بارگذاری…</div>}
      {data && data.items.length === 0 && (
        <div className="card glass" style={{ padding: 24, color: 'var(--text-dim)' }}>گفتگویی ثبت نشده است.</div>
      )}
      {data?.items.map((it) => <ChatItem key={it.id} it={it} showCompany={!!companies} />)}

      {data && data.pages > 1 && (
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', justifyContent: 'center', margin: '16px 0' }}>
          <button type="button" className="adm-select" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>قبلی</button>
          <span style={{ fontSize: 13 }}>صفحهٔ {fa(data.page)} از {fa(data.pages)}</span>
          <button type="button" className="adm-select" disabled={page >= data.pages} onClick={() => setPage((p) => p + 1)}>بعدی</button>
        </div>
      )}
    </>
  );
}
