// Pure helpers for the staff conversations tab (no React, no network).

export const STATUS_LABELS = {
  open: 'باز', waiting_staff: 'منتظر پشتیبانی', waiting_customer: 'منتظر مشتری', closed: 'بسته', spam: 'اسپم',
};
export const INTENT_LABELS = { sales: 'فروش', demo: 'دمو', technical: 'فنی', other: 'سایر' };
export const PRIORITY_LABELS = { low: 'کم', normal: 'عادی', high: 'زیاد', urgent: 'فوری' };
export const FILTERS = [
  { id: 'active', label: 'فعال' },
  { id: 'closed', label: 'بسته' },
  { id: 'spam', label: 'اسپم' },
];

/** `?a=1&b=2` without empty values, so a cleared filter never becomes `?q=`. */
export function buildQuery(params = {}) {
  const qs = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v !== '' && v !== null && v !== undefined),
  ).toString();
  return qs ? `?${qs}` : '';
}

/** Availability follows human activity, not an open tab: true only when the
 * person did something (key, pointer, scroll) within `awayAfterMs`. */
export function isActive(lastInputAt, now, awayAfterMs = 10 * 60 * 1000) {
  return typeof lastInputAt === 'number' && now - lastInputAt < awayAfterMs;
}

export function tabTitle(base, unread) {
  return unread > 0 ? `(${unread}) ${base}` : base;
}

/** Whether an admin-feed event concerns the support chat. */
export function isChatEvent(evt) {
  return typeof evt?.type === 'string' && evt.type.startsWith('support_chat.');
}

/** The thread id an event is about, or null. */
export function eventThreadId(evt) {
  const id = evt?.payload?.thread_id;
  return typeof id === 'string' ? id : null;
}

/** Messages to show: server order, internal notes flagged, no duplicates by id. */
export function mergeMessages(current, incoming) {
  const seen = new Map(current.map((m) => [m.id, m]));
  for (const m of incoming) seen.set(m.id, m);
  return [...seen.values()].sort((a, b) => a.id - b.id);
}

/** Next heartbeat body, or null to skip the request entirely (tab hidden is
 * still a valid "open but idle" ping, so only a signed-out console skips). */
export function heartbeatBody({ signedIn, lastInputAt, now, awayAfterMs }) {
  if (!signedIn) return null;
  return { active: isActive(lastInputAt, now, awayAfterMs) };
}
