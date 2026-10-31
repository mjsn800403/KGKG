'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import Icon from './Icon';
import TicketThread from './TicketThread';
import CsatPrompt from './CsatPrompt';
import DeskLayout from './desk/DeskLayout';
import DeskFilters from './desk/DeskFilters';
import TicketList from './desk/TicketList';
import KbSuggestions from './desk/KbSuggestions';
import { teamApi, getPortalUser, fetchGrantedFleet } from '../utils/api';
import useEventStream from '../utils/useEventStream';
import {
  canRate, dueText, faNum, slaLabel, slaTone, sourceLabel, topicLabel,
} from '../lib/support';
import { friendlyError } from '../lib/friendlyError';

// The customer's side of the support desk.
//
// This page used to be manager-only, because the whole API was: a seat without
// can_manage_team got 403 everywhere, so an ordinary user with a problem had
// only the telephone. Now any seat can open a support request and hold a
// conversation about it here. The kinds offered come from the server's `meta`
// rather than a list in this file, so the manager-only commercial kinds are
// never even shown to someone who would be refused.


export default function RequestsView() {
  const [items, setItems] = useState([]);
  const [meta, setMeta] = useState({ kinds: [], topics: [], can_manage_team: false });
  const [cursor, setCursor] = useState(null);
  const [filters, setFilters] = useState({ q: '', status: '', topic: '', unread: '' });
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const [toast, setToast] = useState(null);
  const [err, setErr] = useState('');
  const [loading, setLoading] = useState(true);
  const toastTimer = useRef(null);
  const selectedRef = useRef(null);
  useEffect(() => { selectedRef.current = selectedId; }, [selectedId]);

  const load = useCallback(async (append = false) => {
    try {
      const params = { ...filters };
      if (append && cursor) params.cursor = cursor;
      const d = await teamApi.requests(params);
      setItems((cur) => (append ? [...cur, ...(d.requests || [])] : (d.requests || [])));
      setCursor(d.next_cursor || null);
      setMeta(d.meta || { kinds: [], topics: [] });
      setErr('');
    } catch (e) { setErr(friendlyError(e)); }
    finally { setLoading(false); }
  }, [filters, cursor]);

  // Filters re-query from the start; `cursor` is deliberately not a dependency
  // here, or every page append would retrigger the first page.
  useEffect(() => {
    let cancelled = false;
    // The loading flag and the cursor reset ride on the fetch's own callbacks
    // rather than the effect body: a synchronous setState here would render
    // twice for every keystroke in the search box.
    const run = async () => {
      try {
        const d = await teamApi.requests(filters);
        if (cancelled) return;
        setItems(d.requests || []);
        setCursor(d.next_cursor || null);
        setMeta(d.meta || { kinds: [], topics: [] });
        setErr('');
      } catch (e) {
        if (!cancelled) setErr(friendlyError(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    run();
    return () => { cancelled = true; };
  }, [filters]);


  // Opening a ticket loads its thread AND marks it read. Those happen together
  // because "read" means the conversation was put in front of somebody.
  const open = useCallback(async (id) => {
    setSelectedId(id);
    setDetail(null);
    try {
      const d = await teamApi.request(id);
      setDetail(d.request || null);
      if ((d.request?.unread_count || 0) > 0) {
        const after = await teamApi.markRead(id);
        setDetail(after.request || d.request);
        setItems((cur) => cur.map((r) => (r.id === id ? { ...r, unread_count: 0 } : r)));
        // The sidebar badge is derived from the same read marks, so it only
        // needs telling that they moved.
        window.dispatchEvent(new CustomEvent('kg:desk-read'));
      }
    } catch (e) { setErr(friendlyError(e)); }
  }, []);

  const flashToast = useCallback((msg, tone = 'ok') => {
    setToast({ msg, tone });
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 5000);
  }, []);

  const refreshRow = useCallback(async (id) => {
    try {
      const d = await teamApi.request(id);
      setDetail(d.request || null);
      setItems((cur) => cur.map((r) => (r.id === id ? { ...r, ...d.request } : r)));
    } catch { /* the list refresh below is the fallback */ }
  }, []);

  useEventStream({
    admin: false,
    onEvent: (evt) => {
      if (!String(evt.type || '').startsWith('request.')) return;
      const req = evt.payload?.request;
      const current = selectedRef.current;
      if (req && current === req.id) {
        // On screen: it arrives in the thread and is marked read. Announcing
        // it as well would be the duplicate notification we are removing.
        refreshRow(req.id);
        teamApi.markRead(req.id).catch(() => {});
        return;
      }
      setItems((cur) => cur.map((r) => (r.id === req?.id
        ? { ...r, ...req, unread_count: (r.unread_count || 0) + (evt.type === 'request.message' ? 1 : 0) }
        : r)));
      if (!req) return;
      if (evt.type === 'request.message') flashToast(`پاسخ تازه روی «${req.subject}»`, 'info');
      else if (evt.type === 'request.updated') {
        if (req.status === 'completed') flashToast(`درخواست «${req.subject}» انجام شد ✓`, 'ok');
        else if (req.status === 'rejected') flashToast(`درخواست «${req.subject}» رد شد`, 'bad');
        else if (req.status === 'in_progress') flashToast(`رسیدگی به «${req.subject}» آغاز شد`, 'info');
      }
    },
  });

  const reply = async (body) => {
    const wasClosed = detail && ['completed', 'rejected'].includes(detail.status);
    await teamApi.replyRequest(selectedId, body);
    await refreshRow(selectedId);
    flashToast(wasClosed ? 'درخواست بازگشایی شد و پیام شما ثبت شد' : 'پیام شما ثبت شد', 'ok');
  };

  const rate = async (csat) => {
    await teamApi.rateRequest(selectedId, csat);
    await refreshRow(selectedId);
    flashToast('ممنون از بازخوردتان 🙏', 'ok');
  };

  const cancel = async () => {
    await teamApi.cancelRequest(selectedId);
    await refreshRow(selectedId);
    flashToast('درخواست لغو شد', 'info');
  };

  const filtered = Boolean(filters.q || filters.status || filters.topic || filters.unread);
  const emptyNode = loading ? (
    <div className="inbox-empty glass">در حال بارگذاری…</div>
  ) : filtered ? (
    // Distinct from having no tickets at all: telling somebody they have none
    // when they have forty and a bad filter is how a tool loses their trust.
    <div className="inbox-empty glass">
      <b>هیچ تیکتی با این فیلترها پیدا نشد</b>
      <button type="button" className="btn"
        onClick={() => setFilters({ q: '', status: '', topic: '', unread: '' })}>
        پاک کردن فیلترها
      </button>
    </div>
  ) : (
    <div className="inbox-empty glass">
      <span className="inbox-empty-ico" aria-hidden="true"><Icon name="mailplus" /></span>
      <b>هنوز درخواستی ثبت نکرده‌اید</b>
      <p>
        برای هر مشکل فنی، پرسش دربارهٔ مستندات یا هر درخواست دیگری از همین‌جا تیکت بدهید؛
        پاسخ پشتیبانی و روند رسیدگی را در همین صفحه می‌بینید.
      </p>
      <button type="button" className="btn btn-accent" onClick={() => setShowForm(true)}>
        ثبت درخواست جدید
      </button>
    </div>
  );

  return (
    <div className="reqview">
      <div className="reqview-head">
        <div>
          <h1 className="rt-title">پشتیبانی و درخواست‌ها</h1>
          <p className="rt-sub">
            مشکل یا پرسش خود را همین‌جا ثبت کنید، گفت‌وگو را دنبال کنید و مهلت پاسخ را ببینید.
          </p>
        </div>
        <button className="btn btn-accent" onClick={() => setShowForm((v) => !v)} id="req-new"
          data-guide="desk-new">
          <Icon name="plus" size={16} /> درخواست جدید
        </button>
      </div>

      {err && <div className="pform-error">{err}</div>}

      <AnimatePresence>
        {showForm && (
          <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }} style={{ overflow: 'hidden' }}>
            <NewRequestForm
              kinds={meta.kinds || []}
              topics={meta.topics || []}
              onDone={(msg) => {
                setShowForm(false);
                setFilters((f) => ({ ...f }));
                flashToast(msg || 'درخواست شما ثبت شد', 'ok');
              }}
            />
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
              topics={meta.topics || []}
              statuses={[
                { id: 'pending', label: 'در انتظار' },
                { id: 'in_progress', label: 'در حال انجام' },
                { id: 'completed', label: 'انجام‌شده' },
              ]}
            />
            <TicketList
              items={items}
              selectedId={selectedId}
              onSelect={open}
              onLoadMore={cursor ? () => load(true) : null}
              loading={loading}
              emptyNode={emptyNode}
            />
          </>
        )}
        conversationPane={selectedId ? (
          <Conversation
            req={detail}
            onSend={reply}
            onRate={rate}
            onCancel={cancel}
          />
        ) : (
          <div className="dk-none">یک تیکت را از فهرست انتخاب کنید.</div>
        )}
      />

      <AnimatePresence>
        {toast && (
          <motion.div className={`reqtoast reqtoast-${toast.tone}`}
            initial={{ opacity: 0, y: 20, scale: 0.96 }} animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 12 }}>
            {toast.msg}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// One ticket's conversation, with its state above it. Every control here was
// already in the accordion this replaces — SLA, progress, rating, cancel — and
// is reused rather than reimplemented, which is what keeps that behaviour from
// drifting while the layout changes around it.
function Conversation({ req, onSend, onRate, onCancel }) {
  if (!req) return <div className="dk-none">در حال بارگذاری گفت‌وگو…</div>;
  const closed = ['completed', 'rejected'].includes(req.status);
  return (
    <div className="cv">
      <header className="cv-head">
        <div className="cv-head-main">
          <span className={`rt-pill rt-pill-${
            { pending: 'warn', in_progress: 'info', completed: 'ok', rejected: 'bad' }[req.status] || 'warn'
          }`}>{req.status_label}</span>
          <h2 className="cv-subject">{req.subject}</h2>
        </div>
        <div className="cv-meta">
          <span>{req.kind_label}</span>
          {req.topic && <span className="cv-chip">{req.topic_label || topicLabel(req.topic)}</span>}
          {req.car?.name && <span className="cv-chip"><Icon name="car" size={12} /> {req.car.name}</span>}
          {req.source && req.source !== 'portal' && (
            <span className="tkt-src">از {sourceLabel(req.source)}</span>
          )}
        </div>
        <SlaRow req={req} />
        <ReqProgress status={req.status} />
      </header>

      <TicketThread
        messages={req.messages || []}
        unreadCount={req.unread_count || 0}
        truncated={Boolean(req.messages_truncated)}
        onSend={onSend}
        placeholder={closed
          ? 'اگر مشکل حل نشده، همین‌جا بنویسید تا درخواست بازگشایی شود…'
          : 'پاسخ یا توضیح بیشتر…'}
        note={closed ? 'ارسال پیام روی یک درخواست بسته، آن را بازگشایی می‌کند.' : null}
      />

      {req.csat && (
        <div className="csat-done">
          امتیاز شما ثبت شده است: <b>{faNum(req.csat.score)} از ۵</b>
          {req.csat.comment ? ` — «${req.csat.comment}»` : ''}
        </div>
      )}
      {canRate(req, getPortalUser()) && <CsatPrompt onRate={onRate} />}

      {['pending', 'in_progress'].includes(req.status) && (
        <div className="inbox-actions">
          <button className="btn" onClick={onCancel}>انصراف از درخواست</button>
        </div>
      )}
    </div>
  );
}

// The promise and whether it was kept. A ticket with no target (one filed
// before the policy existed) renders nothing rather than a misleading badge.
function SlaRow({ req }) {
  const sla = req.sla;
  if (!sla) return null;
  const respTone = slaTone(sla.response_state);
  const resTone = slaTone(sla.resolve_state);
  const due = dueText(sla.resolve_due_at);
  const open = ['pending', 'in_progress'].includes(req.status);
  if (!respTone && !resTone) return null;
  return (
    <div className="tkt-sla">
      {respTone && (
        <span className={`rt-pill rt-pill-${respTone}`}>
          پاسخ اول: {slaLabel(sla.response_state)}
        </span>
      )}
      {resTone && (
        <span className={`rt-pill rt-pill-${resTone}`}>
          رسیدگی: {slaLabel(sla.resolve_state)}
        </span>
      )}
      {open && due && (
        <span className={`tkt-due${due.overdue ? ' overdue' : ''}`}>
          <Icon name="clock" size={13} /> {due.text}
        </span>
      )}
    </div>
  );
}

const STEPS = ['pending', 'in_progress', 'completed'];
function ReqProgress({ status }) {
  if (status === 'rejected') return null;
  const idx = STEPS.indexOf(status);
  return (
    <div className="reqsteps">
      {['ثبت', 'رسیدگی', 'انجام'].map((label, i) => (
        <div key={label} className={`reqstep${i <= idx ? ' done' : ''}${i === idx ? ' current' : ''}`}>
          <span className="reqstep-dot" />
          <span className="reqstep-label">{label}</span>
        </div>
      ))}
    </div>
  );
}

function NewRequestForm({ kinds, topics = [], onDone }) {
  const options = kinds.length ? kinds : [{ id: 'support', label: 'پشتیبانی' }];
  const [kind, setKind] = useState(options.some((k) => k.id === 'support') ? 'support' : options[0].id);
  const [subject, setSubject] = useState('');
  const [body, setBody] = useState('');
  const [priority, setPriority] = useState('normal');
  const [topic, setTopic] = useState('');
  const [carId, setCarId] = useState('');
  const [cars, setCars] = useState([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  // Only vehicles this seat can already open: the server refuses any other,
  // so offering one would be offering a dead end.
  useEffect(() => {
    let cancelled = false;
    fetchGrantedFleet()
      .then((list) => { if (!cancelled) setCars(list || []); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  const submit = async () => {
    if (!subject.trim()) { setErr('موضوع درخواست الزامی است.'); return; }
    setBusy(true); setErr('');
    try {
      await teamApi.createRequest({
        kind, subject: subject.trim(), body: body.trim(), priority,
        topic: topic || undefined,
        car_id: carId ? Number(carId) : undefined,
      });
      onDone?.();
    } catch (e) { setErr(friendlyError(e, 'ثبت درخواست ناموفق بود.')); }
    finally { setBusy(false); }
  };

  return (
    <div className="reqform glass">
      <div className="reqform-row">
        <label htmlFor="req-kind">نوع درخواست</label>
        <select id="req-kind" value={kind} onChange={(e) => setKind(e.target.value)}>
          {options.map((k) => <option key={k.id} value={k.id}>{k.label}</option>)}
        </select>
      </div>
      {topics.length > 0 && (
        <div className="reqform-row">
          <label htmlFor="req-topic">دستهٔ مشکل</label>
          <select id="req-topic" value={topic} onChange={(e) => setTopic(e.target.value)}>
            <option value="">انتخاب نشده</option>
            {topics.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
          </select>
        </div>
      )}
      {cars.length > 0 && (
        <div className="reqform-row">
          <label htmlFor="req-car">خودرو (اختیاری)</label>
          <select id="req-car" value={carId} onChange={(e) => setCarId(e.target.value)}>
            <option value="">مربوط به خودروی خاصی نیست</option>
            {cars.map((c) => (
              <option key={c.id} value={c.id}>
                {[c.brand_name, c.car_name, c.year].filter(Boolean).join(' ')}
              </option>
            ))}
          </select>
        </div>
      )}
      <div className="reqform-row">
        <label htmlFor="req-subject">موضوع</label>
        <input id="req-subject" value={subject} onChange={(e) => setSubject(e.target.value)}
          placeholder="مثلاً: فصل ترمز کمری ۲۰۲۵ باز نمی‌شود" />
      </div>

      {/* Offered while they type, so a question the knowledge base already
          answers need not become a ticket at all. */}
      <KbSuggestions
        query={subject}
        carId={carId ? Number(carId) : null}
        onResolved={() => onDone?.('خوشحالیم که راهنما پاسخ شما بود — تیکتی ثبت نشد.')}
      />
      <div className="reqform-row">
        <label htmlFor="req-body">توضیحات</label>
        <textarea id="req-body" value={body} onChange={(e) => setBody(e.target.value)} rows={3}
          placeholder="چه کاری کردید، چه دیدید، و چه انتظاری داشتید…" />
      </div>
      <div className="reqform-row">
        <label htmlFor="req-priority">اولویت</label>
        <select id="req-priority" value={priority} onChange={(e) => setPriority(e.target.value)}>
          <option value="low">کم</option><option value="normal">عادی</option><option value="high">زیاد</option>
        </select>
      </div>
      {err && <div className="pform-error">{err}</div>}
      <div className="reqform-actions">
        <button className="btn btn-accent" disabled={busy} onClick={submit} id="req-submit">
          {busy ? 'در حال ثبت…' : 'ثبت درخواست'}
        </button>
      </div>
    </div>
  );
}
