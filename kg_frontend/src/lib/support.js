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
