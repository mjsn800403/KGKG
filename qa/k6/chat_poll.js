// Load check for the anonymous chat poll path (docs/superpowers/specs/
// 2026-11-02-customer-communication-design.md §5.3). Visitors poll instead of
// holding SSE streams because the backend has 24 request threads in total.
//
//   k6 run -e BASE=http://127.0.0.1:8000 qa/k6/chat_poll.js
//
// Run it against a local or staging stack, never production. Thread creation is
// rate-limited per IP (5 / 10 min), so point it at a stack started with
// KG_RL_CHAT_CREATE=0/0 KG_RL_CHAT_POLL=0/0 and KG_RL_STATUS... or it will
// measure the limiter instead of the poll. Creating threads needs Turnstile to
// pass (DEBUG without TURNSTILE_SECRET).
import http from 'k6/http';
import { check, sleep } from 'k6';

const BASE = __ENV.BASE || 'http://127.0.0.1:8000';

export const options = {
  vus: Number(__ENV.VUS || 100),
  duration: __ENV.DURATION || '60s',
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<300'],
  },
};

export function setup() { return {}; }

export default function () {
  const created = http.post(`${BASE}/api/chat/threads/`,
    JSON.stringify({ message: 'load test', client_id: `k6-${__VU}-${__ITER}` }),
    { headers: { 'Content-Type': 'application/json' } });
  if (!check(created, { 'created 201': (r) => r.status === 201 })) { sleep(3); return; }
  const { thread_id: id, token } = created.json();
  let after = 0;
  for (let i = 0; i < 20; i++) {
    const r = http.get(`${BASE}/api/chat/threads/${id}/messages/?after=${after}`,
      { headers: { 'X-Chat-Token': token } });
    check(r, { 'poll 200': (x) => x.status === 200 });
    sleep(3);
  }
}
