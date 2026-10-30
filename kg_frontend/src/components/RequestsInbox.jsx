'use client';

import { useCallback, useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import Icon from './Icon';
import TicketThread from './TicketThread';
import { adminApi } from '../utils/api';
import useEventStream from '../utils/useEventStream';
import { csatFace, dueText, faNum, nextStatuses, slaLabel, slaTone, sourceLabel } from '../lib/support';
import { friendlyError } from '../lib/friendlyError';

// The agent's side of the support desk.
//
// It used to be a list with a single "note" input per row, which is why any
// real exchange moved to the telephone. It is now a worklist: the SLA state
// and what is already late are visible without opening anything, a ticket has
// an owner, a conversation and internal notes, an ageing ticket can be
// escalated, and a resolved one can be promoted into a knowledge article so
// the answer is written down once instead of re-derived.

function fmtDate(iso) {
  try { return new Date(iso).toLocaleString('fa-IR', { dateStyle: 'short', timeStyle: 'short' }); }
  catch { return iso; }
}
function statusClass(s) {
  return { pending: 'warn', in_progress: 'info', completed: 'ok', rejected: 'bad' }[s] || 'warn';
}

const STATUS_FILTERS = [
  { id: '', label: 'همه' },
  { id: 'pending', label: 'در انتظار' },
  { id: 'in_progress', label: 'در حال انجام' },
  { id: 'completed', label: 'انجام‌شده' },
  { id: 'rejected', label: 'رد‌شده' },
];
const SOURCE_FILTERS = ['', 'portal', 'phone', 'email', 'sms', 'in_person'];

export default function RequestsInbox() {
  const [items, setItems] = useState([]);
  const [counts, setCounts] = useState({});
  const [admins, setAdmins] = useState([]);
  const [filter, setFilter] = useState('');
  const [source, setSource] = useState('');
  const [breachOnly, setBreachOnly] = useState(false);
  const [busy, setBusy] = useState(null);
  const [note, setNote] = useState({});
  const [openId, setOpenId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [showLog, setShowLog] = useState(false);
  const [err, setErr] = useState('');

  const load = useCallback(async () => {
    try {
      const params = {};
      if (filter) params.status = filter;
      if (source) params.source = source;
      const d = await adminApi.companyRequests(params);
      setItems(d.requests || []);
      setCounts(d.counts || {});
      setAdmins(d.admins || []);
      setErr('');
    } catch (e) { setErr(friendlyError(e)); }
  }, [filter, source]);
  useEffect(() => { load(); }, [load]);

  // As on the customer side: a stale detail is ignored by the row check rather
  // than cleared, which keeps this effect free of synchronous state writes.
  const loadDetail = useCallback(async (id) => {
    if (!id) return;
    try {
      const d = await adminApi.companyRequest(id);
      setDetail(d.request || null);
    } catch (e) { setErr(friendlyError(e)); }
  }, []);

  // Same as the customer side: the thread is fetched by the click that opens it.
  const toggle = useCallback((id) => {
    setOpenId((cur) => (cur === id ? null : id));
    if (openId !== id) loadDetail(id);
  }, [openId, loadDetail]);

  // Live: a seat filing or replying, and another admin's action, both land here.
  useEventStream({
    admin: true,
    onEvent: (evt) => {
      if (!String(evt.type || '').startsWith('request.')) return;
      load();
      const id = evt.payload?.request?.id;
      if (openId && id === openId) loadDetail(openId);
    },
  });

  const patch = async (id, payload) => {
    setBusy(id);
    try {
      await adminApi.setCompanyRequest(id, payload);
      await load();
      if (openId === id) await loadDetail(id);
    } catch (e) { setErr(friendlyError(e, 'ثبت تغییر ناموفق بود.')); }
    finally { setBusy(null); }
  };

  const act = (id, status) => patch(id, { status, admin_note: note[id] || undefined })
    .then(() => setNote((n) => ({ ...n, [id]: '' })));

  // The visible worklist. "Only what is late" is a first-class filter because
  // a breach that nobody looks at is the same as no SLA at all.
  const shown = breachOnly
    ? items.filter((r) => r.sla?.response_state === 'breached' || r.sla?.resolve_state === 'breached')
    : items;

  return (
    <div className="inbox">
      <div className="inbox-filters">
        {STATUS_FILTERS.map((f) => (
          <button key={f.id} className={`inbox-fbtn${filter === f.id ? ' on' : ''}`} onClick={() => setFilter(f.id)}>
            {f.label}
            {f.id && counts[f.id] ? <span className="inbox-fcount">{counts[f.id].toLocaleString('fa-IR')}</span> : null}
          </button>
        ))}
      </div>
      <div className="inbox-filters">
        <span className="inbox-flabel">کانال:</span>
        {SOURCE_FILTERS.map((s) => (
          <button key={s || 'all'} className={`inbox-fbtn${source === s ? ' on' : ''}`} onClick={() => setSource(s)}>
            {s ? sourceLabel(s) : 'همه'}
          </button>
        ))}
        <button className={`inbox-fbtn${breachOnly ? ' on' : ''}`} onClick={() => setBreachOnly((b) => !b)}>
          <Icon name="bell" size={14} /> فقط از مهلت گذشته
        </button>
        <button className="btn inbox-act" onClick={() => setShowLog((v) => !v)}>
          <Icon name="phone" size={14} /> ثبت تماس تلفنی
        </button>
      </div>

      {err && <div className="pform-error">{err}</div>}

      <AnimatePresence>
        {showLog && (
          <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }} style={{ overflow: 'hidden' }}>
            <LogCallForm onDone={() => { setShowLog(false); load(); }} />
          </motion.div>
        )}
      </AnimatePresence>

      {shown.length === 0 ? (
        <div className="inbox-empty glass">درخواستی در این نما وجود ندارد.</div>
      ) : (
        <ul className="inbox-list">
          <AnimatePresence initial={false}>
            {shown.map((r) => {
              const isOpen = openId === r.id;
              const row = isOpen && detail?.id === r.id ? detail : r;
              const due = dueText(row.sla?.resolve_due_at);
              const open = ['pending', 'in_progress'].includes(row.status);
              return (
                <motion.li key={r.id} layout className="inbox-item glass"
                  initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, scale: 0.98 }}>
                  <div className="inbox-item-head">
                    <span className={`rt-pill rt-pill-${statusClass(row.status)}`}>{row.status_label}</span>
                    <b className="inbox-subject">{row.subject}</b>
                    <span className="inbox-kind">{row.kind_label}</span>
                    <span className="tkt-src">{sourceLabel(row.source)}</span>
                    {row.escalated_at && <span className="tkt-esc">ارجاع‌شده</span>}
                    {row.reopen_count > 0 && <span className="tkt-reopen">بازگشایی ×{faNum(row.reopen_count)}</span>}
                    <span className="inbox-when">{fmtDate(row.created_at)}</span>
                  </div>

                  <div className="tkt-sla">
                    {slaTone(row.sla?.response_state) && (
                      <span className={`rt-pill rt-pill-${slaTone(row.sla.response_state)}`}>
                        پاسخ اول: {slaLabel(row.sla.response_state)}
                      </span>
                    )}
                    {slaTone(row.sla?.resolve_state) && (
                      <span className={`rt-pill rt-pill-${slaTone(row.sla.resolve_state)}`}>
                        رسیدگی: {slaLabel(row.sla.resolve_state)}
                      </span>
                    )}
                    {open && due && (
                      <span className={`tkt-due${due.overdue ? ' overdue' : ''}`}>
                        <Icon name="clock" size={13} /> {due.text}
                      </span>
                    )}
                    {row.csat && (
                      <span className="tkt-csat" title="رضایت مشتری">
                        {csatFace(row.csat.score)} {faNum(row.csat.score)}/۵
                      </span>
                    )}
                  </div>

                  <div className="inbox-meta">
                    <span>شرکت: <b>{row.company?.name}</b></span>
                    {row.created_by?.name && <span>ثبت: {row.created_by.name}</span>}
                    {row.priority === 'high' && <span className="inbox-prio">اولویت بالا</span>}
                    <label className="tkt-assign">
                      مسئول:
                      <select
                        value={row.assignee?.id || ''}
                        disabled={busy === r.id}
                        onChange={(e) => patch(r.id, {
                          assignee_id: e.target.value ? Number(e.target.value) : null,
                        })}
                      >
                        <option value="">— بدون مسئول —</option>
                        {admins.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                      </select>
                    </label>
                  </div>

                  {row.body && <p className="inbox-body">{row.body}</p>}
                  {(row.cars?.length > 0 || row.payload?.documents?.length > 0 || row.payload?.seats) && (
                    <div className="inbox-meta">
                      {row.cars?.length > 0 && <span>خودروها: <b>{row.cars.map((c) => c.name).join('، ')}</b></span>}
                      {row.payload?.documents?.length > 0 && <span>مستندات: <b>{row.payload.documents.join('، ')}</b></span>}
                      {row.payload?.seats && <span>ظرفیت درخواستی: <b>{row.payload.seats}</b></span>}
                    </div>
                  )}
                  {row.admin_note && <div className="inbox-adminnote">پاسخ: {row.admin_note}</div>}

                  <div className="inbox-actions">
                    <input className="inbox-note" placeholder="یادداشت پاسخ (اختیاری)"
                      value={note[r.id] || ''} onChange={(e) => setNote((n) => ({ ...n, [r.id]: e.target.value }))} />
                    {nextStatuses(row.status).map(([st, label]) => (
                      <button key={st} className={`btn inbox-act inbox-act-${statusClass(st)}`}
                        disabled={busy === r.id} onClick={() => act(r.id, st)}>
                        {busy === r.id ? '…' : label}
                      </button>
                    ))}
                    {open && !row.escalated_at && (
                      <button className="btn inbox-act" disabled={busy === r.id}
                        onClick={() => patch(r.id, { escalate: true })}>
                        <Icon name="bell" size={14} /> ارجاع فوری
                      </button>
                    )}
                    <button className="btn inbox-act" onClick={() => toggle(r.id)}
                      aria-expanded={isOpen}>
                      <Icon name="mail" size={14} /> گفت‌وگو
                    </button>
                  </div>

                  <AnimatePresence>
                    {isOpen && (
                      <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }}
                        exit={{ opacity: 0, height: 0 }} style={{ overflow: 'hidden' }}>
                        <div className="tkt-detail">
                          {row.messages ? (
                            <TicketThread
                              messages={row.messages}
                              allowInternal
                              sendLabel="ارسال پاسخ"
                              placeholder="پاسخ به مشتری…"
                              note="اولین پاسخِ قابل‌مشاهده برای مشتری، زمان «پاسخ اول» را ثبت می‌کند؛ یادداشت داخلی نه."
                              onSend={(body, { internal }) => patch(r.id, { message: body, internal })}
                            />
                          ) : (
                            <p className="tkt-thread-empty">در حال بارگذاری گفت‌وگو…</p>
                          )}
                          {['completed', 'rejected'].includes(row.status) && (
                            <PromoteForm req={row} onDone={() => loadDetail(r.id)} />
                          )}
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </motion.li>
              );
            })}
          </AnimatePresence>
        </ul>
      )}
    </div>
  );
}

// A request that arrived by telephone is recorded here, so it gets the same
// thread, the same SLA clock and the same metrics as a digital one. Without
// this the only measurable channel would be the one that already worked.
function LogCallForm({ onDone }) {
  const [companies, setCompanies] = useState([]);
  const [form, setForm] = useState({
    company_id: '', subject: '', body: '', source: 'phone', priority: 'normal', kind: 'support',
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  useEffect(() => {
    // /api/admin/companies/ answers {items: [...]}, see portal.admin_companies_view.
    adminApi.companies()
      .then((d) => setCompanies(d.items || []))
      .catch(() => setCompanies([]));
  }, []);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async () => {
    if (!form.company_id) { setErr('شرکت را انتخاب کنید.'); return; }
    if (!form.subject.trim()) { setErr('موضوع الزامی است.'); return; }
    setBusy(true); setErr('');
    try {
      await adminApi.logCompanyRequest({ ...form, company_id: Number(form.company_id) });
      onDone?.();
    } catch (e) { setErr(friendlyError(e, 'ثبت ناموفق بود.')); }
    finally { setBusy(false); }
  };

  return (
    <div className="reqform glass">
      <div className="reqform-row">
        <label htmlFor="log-company">شرکت</label>
        <select id="log-company" value={form.company_id} onChange={set('company_id')}>
          <option value="">— انتخاب شرکت —</option>
          {companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </div>
      <div className="reqform-row">
        <label htmlFor="log-source">کانال</label>
        <select id="log-source" value={form.source} onChange={set('source')}>
          <option value="phone">تلفن</option>
          <option value="email">ایمیل</option>
          <option value="sms">پیامک</option>
          <option value="in_person">حضوری</option>
        </select>
      </div>
      <div className="reqform-row">
        <label htmlFor="log-subject">موضوع</label>
        <input id="log-subject" value={form.subject} onChange={set('subject')}
          placeholder="خلاصهٔ درخواستی که تماس‌گیرنده مطرح کرد" />
      </div>
      <div className="reqform-row">
        <label htmlFor="log-body">شرح تماس</label>
        <textarea id="log-body" rows={3} value={form.body} onChange={set('body')}
          placeholder="چه گفت، چه قرار شد…" />
      </div>
      <div className="reqform-row">
        <label htmlFor="log-priority">اولویت</label>
        <select id="log-priority" value={form.priority} onChange={set('priority')}>
          <option value="low">کم</option><option value="normal">عادی</option><option value="high">زیاد</option>
        </select>
      </div>
      {err && <div className="pform-error">{err}</div>}
      <div className="reqform-actions">
        <button className="btn btn-accent" disabled={busy} onClick={submit}>
          {busy ? 'در حال ثبت…' : 'ثبت درخواست'}
        </button>
      </div>
    </div>
  );
}

// The loop that stops the same answer being written twice: a closed ticket
// becomes a DRAFT article, seeded with the question and the resolution. A
// draft on purpose — somebody still has to edit it into an answer.
function PromoteForm({ req, onDone }) {
  const [slug, setSlug] = useState('');
  const [category, setCategory] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [done, setDone] = useState(false);

  if (done) {
    return (
      <div className="tkt-promoted">
        مقالهٔ پیش‌نویس ساخته شد. برای ویرایش و انتشار به بخش «دانش‌نامه» بروید.
      </div>
    );
  }

  const submit = async () => {
    const s = slug.trim();
    if (!s) { setErr('شناسهٔ مقاله (slug) الزامی است.'); return; }
    setBusy(true); setErr('');
    try {
      await adminApi.promoteRequest(req.id, { slug: s, category: category.trim() || undefined });
      setDone(true);
      onDone?.();
    } catch (e) { setErr(friendlyError(e, 'ساخت مقاله ناموفق بود.')); }
    finally { setBusy(false); }
  };

  return (
    <div className="tkt-promote">
      <div className="tkt-promote-head">
        <Icon name="manual" size={15} /> ساخت مقالهٔ دانش‌نامه از این درخواست
      </div>
      <div className="tkt-promote-row">
        <input value={slug} onChange={(e) => setSlug(e.target.value)}
          placeholder="شناسهٔ لاتین مقاله، مثلاً brake-chapter-empty" dir="ltr" />
        <input value={category} onChange={(e) => setCategory(e.target.value)}
          placeholder="دسته (اختیاری)" />
        <button className="btn inbox-act" disabled={busy} onClick={submit}>
          {busy ? '…' : 'ساخت پیش‌نویس'}
        </button>
      </div>
      {err && <div className="pform-error">{err}</div>}
    </div>
  );
}
