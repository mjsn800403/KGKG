# Architecture Decision Records

One file per decision that shapes the system and would be expensive to reverse. Format
(Nygard): context → decision → consequences, plus the evidence that holds it in place.

* **Recording.** ADR-0001..0006 were recorded on 2026-10-29 for decisions already in force;
  each states when the decision was actually taken and where that is visible (commits,
  CHANGELOG, docs).
* **New decisions** get the next number, status `Proposed` until merged, then `Accepted`.
* **Replacing a decision.** Never edit an accepted ADR's decision. Write a new one and mark
  the old one `Superseded by ADR-NNNN`.

| ADR | Decision | Status | Since |
|---|---|---|---|
| [0001](0001-sqlite-and-per-vehicle-databases.md) | SQLite (WAL) for app data; one read-only SQLite file per vehicle manual | Accepted | 2026-06 |
| [0002](0002-local-retrieval-llm-as-phraser.md) | Local, deterministic retrieval and diagnosis; the external LLM only phrases | Accepted | 2026-07 |
| [0003](0003-containers-with-zero-gap-swap.md) | Release as sha-tagged containers; backend swapped with SO_REUSEPORT, no gap | Accepted | 2026-10-16 |
| [0004](0004-only-a-person-promotes.md) | CI stages; only a person promotes, on staging + E2E evidence | Accepted | 2026-10-27 (E2E: 2026-10-29) |
| [0005](0005-self-hosted-error-monitoring.md) | Self-hosted GlitchTip, Prometheus, Loki, Grafana; no SaaS observability | Accepted | 2026-08-05 / 2026-10-13 |
| [0006](0006-docs-as-code.md) | Documentation lives in the repo and ships with the change | Accepted | 2026-07 |
