// k6 load model for KGTechVault. Target: the QA stack proxy (qa/stack.sh),
// never production. Select a profile with -e PROFILE=baseline|load|stress|soak.
//
// One iteration = one signed-in technician session step: open the landing
// page, check the session, list the fleet, browse the public catalog, and (in
// ~1 of 4 iterations) ask the retrieval assistant, which embeds the query with
// bge-m3 on CPU and is by far the heaviest request in the product.
//
// Thresholds are the proposed acceptance criteria (qa/perf/README.md explains
// where each number comes from). A breached threshold fails the run.
import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Trend, Rate } from 'k6/metrics';

const BASE = __ENV.QA_ORIGIN || 'http://127.0.0.1:8130';
if (/kgtechvault\.com|:8000\b|:3000\b/.test(BASE)) throw new Error('refusing to load-test production');
const TOKEN = __ENV.QA_TOKEN;
const PROFILE = __ENV.PROFILE || 'baseline';
const AUTH = { headers: { Authorization: `Bearer ${TOKEN}` } };

const pageT = new Trend('kg_page_ms', true);
const apiT = new Trend('kg_api_ms', true);
const assistT = new Trend('kg_assist_ms', true);
const bad = new Rate('kg_errors');

const PROFILES = {
  baseline: { executor: 'constant-vus', vus: 1, duration: '2m' },
  load: { executor: 'ramping-vus', startVUs: 0, stages: [
    { duration: '1m', target: 10 }, { duration: '5m', target: 10 }, { duration: '30s', target: 0 }] },
  stress: { executor: 'ramping-vus', startVUs: 0, stages: [
    { duration: '1m', target: 10 }, { duration: '2m', target: 25 }, { duration: '2m', target: 50 },
    { duration: '1m', target: 0 }, { duration: '1m', target: 0 }] },
  soak: { executor: 'constant-vus', vus: 8, duration: '20m' },
};

export const options = {
  scenarios: { main: PROFILES[PROFILE] },
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
  thresholds: PROFILE === 'stress' ? {} : {      // stress is meant to find the breaking point
    kg_errors: ['rate<0.01'],
    kg_page_ms: ['p(95)<1500'],
    kg_api_ms: ['p(95)<500'],
    kg_assist_ms: ['p(95)<4000'],
  },
};

const QUERIES = ['engine oil capacity', 'brake pad replacement', 'coolant drain procedure',
  'spark plug torque', 'tire pressure sensor reset', 'battery removal', 'cabin air filter',
  'روغن موتور', 'لنت ترمز', 'تعویض باتری'];

function ok(res, t, name) {
  t.add(res.timings.duration);
  const good = check(res, { [`${name} 2xx`]: (r) => r.status >= 200 && r.status < 300 });
  bad.add(!good);
}

export default function () {
  group('landing', () => ok(http.get(`${BASE}/`), pageT, 'landing'));
  group('session', () => ok(http.get(`${BASE}/kg-api/api/auth/me/`, AUTH), apiT, 'me'));
  group('fleet', () => ok(http.get(`${BASE}/kg-api/api/auth/fleet/`, AUTH), apiT, 'fleet'));
  group('catalog', () => ok(http.get(`${BASE}/kg-api/Toyota/2025/`), apiT, 'catalog'));
  if (__ITER % 4 === 0) {
    const q = `${QUERIES[(__VU + __ITER) % QUERIES.length]} ${__VU}-${__ITER}`;  // defeat the answer cache
    group('assist', () => ok(http.post(`${BASE}/kg-api/api/assist/`, JSON.stringify(
      { query: q, brand: 'Toyota', model: 'Corolla Cross Hybrid S' }),
      { headers: { ...AUTH.headers, 'Content-Type': 'application/json' }, timeout: '60s' }),
      assistT, 'assist'));
  }
  sleep(1 + Math.random());   // think time 1-2 s
}

function row(name, m) {
  if (!m) return `${name.padEnd(16)} (no samples)`;
  const v = m.values;
  const f = (k) => (v[k] === undefined ? '-' : v[k].toFixed(1)).padStart(9);
  return `${name.padEnd(16)}${f('avg')}${f('med')}${f('p(90)')}${f('p(95)')}${f('p(99)')}${f('max')}`;
}

export function handleSummary(data) {
  const m = data.metrics;
  const reqs = m.http_reqs ? m.http_reqs.values : { count: 0, rate: 0 };
  const text = [
    `profile=${PROFILE}  requests=${reqs.count}  throughput=${reqs.rate.toFixed(2)} req/s  ` +
      `iterations=${m.iterations ? m.iterations.values.count : 0}  max_vus=${m.vus_max ? m.vus_max.values.max : '-'}`,
    `error_rate=${m.kg_errors ? (m.kg_errors.values.rate * 100).toFixed(2) : '-'}%  ` +
      `http_req_failed=${m.http_req_failed ? (m.http_req_failed.values.rate * 100).toFixed(2) : '-'}%`,
    `${'latency (ms)'.padEnd(16)}${['avg', 'p50', 'p90', 'p95', 'p99', 'max'].map((h) => h.padStart(9)).join('')}`,
    row('page (landing)', m.kg_page_ms), row('api (me/fleet/..)', m.kg_api_ms),
    row('assist (RAG)', m.kg_assist_ms), row('all http', m.http_req_duration),
    'thresholds: ' + Object.entries(data.metrics).flatMap(([k, mm]) => Object.entries(mm.thresholds || {})
      .map(([t, r]) => `${k} ${t} ${r.ok ? 'PASS' : 'FAIL'}`)).join('; '),
  ].join('\n') + '\n';
  return { [`/out/k6-${PROFILE}.json`]: JSON.stringify(data, null, 1),
           [`/out/k6-${PROFILE}.txt`]: text, stdout: text };
}
