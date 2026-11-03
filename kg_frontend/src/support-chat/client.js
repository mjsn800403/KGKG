// Typed client for the anonymous support-chat API. It never throws: every call
// resolves to {ok:true, status, data} or {ok:false, kind, status, ...}.
//   kind: rate_limited (retryAfter s) | closed | conflict (code) | not_found |
//         invalid (message, server's Persian text) | network | server

const TOKEN_HEADER = 'X-Support-Chat-Token';

function retryAfterOf(res, data) {
  const h = Number(res.headers?.get?.('Retry-After'));
  if (Number.isFinite(h) && h > 0) return Math.ceil(h);
  const d = Number(data?.retry_after);
  return Number.isFinite(d) && d > 0 ? Math.ceil(d) : 30;
}

export function createClient({ fetch: doFetch, base = '/kg-api' } = {}) {
  const root = String(base).replace(/\/+$/, '');

  async function call(method, path, { token, body, signal } = {}) {
    let res;
    try {
      res = await doFetch(`${root}${path}`, {
        method,
        cache: 'no-store',
        signal,
        headers: {
          ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
          ...(token ? { [TOKEN_HEADER]: token } : {}),
        },
        body: body !== undefined ? JSON.stringify(body) : undefined,
      });
    } catch (e) {
      return { ok: false, kind: 'network', status: 0, aborted: e?.name === 'AbortError' };
    }
    const data = await res.json().catch(() => ({}));
    if (res.ok) return { ok: true, status: res.status, data };
    const status = res.status;
    if (status === 429) return { ok: false, kind: 'rate_limited', status, retryAfter: retryAfterOf(res, data) };
    if (status === 404) return { ok: false, kind: 'not_found', status };
    if (status === 409) {
      return data?.code === 'closed'
        ? { ok: false, kind: 'closed', status, canReopen: !!data.can_reopen }
        : { ok: false, kind: 'conflict', status, code: data?.code || '' };
    }
    if (status >= 500) return { ok: false, kind: 'server', status };
    return { ok: false, kind: 'invalid', status, message: typeof data?.error === 'string' ? data.error : '' };
  }

  const tid = (id) => encodeURIComponent(id);
  return {
    // intent asks about one intent (sales|demo|technical|other); omitted asks about any.
    status: (intent, signal) => call('GET',
      `/api/support-chat/status/${intent ? `?intent=${encodeURIComponent(intent)}` : ''}`, { signal }),
    create: ({ token, message, clientId, intent, page, referrer, turnstileToken, contact }) =>
      call('POST', '/api/support-chat/threads/', {
        body: {
          token, message, client_id: clientId, intent, page, referrer,
          turnstile_token: turnstileToken, ...(contact ? { contact } : {}),
        },
      }),
    poll: (threadId, token, after = 0, signal) =>
      call('GET', `/api/support-chat/threads/${tid(threadId)}/messages/?after=${Number(after) || 0}`, { token, signal }),
    send: (threadId, token, { message, clientId }) =>
      call('POST', `/api/support-chat/threads/${tid(threadId)}/messages/`,
        { token, body: { message, client_id: clientId } }),
    contact: (threadId, token, contact) =>
      call('PATCH', `/api/support-chat/threads/${tid(threadId)}/contact/`, { token, body: contact }),
    reopen: (threadId, token) =>
      call('POST', `/api/support-chat/threads/${tid(threadId)}/reopen/`, { token, body: {} }),
    rate: (threadId, token, score) =>
      call('POST', `/api/support-chat/threads/${tid(threadId)}/csat/`, { token, body: { score } }),
  };
}
