// Load check for the anonymous chat poll path (docs/superpowers/specs/
// 2026-11-02-customer-communication-design.md §5.3). Visitors poll instead of
// holding SSE streams because the backend has 24 request threads in total.
//
//   k6 run -e BASE=http://127.0.0.1:8000 qa/k6/support_chat_poll.js
//
// Run it against a local or staging stack, never production. Thread creation is
// rate-limited per IP (20 / 10 min) and polls per thread (30 / min), so start
// the stack with KG_SC_CREATE_IP=0/0 for this run or it measures the limiter
// instead of the poll. Creating threads needs Turnstile to pass (DEBUG without
// TURNSTILE_SECRET). Nothing here is a measured result until it has been run.
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
  const created = http.post(`${BASE}/api/support-chat/threads/`,
    JSON.stringify({ message: 'load test', client_id: `k6-${__VU}-${__ITER}` }),
    { headers: { 'Content-Type': 'application/json' } });
  if (!check(created, { 'created 201': (r) => r.status === 201 })) { sleep(3); return; }
  const { thread_id: id, token } = created.json();
  let after = 0;
  for (let i = 0; i < 20; i++) {
    const r = http.get(`${BASE}/api/support-chat/threads/${id}/messages/?after=${after}`,
      { headers: { 'X-Support-Chat-Token': token } });
    check(r, { 'poll 200': (x) => x.status === 200 });
    sleep(3);
  }
}
