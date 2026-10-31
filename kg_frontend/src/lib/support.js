// Presentation rules for the support desk (api/requests_api.py, api/sla.py).
//
// These are pure on purpose. An SLA state decides whether a customer is told
// their ticket is on time or late, so the rule deserves tests of its own
// rather than being spelled out inside JSX. The vocabulary mirrors the
// backend's exactly: a state the API can return and this file cannot name is
// a bug, and SLA_STATES is what pins that.

export const SLA_STATES = ['met', 'breached', 'pending'];

const TONES = { met: 'ok', breached: 'bad', pending: 'info' };
const SLA_LABELS = {
  met: 'در مهلت',
  breached: 'از مهلت گذشته',
  pending: 'در مهلت، در انتظار',
};

/** 'ok' | 'bad' | 'info' — or null for 'untracked' and anything unknown, so
 *  a ticket with no target renders no badge at all rather than a wrong one. */
export function slaTone(state) {
  return TONES[state] || null;
}

export function slaLabel(state) {
  return SLA_LABELS[state] || '';
}

const SOURCE_LABELS = {
  portal: 'سامانه',
  phone: 'تلفن',
  email: 'ایمیل',
  sms: 'پیامک',
  in_person: 'حضوری',
};

/** An unknown channel shows its own key: the reader sees something true, and
 *  the gap is obvious to whoever added the channel without a label. */
export function sourceLabel(source) {
  if (!source) return '';
  return SOURCE_LABELS[source] || String(source);
}

const MIN = 60 * 1000;
const HOUR = 60 * MIN;
const DAY = 24 * HOUR;

function spanText(ms) {
  if (ms >= DAY) {
    const d = Math.round(ms / DAY);
    return `${faNum(d)} روز`;
  }
  if (ms >= HOUR) {
    const h = Math.round(ms / HOUR);
    return `${faNum(h)} ساعت`;
  }
  const m = Math.max(1, Math.round(ms / MIN));
  return `${faNum(m)} دقیقه`;
}

/** { overdue, text } for an SLA due date, or null when there is no usable
 *  date — the caller renders nothing rather than "Invalid Date". */
export function dueText(iso, now = new Date()) {
  if (!iso) return null;
  const due = new Date(iso);
  if (Number.isNaN(due.getTime())) return null;
  const delta = due.getTime() - new Date(now).getTime();
  return delta >= 0
    ? { overdue: false, text: `${spanText(delta)} مانده` }
    : { overdue: true, text: `${spanText(-delta)} گذشته` };
}

const CLOSED = ['completed', 'rejected'];

/** Whether this viewer may rate this ticket. Mirrors api/requests_api._seat_csat:
 *  closed, not yet rated, and either the person who filed it or — for a ticket
 *  the platform side logged, which has no filer — a manager. The server
 *  enforces this too; the check here only keeps the prompt from appearing
 *  where it would be refused. */
export function canRate(req, viewer) {
  if (!req || !viewer) return false;
  if (!CLOSED.includes(req.status)) return false;
  if (req.csat) return false;
  if (req.created_by) return req.created_by.id === viewer.id;
  return Boolean(viewer.can_manage_team);
}

const TRANSITIONS = {
  pending: [['in_progress', 'شروع رسیدگی'], ['rejected', 'رد درخواست']],
  in_progress: [['completed', 'تکمیل'], ['rejected', 'رد درخواست']],
  completed: [['in_progress', 'بازگشایی']],
  rejected: [['in_progress', 'بازگشایی']],
};

/** [[status, label], …] an agent may move this ticket to. */
export function nextStatuses(status) {
  return TRANSITIONS[status] || [];
}

const FA_DIGITS = '۰۱۲۳۴۵۶۷۸۹';

export function faNum(n) {
  return String(n).replace(/\d/g, (d) => FA_DIGITS[Number(d)]);
}

/** A duration in minutes. null stays an em dash: the metrics API returns null
 *  rather than 0 when nothing was measured, and that distinction must survive
 *  into the interface or the dashboard lies. */
export function fmtMinutes(minutes) {
  if (minutes === null || minutes === undefined || Number.isNaN(minutes)) return '—';
  return spanText(Math.max(0, minutes) * MIN);
}

export function fmtHours(hours) {
  if (hours === null || hours === undefined || Number.isNaN(hours)) return '—';
  return spanText(Math.max(0, hours) * HOUR);
}

/** A 0..1 rate as a Persian percentage; null stays an em dash, never '۰٪'. */
export function ratio(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return `${faNum(Math.round(value * 100))}٪`;
}

const FACES = { 1: '😠', 2: '🙁', 3: '😐', 4: '🙂', 5: '😀' };

export function csatFace(score) {
  return FACES[score] || '';
}

// --- The conversational desk ------------------------------------------------
// Pure functions, deliberately. This project's frontend suite is node:test over
// plain modules — there is no renderer — so logic that lives in a component
// cannot be tested at all. Anything here worth getting right is therefore kept
// out of the components and tested directly.

const TOPIC_LABELS = {
  missing_document: 'مستند موجود نیست',
  content_wrong: 'محتوا نادرست یا نامفهوم است',
  access_problem: 'مشکل دسترسی',
  assistant_wrong: 'پاسخ دستیار نادرست بود',
  error_or_slow: 'خطا یا کندی سامانه',
  billing: 'مالی و اشتراک',
  other: 'سایر',
};
export const UNCATEGORISED = 'دسته‌بندی‌نشده';

/** A topic's Persian label. An unset topic is named, never left blank: a gap
 *  the reader can see is a gap somebody can close. */
export function topicLabel(topic) {
  if (!topic) return UNCATEGORISED;
  return TOPIC_LABELS[topic] || topic;
}

/** Index of the first message the viewer has not seen, or -1.
 *  The server counts unread; the position is derived from that count against
 *  the thread, so the two can never disagree about how many are unread. */
export function firstUnreadIndex(messages, unreadCount) {
  const n = Number(unreadCount) || 0;
  if (!Array.isArray(messages) || messages.length === 0 || n <= 0) return -1;
  return Math.max(0, messages.length - n);
}

/** `[{ day, messages }]` in the thread's own order, split at each date change.
 *  Grouping by calendar day is what makes a long conversation readable. */
export function groupByDay(messages) {
  if (!Array.isArray(messages) || messages.length === 0) return [];
  const groups = [];
  for (const m of messages) {
    const day = String(m.created_at || '').slice(0, 10);
    const last = groups[groups.length - 1];
    if (last && last.day === day) last.messages.push(m);
    else groups.push({ day, messages: [m] });
  }
  return groups;
}

/** What this ticket wants from the person looking at it.
 *
 *  The order is the whole point. Unread outranks awaiting because something
 *  was said that nobody has read; a closed ticket outranks both because it
 *  wants nothing. These are three different facts, and the single "open"
 *  signal this replaces could express none of them. */
export function activityState(req) {
  if (!req) return 'closed';
  if (['completed', 'rejected'].includes(req.status)) return 'closed';
  if ((Number(req.unread_count) || 0) > 0) return 'unread';
  return req.awaiting_reply ? 'awaiting_us' : 'awaiting_them';
}

/** The second line of a ticket row: how it is categorised, falling back to the
 *  request type when it is not. */
export function rowSubtitle(req) {
  if (!req) return '';
  const parts = [];
  if (req.topic) parts.push(req.topic_label || topicLabel(req.topic));
  if (req.car?.name) parts.push(req.car.name);
  if (parts.length === 0 && req.kind_label) parts.push(req.kind_label);
  return parts.join(' · ');
}
