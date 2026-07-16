# 08 — AI Assistant & RAG

The assistant's promise: **Persian answers grounded exclusively in the manuals the user has
paid for, with links that always open.** Retrieval and diagnosis are local and
deterministic; the external LLM only phrases.

## 8.1 Index design (`api/rag/config.py`)

Content-addressed and deduplicated: every manual page's cleaned text is hashed; identical
content across the fleet is stored and embedded **once** (a *blob*), while the places it
appears live in `occurrences` (~72% of leaves are exact duplicates across trims, so we
embed ~4× less). One unified `index.rag.db` holds blobs / occurrences / chunks / vectors
(sqlite-vec, bge-m3 int8) / FTS5 / graph edges.

The relationship graph is blob-level:
- `semantic` — kNN over embeddings;
- `crosslink` — the manual's own href references;
- `labor_time` — repair procedure ↔ Labor-Times page matched by component path.
"Same procedure across cars" is NOT an edge — it's simply the other occurrences of the same
blob (exact and free).

Nothing under `_rag/` writes to source data; delete the folder to fully revert.

## 8.2 Build pipeline

`ingest` (extract blobs/occurrences from car DBs) → `embed` (bge-m3, windowed commits —
`vec_blobs` is always a contiguous prefix, kill-safe) → `graph` (edges; the
`graph_synced_vectors` meta key marks the embed→graph handoff) → `diag_build` (per-car
sidecars) — normally all run by the admin **pipeline** (doc 11), which resumes each stage
safely. Manual resume rule: after a partial embed, call `embed.embed_index`, then
`store.drop_build_vec` **before** `graph.build_all` (stale partial float table silently
loses edges).

Car metadata resolution (`config.car_meta`): explicit `CAR_REGISTRY` → **catalog fallback**
(reads main DB) → filename heuristic. The catalog fallback (added 2026-07-14) is what makes
`build_rag --add` get year/brand right for future cars automatically.

## 8.3 Retrieval (`retrieve.py`, served via `service.py`)

- Hybrid: vector + FTS + glossary expansion (Book1.csv EN↔FA part names, so a Persian query
  matches English manual text), rescored (`scoring.py`), graph-expanded (related sections,
  cross-vehicle occurrences, labor links).
- **Scope gates:**
  - a query pinned to an un-indexed car hard-fails to a "car not indexed" result rather
    than leaking another car's manual (`_car_indexed` gate);
  - `allowed_cars` (the user's grant set, threaded from `views._guard_car_content`)
    filters primary hits, expansions, cross-vehicle matches and labor links;
  - `allowed_cars` is part of the result-cache AND semantic-cache keys.
- **URL building:** every hit carries a real in-app `app_url` built from occurrences:
  percent-encode with `quote(safe='')` (titles contain `/`), year falls back
  occ.year → title-root year → `'unknown'` (and `car_view` resolves tolerantly).
  After the 2026-07-14 repair, **all 1.66M occurrence URLs + 181k diag URLs verify
  zero-fail** — keep it that way: any change to URL building must re-run the verification
  battery (`/root/linkfix_staging/` scripts).
- `service.py` adds TTL caches (result/diag/search/semantic), a single embed lock (torch
  isn't thread-safe), optional cross-encoder rerank, query logging, and `warmup()` at boot
  (`KG_WARMUP=1`).

## 8.4 Diagnostic rule engine (`diag.py` + sidecars)

Deterministic, per-car: maps a DTC code (e.g. `P0171`) or a Persian symptom to ranked
candidate DTCs (with inheritance scope), ordered diagnostic steps, the repair procedure +
standard labor time, and cross-vehicle matches — all precomputed into
`_rag/diag/<stem>.diag.db` by `diag_build.py`. No LLM involvement. Cross-vehicle and labor
links respect `allowed_cars`.

## 8.5 Chat flow (`kg_frontend/src/app/api/chat/route.js`)

1. Validate: portal token → backend `/api/auth/me/`; require `ai_eligible`. Per-IP rate
   limit (real client IP via `x-real-ip`).
2. Ground: with car context call `/api/diagnose/` first; if it yields nothing (or no car),
   `/api/assist/`.
3. Phrase: Metis (api.metisai.ir, paid) with a strict context-only Persian prompt. A
   **faithfulness gate** ensures buttons/links in the reply are exactly the retrieved ones
   (the model cannot invent or alter URLs).
4. Fallback: if Metis errors/times out, a deterministic Persian renderer produces the same
   grounded content without an LLM. The assistant never goes down with the vendor.
5. The Metis API key + bot id live only in the frontend server env (`.env.production`).

## 8.6 Human-in-the-loop feedback

- Click log (`/api/assist/feedback/`) — which result users actually open.
- 👍/👎 with reason (`/api/feedback/rate/`).
- Expert pins (`/api/feedback/pin/`) — query pattern → known-good target, boosted in
  ranking.
- Admin review feed at `/admin-review` (`/api/feedback/recent/`).
- Offline eval harness: `manage.py eval_rag` + `run_eval.sh` → `/api/eval/report/`.

## 8.7 Operational gotchas (hard-won)

1. `build_rag --add` does **nothing** when no new cars exist — it is not a resume command.
2. Count vectors via `vec_blobs_rowids` (the vec0 extension isn't loaded on plain
   connections).
3. `occurrences.car_stem == Car.car_name` — content auth depends on it.
4. The bge-m3 model (~2.3GB) loads once per gunicorn worker; keep worker count low and use
   threads (already configured).
5. HF is fully offline (`HF_HUB_OFFLINE=1`); the model cache lives at
   `/root/.cache/huggingface` — losing it means re-downloading ~4.3GB out-of-band.
6. Persian queries rely on the glossary; if part-name coverage feels weak, extend
   `Book1.csv` (EN,FA rows) and rebuild the glossary, not the prompt.
