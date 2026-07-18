# 14 — Bilingual Terminology Store

The single source of truth for English↔Persian terminology:
`Database_warehouse/_rag/terms.db` (module `api/rag/terms.py`). Two runtime artifacts are
**generated** from it and hot-reload with no restart:

| Artifact | Consumer | Direction | Reload |
|---|---|---|---|
| `Book1.csv` (project root) | `api/rag/glossary.py` query expansion | fa→en | mtime check per query |
| `_rag/terms_en_fa.json` | chat route via `src/lib/faTerms.js` (`TERMS_JSON_PATH`) | en→fa display | mtime check ≤60s |

**Never hand-edit the artifacts** — change the store, then `manage.py build_terms --export`.

## 14.1 Schema

`terms(en, fa, en_norm, fa_norm, domain, source, confidence, status, use_query,
use_display, notes, timestamps, UNIQUE(en_norm, fa_norm))`

- `fa` keeps ZWNJ (professional نیم‌فاصله); `fa_norm` reuses `glossary._norm_fa` so
  store-side and query-side normalization can never diverge.
- `source` ranks: curated = reviewed (3) > imported (2) > generated (1); a lower-ranked
  upsert never downgrades a higher-ranked row.
- One EN term may keep several FA rows (all valuable fa→en); the display export picks one
  best FA per EN (rank → confidence → shortest), inlines only the first «،»-alternative,
  and drops 1-word-EN → 3+-word-FA over-specific mappings.
- `gen_queue` is the machine-translation work queue (state machine:
  queued → accepted / review / failed) — fully resumable.

## 14.2 Commands (`manage.py build_terms`)

- `--import-legacy` — ONE-TIME bootstrap from the original `Book1.csv` + `translation.sql`
  (refuses on a non-empty store without `--force`; re-importing generated artifacts would
  relabel rows as curated). Cleaning: header artifact dropped, double spaces collapsed,
  Arabic ي/ك unified at rest, EN «standard part…» and FA «قطعه استاندارد…» noise prefixes
  stripped, curated service vocabulary seeded (display-only, `use_query=0`).
- `--export` — regenerate both artifacts (atomic replace + dated `Book1.csv.bak.YYYYMMDD`).
- `--report` — vocabulary/coverage/cost report (read-only; writes `_rag/terms_report.txt`).
- `--mine --top N` — queue the N most-frequent untranslated EN terms from blob titles,
  `comp_readable`, breadcrumb segments and diag names into `gen_queue`.
- `--fa-gaps` — Persian user queries (feedback.db) that `glossary.expand()` under-expands
  → `_rag/fa_gaps_report.csv` (seeds curation / future symptom-variant generation).
- `--import-review file.csv` — ingest human-reviewed `en,fa[,domain]` rows
  (source=reviewed, confidence 1.0), then `--export` to publish.

## 14.3 Machine translation (`manage.py translate_terms`)

Metis-based, QA-gated; **never publishes an unverified pair**:

1. 2 independent samples (separate Metis sessions), few-shot-anchored on curated pairs;
   strict JSON, re-ask ≤2.
2. Disagreement → 3rd sample, 2-of-3 majority (agreement 0.66) or human review.
3. Back-translation fa→en, scored by bge-m3 cosine vs the original EN
   (`--backtrans-min`, default 0.82).
4. Pass both → `terms` active (confidence = 0.5·agreement + 0.5·similarity);
   otherwise `pending_review` + `_rag/terms_review.csv`.

Flags: `--limit N`, `--budget M` (hard Metis-message cap), `--batch-size`, `--dry-run`,
`--env-file` (Metis creds read from `kg_frontend/.env.production`; not duplicated).
Ops: pid lockfile (`_rag/locks/`), yields between batches while a pipeline job is active,
full call log in `_rag/logs/translate_terms.log`. Cost ≈ 0.12–0.15 messages/term.

Workflow: `--report` → `--mine --top N` → `translate_terms --dry-run` → pilot
`--limit 300` → review `terms_review.csv` (+ approve accepted samples) → scaled runs
under `--budget` → every run ends with `build_terms --export`.

## 14.4 Provenance of the legacy data

`/opt/KGKG/translation.sql` was a stale export of `Book1.csv` (its 1,625 pairs are a
strict subset) — retired after `--import-legacy`; kept on disk for history only.
The original hand-maintained `Book1.csv` is preserved as `Book1.csv.bak.20260718`.
