# 30 — Specialized AI assistant: end-to-end deep dive

Companion to [08-ai-assistant-rag.md](08-ai-assistant-rag.md) (design summary) and [17-evaluation.md](17-evaluation.md). This document
follows one request through the actual code and says, for every capability, whether it is **operational by default**, **opt-in**,
**experimental/rejected** or **planned**. Source revision: `origin/work` @ `f078878` **[C]**. Production configuration (`.env.prod`)
was not inspected for this document, so "default" below means the default in code **[U]** for what production sets.
Persian version: [fa/30-ai-assistant-deep-dive.md](fa/30-ai-assistant-deep-dive.md).

Evidence tags: **[C]** read in code at the revision above · **[H]** claim found in a source comment, doc or discussion,
not re-measured · **[U]** unverified. No evaluation number appears here unless it is quoted from a source comment and tagged **[H]**.

## 30.1 The principle (what the system promises)

Persian answers **grounded only in manuals the user's company has bought**, with links that open. Retrieval, ranking, diagnosis,
scope checks, authorization, and link validation are deterministic and local. The external LLM (Metis) is a **phraser**: it
receives a prompt that already contains the evidence and may only reword it; if it is down or unconfigured the user still gets a
deterministic digest. [C] header of `kg_frontend/src/app/api/chat/route.js`, ADR-0002.

## 30.2 Component map

| Layer | Component | Location | Role |
|---|---|---|---|
| Browser | Chat UI | `kg_frontend/src/components/` (chat widget) | Sends `message`, `sessionId`, `brand/model/car`, sanitized `history`, `prevSources`, `stream` flag to the Next.js route. |
| Edge | Chat route (Node, server-side) | `kg_frontend/src/app/api/chat/route.js` (868 lines) | Auth, quota, A/B flags, contextualization, mode selection, prompt, Metis call with bot fallback, link validation, no-LLM fallback, logging. Holds the Metis key; the browser never sees it. |
| Prompt library | `kg_frontend/src/lib/chatPrompt.js`, `contextualize.js`, `faTerms.js`, `safeUrl.js` | frontend | Prompt text, history/prevSources sanitising, allowed-link sets, button sanitiser, terminology pairs, follow-up resolution. |
| Backend API | `/api/assist/`, `/api/diagnose/`, `/api/search…`, `/api/auth/ai-usage/`, `/api/auth/chat-log/`, `/api/auth/me/` | `KG_backend/api/views.py`, `portal.py`, `chatlog.py` | HTTP surface; applies `allowed_cars`. |
| Serving layer | `rag/service.py` | backend | Caches, single GPU/torch lock, optional rerank, query logging, `warmup()`. |
| Retrieval | `rag/retrieve.py`, `scoring.py`, `glossary.py`, `terms.py` | backend | Hybrid retrieval, fusion, calibration, scope gates, graph expansion. |
| Diagnosis | `rag/diag.py`, `rag/diag_build.py` | backend | Deterministic rule engine over per-car diagnostic sidecars (DTC + symptom). |
| Index | `rag/store.py`, `embed.py`, `ingest.py`, `graph.py`, `config.py` | backend | SQLite+FTS5+`sqlite-vec` index `_rag/index.rag.db`; optional pgvector/PG-FTS mirror. |
| Learning loop | `rag/feedback.py` | backend | Query log, ratings, clicks, boosts, expert overrides ("pins"). |
| Evaluation | `api/evalsuite/`, `rag/evalmetrics.py`, `rag/evalreport.py`, `ops/rag/*` | backend / ops | Gold sets, metrics, significance tests, expert review. |

## 30.3 Request lifecycle (sequence)

```
Browser ──POST /api/chat──► Next route
  1  cookie kg_portal_token? ── no ─► 401
  2  GET /api/auth/me/  (real reason on expired/locked) ── fail ─► 401
  3  user.ai_eligible? ── no ─► 403
  4  GET /api/auth/ai-usage/ (plan allowance + A/B flags) ── 429 ─► 429 · other non-200 ─► 503 (fail closed)
  5  sanitizeHistory / prevSources; contextualize() → retrievalQuery (anaphora resolved)
  6  mode selection:
       car or model pinned, not a lookup, not an injection attempt?
         └─► POST /api/diagnose/ ──► diagUsable(d)? ─ yes ─► mode=diagnose (buildDiagnosisContext/Prompt)
       else/also no ─► [optional translate FA→EN, flag mq_translate]
                       POST /api/assist/ ─► filter hits to the selected car/model ─► buildContext
                       low confidence + hits scatter over ≥3 systems ─► mode=clarify (ask ONE question)
  7  prompt = buildPrompt | buildDiagnosisPrompt | buildClarifyPrompt
  8  Metis session call (bot chain, 90 s timeout), streamed (SSE deltas) or single reply
       any failure / not configured ─► fallbackReply (deterministic digest of retrieved sources)
  9  sanitizeButtons(reply, allowedHrefs): links not in the retrieved set are removed
 10  scopeBanner(rag) prepended deterministically (cross-vehicle evidence warning)
 11  charge quota ONLY if not degraded; record() → POST /api/auth/chat-log/ (best effort, 10 s)
 12  response / SSE events {t:'delta', d} … final payload {reply, sources, mode, grounded, confidence, quota, logKey}
```

Facts behind the steps [C]:

- **Auth and entitlement happen before any retrieval or paid call.** Plan allowances noted in the route comment: demo 5, two-day 20,
  monthly 150, annual 200 questions **[H]** (the authoritative numbers live in the backend plan model; check `api/portal.py` before relying
  on them). A question is **charged only after a real answer** (`charge()` skips `degraded` payloads), so an empty message, a failed
  retrieval or an LLM outage costs nothing.
- **Rate limit** per client IP in the route: `CHAT_RL_LIMIT` (default 20) per `CHAT_RL_WINDOW` seconds (default 60), in a process-local
  `Map` (not shared across replicas; resets on restart).
- **Lookup bypass.** Part-number / special-tool / labor-time / spec questions (regex `LOOKUP_RE`) go straight to retrieval unless they
  contain a DTC code, because the diagnostic engine would answer them with an unrelated fault.
- **Injection bypass.** Messages matching `INJECTION_RE` (e.g. "ignore previous…", "system prompt", "developer mode") skip the diagnosis
  engine; the grounded prompts contain an explicit rule to refuse such requests with a fixed sentence.
- **Hard vehicle rule in the route.** When a car/model is selected, retrieved hits whose `car_stem`/`model` differ are **dropped before
  the prompt** (`rag.hits.filter(...)`), and `rag.evidence` is nulled. This is a second line of defence behind the backend's own
  `allowed_cars` and scope gates.
- **Retrieval failure is a 502**, not a fallback answer: the route returns an error telling the operator to check that the index was built.

## 30.4 Index and ingestion (how knowledge gets in)

1. **Source:** per-vehicle content stores (PostgreSQL schemas in `kgkg_vec` for 222 manual cars; SQLite for others) — see
   [23-data-layer.md](23-data-layer.md). Admin pipeline stages (`api/pipeline.py`, `management/commands/run_pipeline.py`) run
   parse → … → `build_rag` → `build_diag`, resuming each safely. [C]
2. **Blobs, not pages.** `ingest.py` hashes each page's cleaned text; identical content across trims is stored and embedded **once**
   (a *blob*); where it appears is in `occurrences`. Source comment: ~72 % of leaves are exact duplicates **[H]**. Index size quoted in
   code comments: 301,369 blobs and 1.66 M occurrence URLs **[H]**.
3. **Embeddings:** `embed.py`, model preset from `RAG_EMBED_MODEL` (default `bge-m3`), int8 vectors in `sqlite-vec`, windowed commits
   so `vec_blobs` is always a contiguous prefix (kill-safe). The server refuses to query an index built with a different model
   (`RuntimeError` in `retrieve.assist`). FP16 on GPU (`RAG_EMBED_FP16`), fp32 on CPU.
4. **Keyword index:** FTS5 over `text`, `title`, `comp` columns with BM25 weights 1 / 4 / 12 (`RAG_FTS_W_*`).
5. **Graph:** `graph.py` builds blob-level edges: `semantic` (kNN over embeddings), `crosslink` (the manual's own hrefs), `labor_time`
   (procedure ↔ Labor-Times page by component path). "Same procedure in another car" is not an edge; it is another occurrence of the
   same blob.
6. **Diagnostic sidecars:** `diag_build.py` produces per-car sidecars from the manuals' own `dtc`, `symptom`, `symptom_link` tables.
7. **Terminology:** `glossary.py` / `terms.py` provide the EN↔FA part-name glossary (generated from the terminology store `terms.db`,
   [14-terminology.md](14-terminology.md)); hot-reloaded.
8. **Rule for resuming:** after a partial embed, call `embed.embed_index`, then `store.drop_build_vec` **before** `graph.build_all`;
   otherwise a stale partial float table silently loses edges. [C] doc 08.
9. **Storage backends:** default vectors and FTS are SQLite (`RAG_VEC_BACKEND`, `RAG_FTS_BACKEND` = `sqlite`). Mirroring into `kgkg_vec`
   (pgvector HNSW and PG FTS) exists (`rag/pgvec.py`, `rag/pgfts.py`, `ops/rag/pgvec_load.py`, `pgfts_load.py`, benchmark
   `pgvec_bench.py`) but is **opt-in** in code; production **does** use it (`RAG_VEC_BACKEND=pgvector`, `RAG_FTS_BACKEND=pg`, observed 2026-11-04 **[P]**).

## 30.5 Retrieval pipeline (`retrieve.assist`)

Ordered exactly as the code runs:

1. **Preconditions.** Index file must exist (`FileNotFoundError` → callers fall back to keyword search); embedding model must match.
2. **Glossary expansion.** `glossary.expand(query)` returns English terms for Persian input; the embedded text is `query + terms`, and the
   FTS MATCH string is built by `_fts_match`. (A Persian query for "روغن ترمز" also searches "brake fluid".)
3. **Query classification.** `scoring.classify_query` labels the query (`code` for DTC-like input, otherwise natural language) and sets
   fusion weights: a code leans on keywords, a Persian sentence on the dense side.
4. **Hard scope gate, part 1.** If `car_stem` is given and has no content in the index → `_no_scope_result(... 'car_not_indexed')`
   immediately; no vector or keyword scan is executed.
5. **Candidate generation.**
   - Dense kNN over all blobs: `RETRIEVE_VEC_K` 40 (unscoped) or `SCOPED_VEC_K` 120 (brand/model/car given).
   - Car-scoped dense pass over the pinned car's own blobs (~4 k, ~80 ms): `RAG_CAR_VEC_K` 40 — needed because a global top-K rarely
     contains a single car's pages.
   - BM25 keyword pass: `RETRIEVE_FTS_K` 40 / `SCOPED_FTS_K` 120, column weights as above.
   - Optional car-scoped keyword pass `scope_fts` — **off for the assistant**. Source comment: enabling it for the assistant was measured and
     **rejected** (n = 250 per language, English nDCG@5 −0.042 and R@10 −0.039, both p < 0.001, 66 queries worse vs 21 better; all ten metrics fell,
     +50 % latency) **[H]**. Only site search uses it.
6. **Weighted RRF fusion.** `rrf += w / (RRF_K + rank + 1)` with `RRF_K = 60`; the max similarity and best (most negative) BM25 per blob are kept.
7. **Authorization gate.** For each candidate blob the occurrences are filtered to `allowed_cars`; a blob with no allowed occurrence is
   **dropped before ranking**. `None` means unrestricted (single-car pages whose access was already checked, internal and evaluation callers).
8. **Occurrence choice and signals.** `_pick_occurrence` picks the occurrence that best fits brand/model/car (`vehicle_boost`);
   boilerplate titles are multiplied by `BOILERPLATE_PENALTY` (0.4); a blob absent from the active scope gets `SCOPE_PENALTY` (0.85);
   `feedback.blob_boost_map()` supplies a rating-based multiplier; graph centrality is added.
9. **Calibration.** `scoring.calibrate` blends normalised RRF (0.30), cosine similarity (0.45), normalised BM25 (0.20) and centrality (0.05),
   multiplied by the boosts and penalties; `variant_fit` further scales hits whose trim does not fit the pinned car.
10. **Adaptive depth.** If the top-1/top-2 relative margin ≥ `MARGIN_EASY` (0.20) and top similarity ≥ `EASY_SIM` (0.72) the query is *easy*:
    return `FINAL_K_MIN` 4 hits and expand 2 graphs; otherwise `FINAL_K` 8 hits and expand all.
11. **Expert pin.** `feedback.pinned_match(qvec)` can surface a curated source for a query pattern as `expert_verified`; the pin still must belong
    to an allowed car.
12. **Hit assembly.** Each hit has `blob_id, car_stem, brand, model, variant, year, title, title_path, segments, app_url, score, similarity,
    matched_via, confidence_band + Persian label, explain, text (≤ 3000 chars), related (graph expansion), cross_vehicle`.
    `app_url` is a real in-app link built from the occurrence (`quote(safe='')` because titles contain `/`).
13. **Grounding gate.** `grounded = hits and top_effective_similarity ≥ GROUND_SIM_FLOOR` (`RAG_GROUND_SIM_FLOOR`, default 0.60). For code queries
    the effective similarity is `max(sim, bm25_norm)`. Not grounded ⇒ confidence band forced to low.
14. **Hard scope gate, part 2 (`_evidence_scope`).** For a pinned car that *is* indexed, checks whether the cited evidence's title or component actually
    exists in that car (`title_absent_from_vehicle`, `component_absent_from_vehicle`); with `RAG_ABSENT_REFUSES` (default on) such a result sets
    `grounded=False`. `RAG_NEARMISS_GUARD` (default on) additionally compares against the best *unscoped* candidate to detect that vehicle scoping swapped
    in a different component.
15. **Result:** `{query, scope, count, hits, kind, grounded, top_similarity, confidence_band, adaptive, car_indexed?, evidence?, out_of_scope?}`.

Confidence bands (`scoring.confidence_band`): *high* needs similarity ≥ 0.75 and margin ≥ 0.15; *low* below similarity 0.45; otherwise *medium*.
Labels are Persian and shown to the user (transparency) **[C]**.

### Serving layer (`rag/service.py`)

- **Exact cache:** key = (lower-cased query, brand, model, car_stem, **sorted tuple of `allowed_cars` or `None`**); TTL `RAG_CACHE_TTL` 900 s,
  max `RAG_CACHE_MAX` 512. A restricted caller can never be served an unrestricted caller's entry (`None` and a set never collide).
- **Semantic cache:** `deque(maxlen=256)` of `(query_vector, scope, result)`; hit if cosine ≥ `RAG_SEM_CACHE_SIM` (0.95) in the same scope. Intended
  for typos, punctuation and inflection only; a source comment states it never merges different meanings **[H]**.
- **One lock** serialises embedding + retrieval (torch/MPS is not thread-safe); on one host this is "plenty fast, a query embeds in tens of ms" **[H]**.
- **Optional rerank:** `RAG_RERANK=1` runs `BAAI/bge-reranker-v2-m3` over the top 20 (`RERANK_CANDIDATES`) and blends with the retrieval order via z-score
  fusion weight `RAG_RERANK_FUSE` (default 1.0 = pure rerank). **Default off** (`RAG_RERANK` default `0`); whether production enables it is **[U]**.
- **Site search** (`service.search`) shares the retriever but uses `expand=False, with_text=False, scope_fts=True`, an over-fetch of `limit × 4` (cap 120),
  and a per-hit corpus-boundary filter (a hit must have real vector similarity ≥ `RAG_SEARCH_SIM_FLOOR` 0.55 *or* a genuine BM25 match), so gibberish and
  out-of-corpus queries return nothing instead of nearest neighbours.
- **Warm-up:** `warmup()` preloads the embedding model and read-only index connection at server start when `KG_WARMUP` is enabled.

## 30.6 Deterministic diagnosis (`rag/diag.py`)

For a pinned car the route calls `/api/diagnose/` first. The engine, inside the same lock and with the same `allowed_cars` cache identity:

- resolves the car's sidecar (`_resolve_stem`); a car-less query only returns an `available_cars` hint, **filtered to the caller's cars** so the fleet roster is
  not disclosed;
- **by code:** detects a DTC (`normalize_code_text`, `_detect_code`) and returns the fault with ordered steps, repair procedure and labor time;
- **by symptom:** combines vector and FTS ranks over `symptom`/`symptom_link` data with feedback boosts into ranked candidate faults with confidence;
- attaches repair procedures, labor-time links, and cross-vehicle matches (each filtered by `allowed_cars`);
- has its own `grounded` verdict and confidence band that the route honours.

`diagUsable(d)` decides whether the route uses the diagnosis (otherwise it proceeds to general retrieval). Diagnosis answers are structured; the LLM only phrases
them (`buildDiagnosisPrompt`).

## 30.7 Prompting, Metis, fallbacks

- **Prompts** (`chatPrompt.js`): with no context, the model is told to say honestly the topic is not in the data, not to invent technical content, to say
  "this brand/vehicle is not covered by KGTechVault" for out-of-coverage vehicles, and to refuse instruction-override attempts with one fixed sentence. With
  context, eleven numbered rules: use only the supplied manual texts; answer in fluent Persian, step by step, quoting torque/fluid/distance values exactly;
  emit one link button per source in the form `[BUTTON](title="…", href="…")`; answer only from the selected vehicle's manual; report estimated labor time when
  present; structure repair answers (diagnosis, parts and fluids, steps, torque/specs, time, warnings) while giving a bare number for a bare spec question;
  pick exactly the torque-table row asked about; quote part and special-tool numbers verbatim and never invent one; keep unit notation (`N·m`, `kgf·cm`);
  decline questions about uncovered brands; refuse role-change or prompt-leak requests. Evidence text is passed through `fenceSafe` and wrapped between
  `=== … ===` markers; history and previous sources are sanitised.
- **Terminology block:** EN↔FA pairs actually occurring in the retrieved context are listed so the model uses the same Persian term the UI uses.
- **Metis integration:** base URL `https://api.metisai.ir/api/v1/chat`; credentials from `METIS_API_KEY` and `METIS_BOT_ID` (server runtime only);
  `METIS_FALLBACK_BOT_IDS` (comma-separated) builds a **bot chain**. `withFallback` tries each bot with a fresh session (a session belongs to one bot) and logs
  `Metis answered on fallback bot #i`. Timeout 90 s per call. For streaming, fallback stops once text has reached the user (`canRetry = !streamed`).
  Session ids from the browser are accepted only if `isSafeSessionId` passes (they become a URL path segment of a request carrying the key).
- **Optional FA→EN query translation** (`RAG_MQ_TRANSLATE=1` or per-user A/B flag `mq_translate` from `api/flags.py`): Metis translates a Persian question into a
  short English service-manual query before `/api/assist/`; rejected if the output is still Persian, empty or > 200 chars; process-local cache of 500. **Not
  applied to diagnosis.** The route's own comment warns the measured gain came from hand-made paraphrases and "may be smaller live" **[H]**; whether it is
  enabled in production is **[U]**.
- **No-LLM fallback:** if Metis is unconfigured, errors, times out, or the budget is exhausted, `fallbackReply({mode, sources, grounded})` builds a
  deterministic digest of the retrieved sources (or `fallbackClarify` for the clarifying mode). `degraded: true` is set, nothing is charged, and the admin chat
  log records it. The cross-vehicle warning `scopeBanner` is prepended deterministically *before* either path, "because a warning the model may choose to omit
  is not a safety control."
- **Clarify mode:** low confidence plus hits scattered over three or more top-level systems produces one clarifying question instead of an answer; grounding
  math is unchanged.

## 30.8 Citation and link integrity

- Every hit carries `app_url`; the route builds `allowedHrefs` from exactly the hits (or diagnosis payload) it passed to the model.
- `sanitizeButtons(reply, allowed)` rewrites output: plain markdown links not in the allowed set are reduced to their text; `[BUTTON](…)` tokens with a disallowed
  href are deleted; malformed button tokens are deleted. **A hallucinated link therefore cannot reach the user.** The count of stripped links is available to the
  caller. [C]
- Source comment: after the 2026-07-14 repair all 1.66 M occurrence URLs and 181 k diagnostic URLs verified with zero failures; any change to URL building
  must re-run the verification battery **[H]** (the scripts named there are on the old workstation/server, not in this repository **[U]**).

## 30.9 Authorization boundaries (summary)

| Boundary | Where enforced | Notes |
|---|---|---|
| Logged-in, AI-eligible account | route steps 1–3 | `ai_eligible` from `/api/auth/me/`. |
| Plan allowance | route step 4 + `charge()` | Fail closed: if the allowance cannot be read → 503. |
| Cars the company bought | `allowed_cars` through `views._guard_car_content` → `service.assist/diagnose/search` → `retrieve.assist` (blob dropped before ranking), `_pinned_hit`, `_expand`, labor/cross-vehicle links | Part of every cache key. |
| Selected vehicle only | `_car_indexed`, `_evidence_scope`, route filter | Second filter in the Node route. |
| Link validity | `sanitizeButtons` | Only retrieved hrefs survive. |

## 30.10 Feedback and learning loop (`rag/feedback.py`)

- **Query log:** `RAG_LOG_QUERIES` (default on) writes each query, scope, result summary, cache flag and latency to `feedback.db`
  (`RAG_FEEDBACK_DB`, default `_rag/feedback.db`). This persists user questions: a privacy-relevant fact for [12-security.md](12-security.md).
- **Signals:** ratings (`rate`), clicks (`log_click`), time-decayed counts → `feedback_multiplier` (floor 0.85, cap 1.2, minimum 3 observations) →
  `blob_boost_map()` (refreshed every `RAG_FB_CACHE_TTL` 300 s) applied to ranking when `RAG_FEEDBACK_BOOST` is on.
- **Expert overrides:** `add_override`/`pinned_match` store a query-vector pattern → source blob mapping (human-in-the-loop); `recent_downvotes` feeds review.
- **Isolation:** staging/QA mount production's `_rag/` and **must** set `RAG_FEEDBACK_DB`, otherwise their queries and ratings land in the production store
  and re-rank live search. `test_feedback_isolation.py` covers the setting.
- Separately, the admin **chat log** (`api/chatlog.py`, endpoint `/api/auth/chat-log/`) stores question, answer, session, mode, grounded/degraded flags,
  vehicle, sources, latencies, token counts, cost and A/B flags for admins/managers. The question is truncated to 4000 chars in the route.

## 30.11 Evaluation and quality assurance

- **Gold sets** (`api/evalsuite/goldset.py`, command `build_goldset`): known-item EN and FA (queries generated *from* a page, so the page is correct by
  construction), out-of-scope (each row verified absent from the index), wrong-vehicle (component verified absent from the scoped vehicle), diagnosis (from the
  manuals' own tables), and unlabelled real-user queries used only for grounding rate, latency and expert review. [C] doc 17.
- **Metrics** (`rag/evalmetrics.py`): Hit@1, nDCG@5, Recall@10, MRR, precision; statistics (`evalsuite/stats.py`) with paired permutation and bootstrap;
  `answer_eval.py` and `expert.py` for answer-level and human review; `baselines.py` for comparison systems.
- **Offline tools** (`ops/rag/`): `dump_cands.py`, `fusion_sweep.py` (2-fold cross-validation of the fusion weight), `paired_significance.py` — see
  [31-ops-files-reference.md](31-ops-files-reference.md) §31.6.
- **Recorded results found in source comments (not re-run) [H]:** scoped-FTS-for-assistant rejected (§30.5); rerank fusion weight ≈ 0.4 chosen by 2-fold CV
  on the gold sets with EN nDCG@5 +0.12 and FA Hit@1 +0.19 (p < 0.001) while the shipped default remains 1.0; `RAG_FTS_CLEAN` reduced p50 from 1168 → 819 ms
  (EN) and 1048 → 842 ms (FA); `RAG_SEARCH_SIM_FLOOR` 0.55 leaves 1 of 81 real queries empty; before this floor the median list for 81 Persian queries at
  limit 30 was 7 results. Where the full evaluation reports (`results.json`) are stored is **[U]**; none is committed under `docs/`.
- **Unit tests** (all under `KG_backend/api/rag/test_*.py`): `test_retrieve.py` (341 lines), `test_scoring.py`, `test_service.py`, `test_service_paths.py`,
  `test_diag_engine.py`, `test_terms.py`, `test_translate_terms.py`, `test_fts.py`, `test_embed.py`, `test_feedback.py`, `test_feedback_isolation.py`,
  `test_pgvec.py`, `test_pgfts.py`, `test_query_adapter.py`, `test_rerank_fuse.py`, `test_ratelimit.py`, `test_store_ro.py`, `test_evalmetrics.py`. Run with the
  backend suite: [32-testing-and-qa.md](32-testing-and-qa.md). Frontend chat logic tests live next to `chatPrompt.js`/`route.js` (see §32.3).
  No document may claim a coverage percentage for these without running the coverage job (§32.9).

## 30.12 Capability status matrix

| Capability | Status | Basis |
|---|---|---|
| Hybrid retrieval (dense + BM25 + RRF + calibration) | **Operational** (code path always on) | [C] |
| Persian→English glossary expansion | **Operational** | [C] |
| Authorization via `allowed_cars` in retrieval and caches | **Operational** | [C] |
| Vehicle scope gates (part 1 and 2), near-miss guard | **Operational by default** (env switches can disable) | [C] |
| Deterministic diagnosis engine | **Operational** when per-car sidecars exist | [C]; which cars have sidecars **[U]** |
| Exact + semantic answer caches | **Operational** | [C] |
| Metis phrasing with bot fallback chain | **Operational when keys configured**; production config **[U]** | [C] |
| No-LLM fallback digest | **Operational** | [C] |
| Link sanitising | **Operational** | [C] |
| Cross-encoder rerank | **Opt-in** (`RAG_RERANK=1`, default off) | [C]; production **[U]** |
| FA→EN query translation | **Opt-in / A/B** (`RAG_MQ_TRANSLATE`, flag `mq_translate`) | [C]; production **[U]** |
| pgvector/PG-FTS retrieval backends | **Opt-in** in code (default `sqlite`); **enabled in production**: `RAG_VEC_BACKEND=pgvector`, `RAG_FTS_BACKEND=pg` (observed 2026-11-04, see [38](38-implementation-status-matrix.md)) | [C]; [P] |
| Scoped FTS for the assistant | **Rejected after measurement** (site search only) | [H] |
| Feedback boosts and expert pins | **Operational** mechanics; volume of real ratings **[U]** | [C] |
| Streaming answers | **Operational** (SSE deltas from the Node route) | [C] |
| Answer-level automated hallucination scoring in production | **Not present** in the request path; only offline `answer_eval.py` | [C] |

## 30.13 Failure modes and limits

- Embedding model mismatch → `RuntimeError` (503/500 from the endpoint) until `RAG_EMBED_MODEL` matches the index.
- Index file missing → `FileNotFoundError`; site search falls back to keyword (`LIKE`) search; assistant route returns 502.
- Single global lock: concurrent assistant requests serialise on embedding/retrieval; a slow rerank blocks others.
- All caches are **per process**; with several gunicorn workers each worker has its own caches and the route's rate-limit map is per Node process.
- The Metis bot chain protects against one withdrawn model, not against Metis itself being down (then the no-LLM digest is used).
- Persian morphology is handled by glossary expansion and the dense model, not by a Persian analyser; unusual wording of a part name can miss.
- The assistant is not a safety system: torque values and procedures are quoted from manuals; the cross-vehicle banner exists for that reason.

## 30.14 Configuration quick reference

Assistant-specific names (full tables: [29](29-environment-reference.md) §29.7): `METIS_API_KEY`, `METIS_BOT_ID`, `METIS_FALLBACK_BOT_IDS`, `BACKEND_URL`,
`CHAT_RL_LIMIT`, `CHAT_RL_WINDOW`, `RAG_MQ_TRANSLATE`, `KG_WARMUP`, `RAG_GROUND_SIM_FLOOR` (0.60), `RAG_ABSENT_REFUSES` (1), `RAG_RERANK` (0), `RAG_VEC_BACKEND`
(`sqlite`), `RAG_FTS_BACKEND` (`sqlite`), plus every `RAG_*` in §29.7.
