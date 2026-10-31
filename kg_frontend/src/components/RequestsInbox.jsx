'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import Icon from './Icon';
import TicketThread from './TicketThread';
import DeskLayout from './desk/DeskLayout';
import DeskFilters from './desk/DeskFilters';
import TicketList from './desk/TicketList';
import { adminApi } from '../utils/api';
import useEventStream from '../utils/useEventStream';
import {
  csatFace, dueText, faNum, nextStatuses, slaLabel, slaTone, sourceLabel, topicLabel,
} from '../lib/support';
import { friendlyError } from '../lib/friendlyError';

// The agent's side of the support desk.
//
// It used to be a list with a single "note" input per row, which is why any
// real exchange moved to the telephone. It is now a worklist: the SLA state
// and what is already late are visible without opening anything, a ticket has
// an owner, a conversation and internal notes, an ageing ticket can be
// escalated, and a resolved one can be promoted into a knowledge article so
// the answer is written down once instead of re-derived.

function statusClass(s) {
  return { pending: 'warn', in_progress: 'info', completed: 'ok', rejected: 'bad' }[s] || 'warn';
}


export default function RequestsInbox() {
  const [items, setItems] = useState([]);
  const [counts, setCounts] = useState({});
  const [admins, setAdmins] = useState([]);
  const [topics, setTopics] = useState([]);
  const [cursor, setCursor] = useState(null);
  const [filters, setFilters] = useState({
    q: '', status: '', topic: '', unread: '', source: '', awaiting: '',
  });
  const [breachOnly, setBreachOnly] = useState(false);
  const [busy, setBusy] = useState(null);
  const [note, setNote] = useState({});
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [showLog, setShowLog] = useState(false);
  const [err, setErr] = useState('');
  const [loading, setLoading] = useState(true);
  const selectedRef = useRef(null);
  useEffect(() => { selectedRef.current = selectedId; }, [selectedId]);

  const fetchPage = useCallback(async (append) => {
    const params = { ...filters };
    if (append && cursor) params.cursor = cursor;
    const d = await adminApi.companyRequests(params);
    setItems((cur) => (append ? [...cur, ...(d.requests || [])] : (d.requests || [])));
    setCursor(d.next_cursor || null);
    setCounts(d.counts || {});
    setAdmins(d.admins || []);
    setTopics(d.topics || []);
    setErr('');
  }, [filters, cursor]);

  const load = useCallback(async () => {
    try { await fetchPage(false); } catch (e) { setErr(friendlyError(e)); }
  }, [fetchPage]);

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      try {
        const d = await adminApi.companyRequests(filters);
        if (cancelled) return;
        setItems(d.requests || []);
        setCursor(d.next_cursor || null);
        setCounts(d.counts || {});
        setAdmins(d.admins || []);
        setTopics(d.topics || []);
        setErr('');
      } catch (e) { if (!cancelled) setErr(friendlyError(e)); }
      finally { if (!cancelled) setLoading(false); }
    };
    run();
    return () => { cancelled = true; };
  }, [filters]);

  // Opening a ticket loads its thread and marks it read for THIS admin —
  // another admin's unread state is their own.
  const open = useCallback(async (id) => {
    setSelectedId(id);
    setDetail(null);
    try {
      const d = await adminApi.companyRequest(id);
      setDetail(d.request || null);
      if ((d.request?.unread_count || 0) > 0) {
        const after = await adminApi.markCompanyRequestRead(id);
        setDetail(after.request || d.request);
        setItems((cur) => cur.map((r) => (r.id === id ? { ...r, unread_count: 0 } : r)));
      }
    } catch (e) { setErr(friendlyError(e)); }
  }, []);

  const loadDetail = useCallback(async (id) => {
    if (!id) return;
    try {
      const d = await adminApi.companyRequest(id);
      setDetail(d.request || null);
      setItems((cur) => cur.map((r) => (r.id === id ? { ...r, ...d.request } : r)));
    } catch (e) { setErr(friendlyError(e)); }
  }, []);

  useEventStream({
    admin: true,
    onEvent: (evt) => {
      if (!String(evt.type || '').startsWith('request.')) return;
      const id = evt.payload?.request?.id;
      const current = selectedRef.current;
      if (current && id === current) { loadDetail(current); return; }
      load();
    },
  });

  const patch = async (id, payload) => {
    setBusy(id);
    try {
      await adminApi.setCompanyRequest(id, payload);
      await load();
      if (selectedId === id) await loadDetail(id);
    } catch (e) { setErr(friendlyError(e, 'ثبت تغییر ناموفق بود.')); }
    finally { setBusy(null); }
  };

  const act = (id, status) => patch(id, { status, admin_note: note[id] || undefined })
    .then(() => setNote((n) => ({ ...n, [id]: '' })));

  // "Only what is late" stays a client-side filter over the page: a breach
  // nobody looks at is the same as no SLA at all, and it reads the SLA state
  // the server already computed.
  const shown = breachOnly
    ? items.filter((r) => r.sla?.response_state === 'breached'
                       || r.sla?.resolve_state === 'breached')
    : items;

  const filtered = Boolean(filters.q || filters.status || filters.topic || filters.unread
                           || filters.source || filters.awaiting || breachOnly);
  const emptyNode = loading
    ? <div className="inbox-empty glass">در حال بارگذاری…</div>
    : (
      <div className="inbox-empty glass">
        <b>{filtered ? 'هیچ تیکتی با این فیلترها پیدا نشد' : 'تیکتی ثبت نشده است'}</b>
        {filtered && (
          <button type="button" className="btn" onClick={() => {
            setBreachOnly(false);
            setFilters({ q: '', status: '', topic: '', unread: '', source: '', awaiting: '' });
          }}>پاک کردن فیلترها</button>
        )}
      </div>
    );

  return (
    <div className="inbox">
      {err && <div className="pform-error">{err}</div>}

      <AnimatePresence>
        {showLog && (
          <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }} style={{ overflow: 'hidden' }}>
            <LogCallForm onDone={() => { setShowLog(false); load(); }} />
          </motion.div>
        )}
      </AnimatePresence>

      <DeskLayout
        hasSelection={Boolean(selectedId)}
        onBack={() => { setSelectedId(null); setDetail(null); }}
        listPane={(
          <>
            <DeskFilters
              value={filters}
              onChange={setFilters}
              topics={topics}
              counts={counts}
              statuses={[
                { id: 'pending', label: 'در انتظار' },
                { id: 'in_progress', label: 'در حال انجام' },
                { id: 'completed', label: 'انجام‌شده' },
                { id: 'rejected', label: 'رد‌شده' },
              ]}
              extra={(
                <>
                  <button type="button"
                    className={`inbox-fbtn${filters.awaiting ? ' on' : ''}`}
                    onClick={() => setFilters((f) => ({
                      ...f, awaiting: f.awaiting ? '' : '1', cursor: null,
                    }))}>
                    <Icon name="mail" size={14} /> منتظر پاسخ ما
                    {counts.awaiting_reply
                      ? <span className="inbox-fcount">{faNum(counts.awaiting_reply)}</span>
                      : null}
                  </button>
                  <button type="button" className={`inbox-fbtn${breachOnly ? ' on' : ''}`}
                    onClick={() => setBreachOnly((b) => !b)}>
                    <Icon name="bell" size={14} /> از مهلت گذشته
                  </button>
                  <select className="dk-select" aria-label="کانال ورود"
                    value={filters.source || ''}
                    onChange={(e) => setFilters((f) => ({
                      ...f, source: e.target.value, cursor: null,
                    }))}>
                    <option value="">همهٔ کانال‌ها</option>
                    {['portal', 'phone', 'email', 'sms', 'in_person'].map((sc) => (
                      <option key={sc} value={sc}>{sourceLabel(sc)}</option>
                    ))}
                  </select>
                  <button type="button" className="btn inbox-act"
                    onClick={() => setShowLog((v) => !v)}>
                    <Icon name="phone" size={14} /> ثبت تماس تلفنی
                  </button>
                </>
              )}
            />
            <TicketList
              items={shown}
              selectedId={selectedId}
              onSelect={open}
              onLoadMore={cursor && !breachOnly ? () => fetchPage(true).catch(() => {}) : null}
              loading={loading}
              emptyNode={emptyNode}
              showCompany
            />
          </>
        )}
        conversationPane={selectedId ? (
          <AdminConversation
            req={detail}
            admins={admins}
            busy={busy === selectedId}
            note={note[selectedId] || ''}
            onNote={(v) => setNote((n) => ({ ...n, [selectedId]: v }))}
            onPatch={(payload) => patch(selectedId, payload)}
            onAct={(status) => act(selectedId, status)}
            onPromoted={() => loadDetail(selectedId)}
          />
        ) : (
          <div className="dk-none">یک تیکت را از فهرست انتخاب کنید.</div>
        )}
      />
    </div>
  );
}

// One ticket, with every control the desk had before: owner, status, escalate,
// the answer note, internal notes, and promotion into a knowledge article once
// it is resolved. Reused rather than reimplemented — that is what keeps this
// behaviour from drifting while the layout changes around it.
function AdminConversation({
  req, admins, busy, note, onNote, onPatch, onAct, onPromoted,
}) {
  if (!req) return <div className="dk-none">در حال بارگذاری گفت‌وگو…</div>;
  const open = ['pending', 'in_progress'].includes(req.status);
  const due = dueText(req.sla?.resolve_due_at);
  return (
    <div className="cv">
      <header className="cv-head">
        <div className="cv-head-main">
          <span className={`rt-pill rt-pill-${statusClass(req.status)}`}>{req.status_label}</span>
          <h2 className="cv-subject">{req.subject}</h2>
        </div>
        <div className="cv-meta">
          <span>{req.company?.name}</span>
          <span>{req.kind_label}</span>
          <span className="tkt-src">{sourceLabel(req.source)}</span>
          {req.topic && <span className="cv-chip">{req.topic_label || topicLabel(req.topic)}</span>}
          {req.car?.name && <span className="cv-chip"><Icon name="car" size={12} /> {req.car.name}</span>}
          {req.created_by?.name && <span>ثبت: {req.created_by.name}</span>}
          {req.priority === 'high' && <span className="inbox-prio">اولویت بالا</span>}
          {req.awaiting_reply && <span className="tkt-wait">منتظر پاسخ ما</span>}
          {req.escalated_at && <span className="tkt-esc">ارجاع‌شده</span>}
          {req.reopen_count > 0 && <span className="tkt-reopen">بازگشایی ×{faNum(req.reopen_count)}</span>}
        </div>

        <div className="tkt-sla">
          {slaTone(req.sla?.response_state) && (
            <span className={`rt-pill rt-pill-${slaTone(req.sla.response_state)}`}>
              پاسخ اول: {slaLabel(req.sla.response_state)}
            </span>
          )}
          {slaTone(req.sla?.resolve_state) && (
            <span className={`rt-pill rt-pill-${slaTone(req.sla.resolve_state)}`}>
              رسیدگی: {slaLabel(req.sla.resolve_state)}
            </span>
          )}
          {open && due && (
            <span className={`tkt-due${due.overdue ? ' overdue' : ''}`}>
              <Icon name="clock" size={13} /> {due.text}
            </span>
          )}
          {req.csat && (
            <span className="tkt-csat" title="رضایت مشتری">
              {csatFace(req.csat.score)} {faNum(req.csat.score)}/۵
            </span>
          )}
        </div>

        <div className="inbox-meta">
          <label className="tkt-assign">
            مسئول:
            <select value={req.assignee?.id || ''} disabled={busy}
              onChange={(e) => onPatch({
                assignee_id: e.target.value ? Number(e.target.value) : null,
              })}>
              <option value="">— بدون مسئول —</option>
              {admins.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
          </label>
          {open && !req.escalated_at && (
            <button className="btn inbox-act" disabled={busy}
              onClick={() => onPatch({ escalate: true })}>
              <Icon name="bell" size={14} /> ارجاع فوری
            </button>
          )}
        </div>
      </header>

      {req.body && <p className="inbox-body">{req.body}</p>}
      {(req.cars?.length > 0 || req.payload?.documents?.length > 0 || req.payload?.seats) && (
        <div className="inbox-meta">
          {req.cars?.length > 0 && <span>خودروها: <b>{req.cars.map((c) => c.name).join('، ')}</b></span>}
          {req.payload?.documents?.length > 0 && <span>مستندات: <b>{req.payload.documents.join('، ')}</b></span>}
          {req.payload?.seats && <span>ظرفیت درخواستی: <b>{req.payload.seats}</b></span>}
        </div>
      )}
      {req.admin_note && <div className="inbox-adminnote">پاسخ: {req.admin_note}</div>}

      <TicketThread
        messages={req.messages || []}
        unreadCount={req.unread_count || 0}
        truncated={Boolean(req.messages_truncated)}
        allowInternal
        sendLabel="ارسال پاسخ"
        placeholder="پاسخ به مشتری…"
        note="اولین پاسخِ قابل‌مشاهده برای مشتری، زمان «پاسخ اول» را ثبت می‌کند؛ یادداشت داخلی نه."
        onSend={(body, { internal }) => onPatch({ message: body, internal })}
      />

      <div className="inbox-actions">
        <input className="inbox-note" placeholder="یادداشت پاسخ (اختیاری)"
          value={note} onChange={(e) => onNote(e.target.value)} />
        {nextStatuses(req.status).map(([st, label]) => (
          <button key={st} className={`btn inbox-act inbox-act-${statusClass(st)}`}
            disabled={busy} onClick={() => onAct(st)}>
            {busy ? '…' : label}
          </button>
        ))}
      </div>

      {['completed', 'rejected'].includes(req.status) && (
        <PromoteForm req={req} onDone={onPromoted} />
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
