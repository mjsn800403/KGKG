# ADR-0002 — Local, deterministic retrieval and diagnosis; the external LLM only phrases

**Status:** Accepted · **Since:** 2026-07 · **Recorded:** 2026-10-29

## Context
A wrong torque value or a procedure for the wrong engine can damage a vehicle or hurt a
technician. Customers pay for specific vehicles and document layers; the assistant must not
reveal anything else. Persian answers need a language model, and the available one (Metis) is
an external service.

## Decision
* **Retrieval runs locally.** That covers embeddings (bge-m3, offline), BM25, the
  relationship graph and scoring.
* **The diagnostic rule engine is local too,** and runs first for trouble codes and
  symptoms.
* **Access control is enforced inside retrieval** (`allowed_cars`) and is part of every cache
  key. The UI is not the boundary.
* **The LLM only rewrites already-retrieved context into Persian.** A faithfulness gate
  keeps links and buttons exactly as retrieved. If the LLM fails, a deterministic Persian
  fallback renders the same content.

## Consequences
* **No answer can cite a page the user may not open**, whatever the model does (RQ-09,
  RQ-10).
* **Quality depends on retrieval,** which is measured offline on gold sets (`qa/eval/`).
  Wrong-vehicle attribution is still an open action (A-05).
* **The embedding model is CPU-bound** and caps throughput (P-01: about 28 req/s at
  50 users). Light API requests queue behind embeddings.
* **torch cannot be upgraded casually.** Its version is pinned to the index; an upgrade
  needs an embedding-equivalence check (`ops/security/pip-audit-ignore.txt`).

## Evidence
`docs/08-ai-assistant-rag.md`, `api/rag/service.py` (`_acs` / cache identity),
`api/rag/test_service_paths.py`, `test_qa_content_guard.py`, frontend `chatPrompt.test.mjs`,
`audit-evidence/04-integration-testing/`.
