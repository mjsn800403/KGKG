# 17 — AI evaluation suite

How the AI is measured, what the numbers mean, and how to reproduce them.

Retrieval and diagnosis are measured **offline**: no LLM calls, no external
services, no writes to product data. Answer quality is measured separately
because it drives the paid Metis phraser and therefore costs money.

---

## 17.1 Why this exists

Until 2026-08-05 the platform had a retrieval-metrics module
(`api/rag/evalmetrics.py`) and a runner (`run_eval.sh` / `eval_rag`) that had
never completed a run — the only log on disk was a crash — and no gold set at
all. Every accuracy claim about the assistant was therefore unverified. This
suite exists so that claims about the AI are backed by a reproducible number
with a confidence interval.

## 17.2 The ground-truth rule

**No label is invented, and no language model is asked what the right answer
is.** Every gold set derives its labels from data that already exists:

| Gold set | File | Where the label comes from |
|---|---|---|
| Known-item EN | `gold/known_item_en.jsonl` | The query is generated *from* a manual page, so that page is correct by construction |
| Known-item FA | `gold/known_item_fa.jsonl` | Same topics phrased in Persian; the corpus stays English |
| Out-of-scope | `gold/out_of_scope.jsonl` | Each row is verified absent from the index before admission |
| Wrong-vehicle | `gold/wrong_vehicle.jsonl` | Component verified absent from the scoped vehicle's own manual |
| Diagnosis | `gold/diagnosis.jsonl` | The manuals' own `dtc` / `symptom` / `symptom_link` tables |
| Real user | `gold/real_user.jsonl` | Logged production queries — **unlabelled**, used only for grounding rate, latency and expert review |

Two rules worth remembering because getting them wrong silently corrupts the
measurement:

- **Symptom labels must come from `symptom_link.target_kind='page' AND
  source='symptom_table'`.** Those are Toyota-authored. The far more numerous
  `source='inheritance'` DTC links are derived by our own build (same
  subsystem), so scoring against them would score the system against its own
  guesswork.
- **Out-of-scope rows are verified, not assumed.** Candidates that turn out to
  be covered by the corpus are rejected and reported rather than mislabelled.

Relevance is judged at **blob level** (content identity), not `app_url`, since
one blob is shared by many vehicles. Pages differing only by date-range or
variant under the same component+action count as one relevant family.

## 17.3 Systems compared

All five answer the same queries over the same index and are scored by the same
code:

| System | What it is |
|---|---|
| `keyword` | Boolean term match, no ranking, no terminology layer — "we added a search box" |
| `bm25` | FTS5/BM25 lexical ranking with the terminology layer |
| `dense` | bge-m3 vector kNN only — plain baseline RAG, no fusion or re-ranking |
| `hybrid` | The production pipeline (`api.rag.retrieve.assist`) |
| `hybrid_ng` | Production pipeline with Persian→English term expansion disabled |

`hybrid_ng` is the ablation that separates the terminology dictionary's
contribution from the multilingual encoder's own cross-lingual ability. It is
skipped on the English set, where term expansion is a no-op by construction.

Fairness note that belongs in any presentation of these numbers: `hybrid` and
`hybrid_ng` receive the vehicle scope because that is how the product is used
and they boost in-vehicle pages with it; `keyword`, `bm25` and `dense` are
vehicle-unaware. Labels are vehicle-independent, so all systems are scored
against identical targets.

## 17.4 Running it

Source the environment first — without it Django aborts on `DJANGO_SECRET_KEY`,
which is exactly how the original harness died:

```bash
cd /opt/KGKG/KG_backend && set -a && . ./.env.prod && set +a
```

| Step | Command | Cost |
|---|---|---|
| Build gold sets | `python manage.py build_goldset` | free, ~10 min |
| Offline suite | `python manage.py run_evalsuite` | free, ~35 min |
| Answer suite | `python manage.py run_answer_eval --budget 600` | **paid**, ~75 min |
| Expert sheets | `python manage.py expert_sheet --build --n 120` | free |
| Score returned sheets | `python manage.py expert_sheet --score '.../expert_review_reviewer*.csv'` | free |
| Render report | `python manage.py eval_report` | free |

Wrappers `/root/run_evalsuite.sh` and `/root/run_answer.sh` set the environment
and the offline HuggingFace flags. The first run after the machine has been
idle is several times slower until the 12 GB index is back in page cache.

`run_answer_eval` mints a short-lived `AuthToken` for an existing AI-eligible
account and **revokes it in a `finally` block**; it creates no account and
touches no password. `--budget` is a hard ceiling on paid calls and `--dry-run`
prints the plan without spending anything.

## 17.5 What each metric means

- **Hit@1** — the correct manual page is the first result. This is the number
  to quote for "reference page retrieval accuracy".
- **nDCG@5 / Recall@10** — reward returning *more* of the relevant family.
  The production pipeline deliberately diversifies and expands the graph, so it
  can lead on Hit@1 while trailing on Recall@10; that is a design choice
  (right page first) rather than a regression.
- **Correct refusal** — the engine reported `grounded=false` on a question the
  corpus cannot answer.
- **Link hallucination** — the chat route already computes the exact set of
  hrefs that came from retrieval and strips invented ones, reporting
  `strippedLinks`. A response with `strippedLinks > 0` is a caught fabrication;
  this is an exact count, not an estimate.
- **Numeric fidelity** — every number in an answer is checked against the
  numbers in that answer's own retrieved context, recovered from `topBlobs`.
  The client-side `sources` array carries titles and URLs only, so scoring
  against it would mark every genuine specification unsupported. Small integers
  (≤ 20) are excluded as step numbers. It is an upper bound on numeric
  hallucination: a correct value restated in another unit counts as unsupported.

Every headline figure ships with a 95% bootstrap confidence interval, and every
system-vs-system claim with a paired bootstrap p-value (`api/evalsuite/stats.py`).
A difference without a p-value is not a result.

## 17.6 Expert review

Evaluation by automotive technical experts cannot be simulated. The tooling is
built and the sample drawn; the scores stay empty until real reviewers return
sheets. `expert_sheet --build` writes one CSV per reviewer (UTF-8 BOM so Excel
opens Persian correctly) plus `expert_review_RUBRIC.md`, over a stratified
sample of what was actually measured. The rubric separates **retrieval** quality
(was the right page found?) from **answer** quality (was the Persian faithful to
it?), because those fail differently and are fixed differently. `--score` reads
the sheets back and reports per-criterion means with Cohen's κ, so the
reliability of the ratings themselves is visible.

## 17.7 Outputs

```
Database_warehouse/_rag/eval/
  gold/     the gold sets + summary.json (includes rejected out-of-scope candidates)
  runs/     <ts>/results.json          offline suite, incl. per-query detail
            <ts>/answer_results.json   paid answer suite
  expert/   reviewer CSVs, rubric, expert_scores.json once returned
  report/   EVALUATION_REPORT.md + EVALUATION_SUMMARY_FA.md
```

`eval_report` copies numbers from the run files verbatim and computes nothing
new, so the report can never disagree with the measurements.
