# Performance, load, stress and stability test report

All numbers below are copied from machine output in this folder
(`run*/k6-*.txt|json`, `run*/resources-*.csv`). Nothing is extrapolated.

## Environment

| Item | Value |
|---|---|
| Target | QA stack (`qa/stack.sh`): backend + frontend + nginx proxy on a sanitized copy of the production DB, production RAG index and manual stores (read) |
| Host | Production host 103.75.197.155: 16 vCPU, 31 GiB RAM, shared with live production |
| Resource caps | backend 6 CPUs / 10 GiB, frontend 2 CPUs / 3 GiB, proxy 1 CPU, k6 load generator 2 CPUs |
| Backend config | Same image and gunicorn settings as production: 3 gthread workers × 8 threads |
| App throttles | Off for capacity runs (`KG_RL_DISABLE=1`, content-guard ceilings raised): all virtual users share one IP and one account, so with them on the test would only measure the limiter. The limiter itself is covered by `api/test_qa_ratelimit.py` |
| Tool | k6 0.57.0 (`grafana/k6:0.57.0`), script `qa/perf/k6-kgkg.js` |
| Date | 2026-10-27 (UTC) |

Workload (one iteration ≈ one technician step, 1–2 s think time): GET `/`
(server-rendered landing), GET `/kg-api/api/auth/me/`, GET
`/kg-api/api/auth/fleet/`, GET `/kg-api/Toyota/2025/` (catalog), and every
4th iteration POST `/kg-api/api/assist/` with a unique query (bge-m3
embedding on CPU + hybrid retrieval — the heaviest request in the product;
unique queries defeat the answer cache). Manual page content is excluded: it
is sealed by the content shield and cannot be fetched by a bare HTTP client.

Production demand for comparison (nginx log, 2026-10-27): 3,941 requests in
18 h; busiest hour 792 requests ≈ 0.22 req/s.

## Results — run 1 (revision `c43998c`, gunicorn `--max-requests 2000`)

| Profile | VUs / duration | Requests | Throughput | Errors | Landing p95 | API p95 | Assistant p50 / p95 / p99 | Thresholds |
|---|---|---|---|---|---|---|---|---|
| baseline | 1 / 2 min | 294 | 2.4 req/s | 0.00 % | 18.2 ms | 35.4 ms | 959 / 1,263 / 1,781 ms | all pass |
| load | ramp → 10 / 6.5 min | 7,599 | 19.5 req/s | 0.00 % | 21.0 ms | 38.4 ms | 1,107 / 2,242 / 6,372 ms | all pass |
| stress | ramp 10 → 25 → 50 / 7 min | 10,145 | 28.1 req/s | 0.64 % | 27.7 ms | 1,750 ms | 3,556 / 11,516 / 13,799 ms | n/a (stress finds limits) |
| soak | 8 / 20 min | 21,483 | 17.9 req/s | 0.04 % | 19.9 ms | 36.8 ms | 1,053 / 2,278 / 7,818 ms | all pass |

Resources (sampled every 2 s):

| Profile | Backend CPU avg / max (cap 600 %) | Backend memory first quarter → last quarter (max) | Host load max | **Production `/api/health/` during the run** |
|---|---|---|---|---|
| baseline | 47 % / 608 % | 3,363 → 3,067 MiB (3,366) | 4.6 | 31 samples, 0 non-200, p50 4.4 ms, max 6.9 ms |
| load | 221 % / 603 % | 3,010 → 3,297 MiB (3,331) | 7.8 | 98 samples, 0 non-200, p50 4.5 ms, max 6.5 ms |
| stress | 350 % / 585 % | 3,132 → 3,327 MiB (3,748) | 12.9 | 90 samples, 0 non-200, p50 4.6 ms, max 7.5 ms |
| soak | 197 % / 629 % | 3,907 → 3,573 MiB (3,949) | 10.1 | 299 samples, 0 non-200, p50 4.4 ms, max 9.0 ms |

## Findings

**P-01 Capacity knee.** Throughput grows from 19.5 req/s at 10 users to only
28.1 req/s at 50: the backend is CPU-bound on query embedding (backend CPU at
its 6-CPU cap). Because assistant requests and light API requests share one
worker pool, light requests queue behind embeddings: API p95 rises from 38 ms
to 1.75 s and assistant p95 to 11.5 s at 50 users. Expected load (10 users,
~88× today's peak) is comfortably within criteria.
*Recommendation (not implemented):* bound concurrent embeddings per worker,
or serve `/api/assist/` from a separate worker pool, so a burst of questions
cannot slow down navigation.

**P-02 Errors come from worker recycling.** Every failed request in every
profile was an nginx 502 *Connection reset by peer* at the moment a gunicorn
worker hit `--max-requests 2000` and recycled
(`run1-recycle-2000/gunicorn-recycles.log`, `proxy-502-resets.log`). In the
stress run all three workers recycled within 18 s (20:15:34–20:15:52) and
64 requests failed. Production runs the same flags (3 recycles in the 24 h
before the test). The soak showed no memory growth to justify such frequent
recycling, so the threshold was raised to 20,000 (commit "perf(backend):
recycle gunicorn workers every 20,000 requests"). Re-test: run 2 below.

**P-03 No production impact.** Across 518 production health samples taken
during the four profiles of run 1, and 89 more during run 2, production
answered 200 every time (607 of 607) with a maximum latency of 9.0 ms.

**P-04 Memory.** No upward trend over 20 minutes at sustained load. Worker
recycling resets worker memory, so a slow leak could be masked; run 2 with
less frequent recycling is the better leak indicator.

## Results — run 2 (revision `f7d3856`, gunicorn `--max-requests 20000`)

Same stress profile, same caps, immediately after rebuilding with the P-02
change (raw output: `run2-recycle-20000/`):

| Profile | Requests | Throughput | Errors | Landing p95 | API p95 | Assistant p50 / p95 / p99 | Worker recycles |
|---|---|---|---|---|---|---|---|
| stress (before, run 1) | 10,145 | 28.1 req/s | 0.64 % | 27.7 ms | 1,750 ms | 3,556 / 11,516 / 13,799 ms | 6 in 18 s at peak |
| **stress (after, run 2)** | **10,866** | **30.2 req/s** | **0.00 %** | 28.3 ms | 1,898 ms | 3,068 / 11,764 / 13,433 ms | **0** |

P-02 is closed: with no recycling during the run there were no resets and
no errors. P-01 (latency under saturation) is unchanged, as expected — it is
a capacity property, not an error source.

## Limitations

* The QA stack shares the production host, so absolute numbers include
  noise from production and other services; the caps make the test
  conservative, not optimistic.
* The external LLM call that phrases chat answers is not in the load model
  (cost, third-party rate limits); measured latency is our own pipeline.
* Single client IP and few accounts: per-IP/per-user throttling behaviour
  under load is tested at integration level, not here.
* Run 1 applies to revision `c43998c`, run 2 to `f7d3856`; re-run on each minor release.
