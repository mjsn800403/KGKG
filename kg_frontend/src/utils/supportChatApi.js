// Staff-side calls for the visitor support chat (inside «میز پشتیبانی»).
// Uses the admin session token already held by the console; never the visitor
// token. Throws Error with `.unauthorized` / `.status`; the message is the
// server's, so callers show it through friendlyError.
import { getAdminToken } from './api';
import { buildQuery } from '../support-chat/admin/logic';

const BASE = (process.env.NEXT_PUBLIC_API_BASE || '/kg-api').replace(/\/+$/, '');
const ROOT = '/api/admin/support-chat';

// `background: true` marks an automatic call (timer or event-driven reload): the
// server then does not slide the 12 h idle window for it, so only a person
// acting keeps a console signed in.
async function call(method, path, body, { background = false } = {}) {
  const token = getAdminToken();
  const res = await fetch(`${BASE}${ROOT}${path}`, {
    method,
    cache: 'no-store',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(background ? { 'X-Kg-Background': '1' } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data?.error || `support chat: ${res.status}`);
    err.status = res.status;
    err.code = data?.code;
    err.unauthorized = res.status === 401;
    // Tell the console: the session is over, sign in again (see admin/page.jsx).
    if (err.unauthorized) window.dispatchEvent(new Event('kg:admin-unauthorized'));
    throw err;
  }
  return data;
}

const t = (id) => `/threads/${encodeURIComponent(id)}`;

export const supportChatApi = {
  list: (params, opts) => call('GET', `/threads/${buildQuery(params)}`, undefined, opts),
  detail: (id, params, opts) => call('GET', `${t(id)}/${buildQuery(params)}`, undefined, opts),
  reply: (id, message, internal = false) => call('POST', `${t(id)}/reply/`, { message, internal }),
  seen: (id) => call('POST', `${t(id)}/seen/`, {}),
  assign: (id, admin) => call('POST', `${t(id)}/assign/`, { admin }),
  priority: (id, priority) => call('POST', `${t(id)}/priority/`, { priority }),
  intent: (id, intent) => call('POST', `${t(id)}/intent/`, { intent }),
  close: (id) => call('POST', `${t(id)}/close/`, {}),
  reopen: (id) => call('POST', `${t(id)}/reopen/`, {}),
  spam: (id) => call('POST', `${t(id)}/spam/`, {}),
  restore: (id) => call('POST', `${t(id)}/restore/`, {}),
  presence: () => call('GET', '/presence/'),
  setPresence: (status) => call('PUT', '/presence/', { status }),
  heartbeat: (active) => call('POST', '/presence/heartbeat/', { active }),
};
