// Staff-side calls for the visitor support chat (inside «میز پشتیبانی»).
// Uses the admin session token already held by the console; never the visitor
// token. Throws Error with `.unauthorized` / `.status`; the message is the
// server's, so callers show it through friendlyError.
import { getAdminToken } from './api';
import { buildQuery } from '../support-chat/admin/logic';

const BASE = (process.env.NEXT_PUBLIC_API_BASE || '/kg-api').replace(/\/+$/, '');
const ROOT = '/api/admin/support-chat';

async function call(method, path, body) {
  const token = getAdminToken();
  const res = await fetch(`${BASE}${ROOT}${path}`, {
    method,
    cache: 'no-store',
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data?.error || `support chat: ${res.status}`);
    err.status = res.status;
    err.code = data?.code;
    err.unauthorized = res.status === 401;
    throw err;
  }
  return data;
}

const t = (id) => `/threads/${encodeURIComponent(id)}`;

export const supportChatApi = {
  list: (params) => call('GET', `/threads/${buildQuery(params)}`),
  detail: (id, params) => call('GET', `${t(id)}/${buildQuery(params)}`),
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
