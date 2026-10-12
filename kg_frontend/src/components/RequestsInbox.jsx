'use client';

import { useCallback, useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { adminApi } from '../utils/api';
import useEventStream from '../utils/useEventStream';

function fmtDate(iso) {
  try { return new Date(iso).toLocaleString('fa-IR', { dateStyle: 'short', timeStyle: 'short' }); }
  catch { return iso; }
}

const STATUS_FILTERS = [
  { id: '', label: 'همه' },
  { id: 'pending', label: 'در انتظار' },
  { id: 'in_progress', label: 'در حال انجام' },
  { id: 'completed', label: 'انجام‌شده' },
  { id: 'rejected', label: 'رد‌شده' },
];
const NEXT = {
  pending: [['in_progress', 'شروع رسیدگی'], ['rejected', 'رد']],
  in_progress: [['completed', 'تکمیل'], ['rejected', 'رد']],
  completed: [], rejected: [['in_progress', 'بازگشایی']],
};
function statusClass(s) {
  return { pending: 'warn', in_progress: 'info', completed: 'ok', rejected: 'bad' }[s] || 'warn';
}

export default function RequestsInbox() {
  const [items, setItems] = useState([]);
  const [counts, setCounts] = useState({});
  const [filter, setFilter] = useState('');
  const [busy, setBusy] = useState(null);
  const [note, setNote] = useState({});

  const load = useCallback(async () => {
    try {
      const d = await adminApi.companyRequests(filter ? { status: filter } : {});
      setItems(d.requests || []);
      setCounts(d.counts || {});
    } catch { /* keep */ }
  }, [filter]);
  useEffect(() => { load(); }, [load]);

  // Live: a manager filing or an admin action anywhere refreshes the inbox.
  useEventStream({
    admin: true,
    onEvent: (evt) => {
      if (evt.type === 'request.created' || evt.type === 'request.updated') load();
    },
  });

  const act = async (id, status) => {
    setBusy(id);
    try {
      await adminApi.setCompanyRequest(id, { status, admin_note: note[id] || undefined });
      setNote((n) => ({ ...n, [id]: '' }));
      await load();
    } catch (e) { alert(e.message); }
    finally { setBusy(null); }
  };

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

      {items.length === 0 ? (
        <div className="inbox-empty glass">درخواستی در این نما وجود ندارد.</div>
      ) : (
        <ul className="inbox-list">
          <AnimatePresence initial={false}>
            {items.map((r) => (
              <motion.li key={r.id} layout className="inbox-item glass"
                initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, scale: 0.98 }}>
                <div className="inbox-item-head">
                  <span className={`rt-pill rt-pill-${statusClass(r.status)}`}>{r.status_label}</span>
                  <b className="inbox-subject">{r.subject}</b>
                  <span className="inbox-kind">{r.kind_label}</span>
                  <span className="inbox-when">{fmtDate(r.created_at)}</span>
                </div>
                <div className="inbox-meta">
                  <span>شرکت: <b>{r.company?.name}</b></span>
                  {r.created_by?.name && <span>ثبت: {r.created_by.name}</span>}
                  {r.priority === 'high' && <span className="inbox-prio">اولویت بالا</span>}
                </div>
                {r.body && <p className="inbox-body">{r.body}</p>}
                {r.payload && Object.keys(r.payload).length > 0 && (
                  <pre className="inbox-payload">{JSON.stringify(r.payload, null, 1)}</pre>
                )}
                {r.admin_note && <div className="inbox-adminnote">پاسخ: {r.admin_note}</div>}
                {NEXT[r.status]?.length > 0 && (
                  <div className="inbox-actions">
                    <input className="inbox-note" placeholder="یادداشت پاسخ (اختیاری)"
                      value={note[r.id] || ''} onChange={(e) => setNote((n) => ({ ...n, [r.id]: e.target.value }))} />
                    {NEXT[r.status].map(([st, label]) => (
                      <button key={st} className={`btn inbox-act inbox-act-${statusClass(st)}`}
                        disabled={busy === r.id} onClick={() => act(r.id, st)}>
                        {busy === r.id ? '...' : label}
                      </button>
                    ))}
                  </div>
                )}
              </motion.li>
            ))}
          </AnimatePresence>
        </ul>
      )}
    </div>
  );
}
