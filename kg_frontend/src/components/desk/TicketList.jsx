'use client';

import { motion } from 'motion/react';
import Icon from '../Icon';
import { activityState, faNum, rowSubtitle } from '../../lib/support';

// The worklist. Presentational on purpose: it decides nothing about what is
// selected or loaded, so the same component serves the customer view and the
// desk inbox.
//
// Rows are ordered by last activity, not by creation. A ticket somebody replied
// to five minutes ago belongs at the top even if it was filed last month —
// ordering by creation is what turns a list into an archive nobody scrolls.

function initials(name) {
  const text = (name || '').trim();
  if (!text) return '—';
  const parts = text.split(/\s+/).slice(0, 2);
  return parts.map((p) => p[0]).join('');
}

function relTime(iso) {
  if (!iso) return '';
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return 'همین حالا';
  if (mins < 60) return `${faNum(mins)} دقیقه پیش`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${faNum(hours)} ساعت پیش`;
  return `${faNum(Math.round(hours / 24))} روز پیش`;
}

const STATE_CLASS = {
  unread: 'tl-unread',
  awaiting_us: 'tl-awaiting',
  awaiting_them: 'tl-waiting',
  closed: 'tl-closed',
};

export default function TicketList({
  items = [],
  selectedId = null,
  onSelect,
  onLoadMore = null,
  loading = false,
  emptyNode = null,
  showCompany = false,
}) {
  if (items.length === 0) return emptyNode;

  return (
    <ul className="tl" role="listbox" aria-label="فهرست تیکت‌ها">
      {items.map((r) => {
        const state = activityState(r);
        const unread = Number(r.unread_count) || 0;
        const who = showCompany ? r.company?.name : (r.created_by?.name || '');
        return (
          <motion.li
            key={r.id}
            layout
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            className={`tl-row ${STATE_CLASS[state]}${selectedId === r.id ? ' tl-on' : ''}`}
          >
            <button
              type="button"
              role="option"
              aria-selected={selectedId === r.id}
              className="tl-btn"
              onClick={() => onSelect?.(r.id)}
            >
              <span className="tl-ava" aria-hidden="true">{initials(who || r.subject)}</span>
              <span className="tl-main">
                <span className="tl-top">
                  <b className="tl-subject">{r.subject}</b>
                  <span className="tl-when">{relTime(r.last_message?.at || r.created_at)}</span>
                </span>
                <span className="tl-sub">
                  {who && <span className="tl-who">{who}</span>}
                  <span className="tl-cat">{rowSubtitle(r)}</span>
                </span>
                <span className="tl-tags">
                  <span className={`rt-pill rt-pill-${
                    { pending: 'warn', in_progress: 'info', completed: 'ok', rejected: 'bad' }[r.status] || 'warn'
                  }`}>{r.status_label}</span>
                  {state === 'awaiting_us' && <span className="tkt-wait">منتظر پاسخ ما</span>}
                  {r.escalated_at && <span className="tkt-esc">ارجاع‌شده</span>}
                  {r.reopen_count > 0 && <span className="tkt-reopen">بازگشایی ×{faNum(r.reopen_count)}</span>}
                </span>
              </span>
              {unread > 0 && (
                <span className="tl-dot" aria-label={`${faNum(unread)} پیام خوانده‌نشده`}>
                  {faNum(unread)}
                </span>
              )}
            </button>
          </motion.li>
        );
      })}
      {onLoadMore && (
        <li className="tl-more">
          <button type="button" className="btn" disabled={loading} onClick={onLoadMore}>
            <Icon name="chevron" size={14} /> {loading ? 'در حال بارگذاری…' : 'موارد بیشتر'}
          </button>
        </li>
      )}
    </ul>
  );
}
