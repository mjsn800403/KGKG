'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import Icon from './Icon';
import TicketThread from './TicketThread';
import CsatPrompt from './CsatPrompt';
import { teamApi, getPortalUser } from '../utils/api';
import useEventStream from '../utils/useEventStream';
import { canRate, dueText, faNum, slaLabel, slaTone, sourceLabel } from '../lib/support';
import { friendlyError } from '../lib/friendlyError';

// The customer's side of the support desk.
//
// This page used to be manager-only, because the whole API was: a seat without
// can_manage_team got 403 everywhere, so an ordinary user with a problem had
// only the telephone. Now any seat can open a support request and hold a
// conversation about it here. The kinds offered come from the server's `meta`
// rather than a list in this file, so the manager-only commercial kinds are
// never even shown to someone who would be refused.

function fmtDate(iso) {
  try { return new Date(iso).toLocaleString('fa-IR', { dateStyle: 'short', timeStyle: 'short' }); }
  catch { return iso; }
}
function statusClass(s) {
  return { pending: 'warn', in_progress: 'info', completed: 'ok', rejected: 'bad' }[s] || 'warn';
}

export default function RequestsView() {
  const [items, setItems] = useState([]);
  const [meta, setMeta] = useState({ kinds: [], can_manage_team: false });
  const [openId, setOpenId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const [toast, setToast] = useState(null);
  const [err, setErr] = useState('');
  const toastTimer = useRef(null);

  const load = useCallback(async () => {
    try {
      const d = await teamApi.requests();
      setItems(d.requests || []);
      setMeta(d.meta || { kinds: [] });
      setErr('');
    } catch (e) { setErr(friendlyError(e)); }
  }, []);
  useEffect(() => { load(); }, [load]);

  // A closed row needs no clearing: every read of `detail` checks that it
  // belongs to the row being rendered, so a stale one is simply ignored.
  const loadDetail = useCallback(async (id) => {
    if (!id) return;
    try {
      const d = await teamApi.request(id);
      setDetail(d.request || null);
    } catch (e) { setErr(friendlyError(e)); }
  }, []);

  // Opening a row fetches its thread from the click, not from an effect
  // mirroring `openId`: the fetch belongs to the action that caused it, and the
  // live event handler below calls the same function.
  const toggle = useCallback((id) => {
    setOpenId((cur) => (cur === id ? null : id));
    if (openId !== id) loadDetail(id);
  }, [openId, loadDetail]);

  const flashToast = useCallback((msg, tone = 'ok') => {
    setToast({ msg, tone });
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 5000);
  }, []);

  // Live: the agent's progress and replies appear without a refresh.
  useEventStream({
    admin: false,
    onEvent: (evt) => {
      if (!String(evt.type || '').startsWith('request.')) return;
      const req = evt.payload?.request;
      load();
      if (req && openId === req.id) loadDetail(openId);
      if (evt.type === 'request.updated' && req) {
        if (req.status === 'completed') flashToast(`درخواست «${req.subject}» انجام شد ✓`, 'ok');
        else if (req.status === 'rejected') flashToast(`درخواست «${req.subject}» رد شد`, 'bad');
        else if (req.status === 'in_progress') flashToast(`رسیدگی به «${req.subject}» آغاز شد`, 'info');
      }
      if (evt.type === 'request.message' && req) flashToast(`پاسخ تازه روی «${req.subject}»`, 'info');
    },
  });

  const reply = async (body) => {
    const wasClosed = detail && ['completed', 'rejected'].includes(detail.status);
    await teamApi.replyRequest(openId, body);
    await Promise.all([load(), loadDetail(openId)]);
    flashToast(wasClosed ? 'درخواست بازگشایی شد و پیام شما ثبت شد' : 'پیام شما ثبت شد', 'ok');
  };

  const rate = async (csat) => {
    await teamApi.rateRequest(openId, csat);
    await Promise.all([load(), loadDetail(openId)]);
    flashToast('ممنون از بازخوردتان 🙏', 'ok');
  };

  return (
    <div className="reqview">
      <div className="reqview-head">
        <div>
          <h1 className="rt-title">پشتیبانی و درخواست‌ها</h1>
          <p className="rt-sub">
            مشکل یا پرسش خود را همین‌جا ثبت کنید، گفت‌وگو را دنبال کنید و مهلت پاسخ را ببینید.
          </p>
        </div>
        <button className="btn btn-accent" onClick={() => setShowForm((s) => !s)} id="req-new">
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
              onDone={() => { setShowForm(false); load(); flashToast('درخواست شما ثبت شد', 'ok'); }}
            />
          </motion.div>
        )}
      </AnimatePresence>

      {items.length === 0 ? (
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
      ) : (
        <ul className="inbox-list">
          <AnimatePresence initial={false}>
            {items.map((r) => {
              const isOpen = openId === r.id;
              const shown = isOpen && detail?.id === r.id ? detail : r;
              return (
                <motion.li key={r.id} layout className="inbox-item glass"
                  initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
                  <button
                    type="button"
                    className="inbox-item-head inbox-item-toggle"
                    aria-expanded={isOpen}
                    onClick={() => toggle(r.id)}
                  >
                    <span className={`rt-pill rt-pill-${statusClass(shown.status)}`}>{shown.status_label}</span>
                    <b className="inbox-subject">{shown.subject}</b>
                    <span className="inbox-kind">{shown.kind_label}</span>
                    {shown.source && shown.source !== 'portal' && (
                      <span className="tkt-src">از {sourceLabel(shown.source)}</span>
                    )}
                    {shown.reopen_count > 0 && <span className="tkt-reopen">بازگشایی‌شده</span>}
                    <span className="inbox-when">{fmtDate(shown.created_at)}</span>
                    <Icon name="chevron" size={15} className={`inbox-chev${isOpen ? ' up' : ''}`} />
                  </button>

                  <SlaRow req={shown} />
                  <ReqProgress status={shown.status} />

                  <AnimatePresence>
                    {isOpen && (
                      <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }}
                        exit={{ opacity: 0, height: 0 }} style={{ overflow: 'hidden' }}>
                        <div className="tkt-detail">
                          {shown.messages ? (
                            <TicketThread
                              messages={shown.messages}
                              onSend={reply}
                              placeholder={
                                ['completed', 'rejected'].includes(shown.status)
                                  ? 'اگر مشکل حل نشده، همین‌جا بنویسید تا درخواست بازگشایی شود…'
                                  : 'پاسخ یا توضیح بیشتر…'
                              }
                              note={
                                ['completed', 'rejected'].includes(shown.status)
                                  ? 'ارسال پیام روی یک درخواست بسته، آن را بازگشایی می‌کند.'
                                  : null
                              }
                            />
                          ) : (
                            <p className="tkt-thread-empty">در حال بارگذاری گفت‌وگو…</p>
                          )}

                          {shown.csat && (
                            <div className="csat-done">
                              امتیاز شما ثبت شده است: <b>{faNum(shown.csat.score)} از ۵</b>
                              {shown.csat.comment ? ` — «${shown.csat.comment}»` : ''}
                            </div>
                          )}
                          {/* Read at the moment it is needed: this branch only
                              renders after the reader opened the row, so it never
                              runs during the server render and cannot create a
                              hydration gap. */}
                          {canRate(shown, getPortalUser()) && <CsatPrompt onRate={rate} />}

                          {['pending', 'in_progress'].includes(shown.status) && (
                            <div className="inbox-actions">
                              <button className="btn" onClick={async () => {
                                await teamApi.cancelRequest(r.id);
                                await Promise.all([load(), loadDetail(r.id)]);
                              }}>
                                انصراف از درخواست
                              </button>
                            </div>
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

function NewRequestForm({ kinds, onDone }) {
  const options = kinds.length ? kinds : [{ id: 'support', label: 'پشتیبانی' }];
  const [kind, setKind] = useState(options.some((k) => k.id === 'support') ? 'support' : options[0].id);
  const [subject, setSubject] = useState('');
  const [body, setBody] = useState('');
  const [priority, setPriority] = useState('normal');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  const submit = async () => {
    if (!subject.trim()) { setErr('موضوع درخواست الزامی است.'); return; }
    setBusy(true); setErr('');
    try {
      await teamApi.createRequest({ kind, subject: subject.trim(), body: body.trim(), priority });
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
      <div className="reqform-row">
        <label htmlFor="req-subject">موضوع</label>
        <input id="req-subject" value={subject} onChange={(e) => setSubject(e.target.value)}
          placeholder="مثلاً: فصل ترمز کمری ۲۰۲۵ باز نمی‌شود" />
      </div>
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
