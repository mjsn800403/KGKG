'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import Icon from './Icon';
import { teamApi } from '../utils/api';
import useEventStream from '../utils/useEventStream';

const KINDS = [
  { id: 'vehicle_access', label: 'درخواست دسترسی به خودرو' },
  { id: 'seats', label: 'افزایش ظرفیت کاربران' },
  { id: 'ai_assistant', label: 'فعال‌سازی دستیار هوشمند' },
  { id: 'documents', label: 'افزودن بستهٔ مستندات' },
  { id: 'support', label: 'پشتیبانی' },
  { id: 'other', label: 'سایر' },
];
function statusClass(s) {
  return { pending: 'warn', in_progress: 'info', completed: 'ok', rejected: 'bad' }[s] || 'warn';
}
function fmtDate(iso) {
  try { return new Date(iso).toLocaleString('fa-IR', { dateStyle: 'short', timeStyle: 'short' }); }
  catch { return iso; }
}

export default function RequestsView() {
  const [items, setItems] = useState([]);
  const [openCount, setOpenCount] = useState(0);
  const [showForm, setShowForm] = useState(false);
  const [toast, setToast] = useState(null);
  const toastTimer = useRef(null);

  const load = useCallback(async () => {
    try {
      const d = await teamApi.requests();
      setItems(d.requests || []);
      setOpenCount(d.meta?.open_count || 0);
    } catch { /* keep */ }
  }, []);
  useEffect(() => { load(); }, [load]);

  const flashToast = useCallback((msg, tone = 'ok') => {
    setToast({ msg, tone });
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 5000);
  }, []);

  // Live: reflect admin progress on the manager's own requests in real time.
  useEventStream({
    admin: false,
    onEvent: (evt) => {
      if (evt.type !== 'request.updated' && evt.type !== 'request.created') return;
      const req = evt.payload?.request;
      load();
      if (evt.type === 'request.updated' && req) {
        if (req.status === 'completed') flashToast(`درخواست «${req.subject}» انجام شد ✓`, 'ok');
        else if (req.status === 'rejected') flashToast(`درخواست «${req.subject}» رد شد`, 'bad');
        else if (req.status === 'in_progress') flashToast(`رسیدگی به «${req.subject}» آغاز شد`, 'info');
      }
    },
  });

  return (
    <div className="reqview">
      <div className="reqview-head">
        <div>
          <h1 className="rt-title">درخواست‌های شرکت</h1>
          <p className="rt-sub">درخواست‌های خود را ثبت کنید و وضعیت رسیدگی را لحظه‌ای دنبال کنید.</p>
        </div>
        <button className="btn btn-accent" onClick={() => setShowForm((s) => !s)}>
          <Icon name="plus" size={16} /> درخواست جدید
        </button>
      </div>

      <AnimatePresence>
        {showForm && (
          <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }} style={{ overflow: 'hidden' }}>
            <NewRequestForm onDone={() => { setShowForm(false); load(); flashToast('درخواست شما ثبت شد', 'ok'); }} />
          </motion.div>
        )}
      </AnimatePresence>

      {items.length === 0 ? (
        <div className="inbox-empty glass">هنوز درخواستی ثبت نکرده‌اید.</div>
      ) : (
        <ul className="inbox-list">
          <AnimatePresence initial={false}>
            {items.map((r) => (
              <motion.li key={r.id} layout className="inbox-item glass"
                initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
                <div className="inbox-item-head">
                  <span className={`rt-pill rt-pill-${statusClass(r.status)}`}>{r.status_label}</span>
                  <b className="inbox-subject">{r.subject}</b>
                  <span className="inbox-kind">{r.kind_label}</span>
                  <span className="inbox-when">{fmtDate(r.created_at)}</span>
                </div>
                {r.body && <p className="inbox-body">{r.body}</p>}
                {r.admin_note && <div className="inbox-adminnote">پاسخ پشتیبانی: {r.admin_note}</div>}
                <ReqProgress status={r.status} />
                {(r.status === 'pending' || r.status === 'in_progress') && (
                  <div className="inbox-actions">
                    <button className="btn" onClick={async () => { await teamApi.cancelRequest(r.id); load(); }}>
                      انصراف از درخواست
                    </button>
                  </div>
                )}
              </motion.li>
            ))}
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

function NewRequestForm({ onDone }) {
  const [kind, setKind] = useState('support');
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
    } catch (e) { setErr(e.message || 'ثبت ناموفق بود'); }
    finally { setBusy(false); }
  };

  return (
    <div className="reqform glass">
      <div className="reqform-row">
        <label>نوع درخواست</label>
        <select value={kind} onChange={(e) => setKind(e.target.value)}>
          {KINDS.map((k) => <option key={k.id} value={k.id}>{k.label}</option>)}
        </select>
      </div>
      <div className="reqform-row">
        <label>موضوع</label>
        <input value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="مثلاً: نیاز به دسترسی کمری ۲۰۲۵" />
      </div>
      <div className="reqform-row">
        <label>توضیحات</label>
        <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={3} placeholder="جزئیات درخواست…" />
      </div>
      <div className="reqform-row">
        <label>اولویت</label>
        <select value={priority} onChange={(e) => setPriority(e.target.value)}>
          <option value="low">کم</option><option value="normal">عادی</option><option value="high">زیاد</option>
        </select>
      </div>
      {err && <div className="pform-error">{err}</div>}
      <div className="reqform-actions">
        <button className="btn btn-accent" disabled={busy} onClick={submit}>{busy ? 'در حال ثبت…' : 'ثبت درخواست'}</button>
      </div>
    </div>
  );
}
