# KGKG — Quantitative AI Evaluation Results

*Generated from run `20260805_160837`. Embedding model: `BAAI/bge-m3`. All retrieval metrics are computed offline over the production index with zero LLM calls.*

## 1. How the ground truth was built

| Gold set | Rows | Label source |
|---|---:|---|
| Known-item, English | 250 | query generated from a specific manual page — that page is correct by construction |
| Known-item, Persian | 250 | same topics phrased in Persian against the English corpus |
| Out-of-scope | 52 | verified absent from the index before admission |
| Wrong-vehicle | 60 | component verified absent from the scoped vehicle's own manual |
| Diagnosis | 453 | the manuals' own DTC and symptom tables (manufacturer-authored) |
| Real user queries | 143 | logged production queries (unlabelled — used for grounding rate, latency, expert review) |

Out-of-scope candidates rejected because the corpus DOES cover them: `carburetor float bowl, distributor cap rotor, magneto ignition, tractor power take off shaft, points condenser ignition, supercharger intercooler bypass`. They were dropped rather than mislabelled.

## 2. Retrieval — English queries

n = 250 queries.

| System | nDCG@5 | Hit@1 | Hit@5 | Recall@10 | MRR | p50 ms |
|---|---|---|---|---|---|---:|
| `keyword` | 0.055 [0.035–0.075] | 2.8% [0.8–5.2] | 13.2% [9.2–17.6] | 12.3% [8.9–16.1] | 0.074 [0.050–0.099] | 1 |
| `bm25` | 0.346 [0.295–0.397] | 34.4% [28.8–40.0] | 46.4% [40.4–52.8] | 42.4% [36.9–48.3] | 0.394 [0.338–0.450] | 636 |
| `dense` | 0.494 [0.442–0.544] | 53.2% [46.8–59.6] | 70.8% [64.8–76.4] | 57.7% [52.7–62.5] | 0.605 [0.549–0.660] | 525 |
| `hybrid` | 0.468 [0.431–0.505] | 65.2% [59.6–70.8] | 84.0% [79.6–88.4] | 55.5% [51.2–59.8] | 0.730 [0.682–0.775] | 1614 |

Paired bootstrap vs the production pipeline (`hybrid`):

| Comparison | Δ nDCG@5 | p | Δ Hit@1 | p |
|---|---:|---:|---:|---:|
| hybrid_vs_keyword | 0.4133 | 0.0005 | 0.624 | 0.0005 |
| hybrid_vs_bm25 | 0.1221 | 0.0005 | 0.308 | 0.0005 |
| hybrid_vs_dense | -0.0256 | 0.2719 | 0.12 | 0.0025 |

## 3. Retrieval — Persian queries over English documents

n = 250 queries.

| System | nDCG@5 | Hit@1 | Hit@5 | Recall@10 | MRR | p50 ms |
|---|---|---|---|---|---|---:|
| `keyword` | 0.000 [0.000–0.000] | 0.0% [0.0–0.0] | 0.0% [0.0–0.0] | 0.0% [0.0–0.0] | 0.000 [0.000–0.000] | 0 |
| `bm25` | 0.060 [0.036–0.087] | 5.2% [2.8–8.0] | 9.6% [6.0–13.2] | 9.0% [5.9–12.2] | 0.071 [0.045–0.101] | 479 |
| `dense` | 0.200 [0.161–0.242] | 21.2% [16.4–26.4] | 35.2% [29.2–41.2] | 24.4% [20.1–29.1] | 0.270 [0.221–0.320] | 531 |
| `hybrid` | 0.228 [0.198–0.262] | 31.6% [26.0–37.6] | 54.4% [48.4–60.4] | 29.5% [25.4–34.0] | 0.410 [0.357–0.462] | 1284 |
| `hybrid_ng` | 0.211 [0.178–0.247] | 26.4% [20.8–31.6] | 46.8% [40.8–52.8] | 25.7% [21.7–30.0] | 0.349 [0.298–0.400] | 715 |

Paired bootstrap vs the production pipeline (`hybrid`):

| Comparison | Δ nDCG@5 | p | Δ Hit@1 | p |
|---|---:|---:|---:|---:|
| hybrid_vs_keyword | 0.2284 | 0.0005 | 0.316 | 0.0005 |
| hybrid_vs_bm25 | 0.1681 | 0.0005 | 0.264 | 0.0005 |
| hybrid_vs_dense | 0.028 | 0.1559 | 0.104 | 0.0015 |
| hybrid_vs_hybrid_ng | 0.0175 | 0.3248 | 0.052 | 0.1399 |

## 4. Refusal on out-of-scope questions

| Category | Correct refusal | n |
|---|---|---:|
| non_automotive | 100.0% [86.7–100.0] | 25 |
| nonsense | 100.0% [79.6–100.0] | 15 |
| automotive_absent | 8.3% [1.5–35.4] | 12 |
| **overall** | **78.8% [66.0–87.8]** | 52 |

## 5. Vehicle attribution (component absent from the scoped car)

| Outcome | Count | Share |
|---|---:|---:|
| refused | 0 | 0.0% |
| attributed_other_vehicle | 24 | 40.0% |
| claimed_scoped_vehicle | 36 | 60.0% |

`claimed_scoped_vehicle` is the error mode: the answer was attributed to a vehicle whose own manual does not contain that component.

## 6. Fault-diagnosis engine

| Condition | Hit@1 | Hit@3 | MRR | n |
|---|---|---|---|---:|
| dtc_name | 59.3% [51.3–66.7] | 88.7% [83.3–93.3] | 0.741 [0.690–0.793] | 150 |
| dtc_code | 100.0% [100.0–100.0] | 100.0% [100.0–100.0] | 1.000 [1.000–1.000] | 150 |
| symptom | 92.8% [88.2–96.7] | 97.4% [94.8–99.4] | 0.951 [0.918–0.977] | 153 |

`dtc_code` is an exact code lookup, `dtc_name` a semantic match on the fault name with the code removed, and `symptom` a Problem-Symptoms-Table entry resolved to its troubleshooting page. `symptom` reuses the indexed wording, so it bounds the linkage stage rather than paraphrase robustness.

## 7. Behaviour on real logged user queries

- n = 133 real Persian queries from production logs
- grounded (answered rather than refused): 98.5% [94.7–99.6]
- confidence bands: `{'medium': 131, 'low': 2}`
- latency p50/p90/p99: 3162 / 3358 / 3476 ms (production depth)

These queries have no relevance labels, so no accuracy figure is claimed for them here; they are the sample frame for expert review.

## 8. Answer quality, hallucination and the no-RAG baseline

*462 paid LLM calls through the production chat pipeline.*

| Measure | In-scope | Out-of-scope | Wrong-vehicle |
|---|---|---|---|
| n | 200 | 52 | 60 |
| grounded / answered | 93.5% [89.2–96.2] | 19.2% [10.8–31.9] | 91.7% [81.9–96.4] |
| link hallucination attempted (caught by gate) | 14.0% [9.9–19.5] | 7.7% [3.0–18.2] | 23.3% [14.4–35.4] |
| answers with an unsupported number | 1.0% [0.3–3.7] | 0.0% [0.0–16.8] | 1.9% [0.3–9.9] |
| unsupported share of numeric claims | 0.37% | 0.00% | 0.46% |
| no-LLM fallback served | 0.0% [0.0–1.9] | 0.0% [0.0–6.9] | 0.0% [0.0–6.0] |

Every fabricated link was removed before the user could see it: the rate above is what the model *attempted*, and the gate's catch rate on these runs was 100%. Numeric claims — torque values, capacities, voltages — were checked against the page text the answer was actually grounded in.

### Same LLM WITHOUT retrieval (general-purpose baseline)

- n = 150 identical questions, no context supplied
- declined to answer: 0.0% [0.0–2.5]
- answers containing specific numeric claims: 42 (42 numbers total)
- answers offering a source link: 116 (it has no corpus to cite, so any link would be fabricated)

## 9. Evaluation by automotive technical experts

**Not yet collected.** Expert review requires human reviewers and is the one item here that cannot be produced by measurement alone. The tooling is ready: `manage.py expert_sheet --build` emits a stratified sample as one rating sheet per reviewer with a Persian rubric, and `--score` reads them back and reports per-criterion means with Cohen's κ inter-rater agreement. No score is claimed until real reviewers return sheets.

## 10. Limitations

- Known-item queries are generated from page breadcrumbs by template, not written by technicians; they test topic-to-page retrieval, and are easier than free-form questions.
- Persian known-item queries are phrased using the same terminology dictionary the retrieval layer expands with. The `hybrid_ng` column is the ablation with that dictionary disabled and is the honest lower bound on the encoder's own cross-lingual ability.
- `keyword`, `bm25` and `dense` are vehicle-unaware; the production pipeline receives the vehicle scope because that is how it is used. Labels are vehicle-independent, so all systems are scored on the same targets.
- Numeric fidelity is a mechanical check that a number in the answer also occurs in that answer's own retrieved context. It is an upper bound on numeric hallucination: a correct number restated in a different unit or format counts as unsupported.
- Real user queries (n≈143) are unlabelled; no accuracy claim is made from them.
- The authoritative link-hallucination count is `strippedLinks`, computed by the route against everything retrieval returned (including related and cross-vehicle pages). A stricter client-side recomputation against the `sources` list alone flags a handful more, but every one inspected was a legitimate related-page link that `sources` simply does not enumerate — so that stricter count over-reports and is not used here.
- The out-of-scope refusal figure is dominated by how the corpus boundary was probed. Non-automotive and nonsense questions are refused reliably; automotive topics that merely happen to be absent are not, and that gap is a finding, not a rounding error.
