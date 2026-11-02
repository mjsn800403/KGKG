# 17 · Data integrity: reconstructed activity in production

Opened 2026-11-02. GitHub #64, Jira KGTEC-20. Status: **open**. Investigation complete; remediation not started. Nothing was deleted, rewritten or moved, in production or in this repository's history.

## One-paragraph summary

On 2026-08-12 a one-off script (`KG_backend/gen_manual_activity.py`) inserted 102,054 rows into `api_activitylog` and marked each with the suffix « — بازسازی‌شده » ("reconstructed") in `detail`. The script's manifest says the rows were generated for evaluation/demo and are **not genuine user history**. On 2026-11-02, 83,486 of those rows are still in production, out of 86,212 rows in the table (96.8%). Analytics, recommendations, onboarding checks and some audit-evidence figures read that table without distinguishing them. This directory records what is established, what is not, how the numbers reconcile, and how to correct the record without losing any history.

## Decision on record (PM, 2026-11-02)

Preserve all records. Do not delete, rewrite, relocate or anonymize activity rows. Never present synthetic activity as genuine user behaviour. Do not use contaminated metrics as evidence of adoption, engagement or operational performance. Preserve historical evidence and production availability.

## Contents

| File | What it holds |
|---|---|
| `FINDINGS.md` | Verified inventory, the explanation of the 102,054 vs 83,486 gap, reconciliation of every figure, classification of all 86,212 rows, what cannot be established |
| `EVIDENCE_PRESERVATION.md` | Secure procedure for preserving the original data (not yet executed; needs authorization) |
| `REMEDIATION_DESIGN.md` | Provenance-aware analytics design, migration and rollback, reader-by-reader behaviour, approval gates |
| `TEST_PLAN.md` | Tests to write before any implementation, with acceptance criteria |
| `CHECKSUMS.txt` | SHA-256 of the repository artifacts the findings depend on |

## Corrections made elsewhere (documentation only, originals preserved)

Each affected statement keeps its original text and gains a dated correction directly beside it:

- `audit-evidence/16-improvement-programme/METRIC_DEFINITIONS.md` (baseline paragraph)
- `audit-evidence/16-improvement-programme/evidence/ui/README.md` (feature-discovery baseline table)
- `docs/superpowers/specs/2026-10-30-feature-discovery-onboarding-design.md` (measured-problem table)
- `docs/CHANGELOG.md` (new Correction entry; the old entry is tagged superseded)
- `docs/13-guidance-system.md` §13.11 (denominator clarification)

## Metric status at a glance (as of 2026-11-02)

| Status | Metrics |
|---|---|
| **Unreliable, do not use** | manual views 71,886 / 71,888; manuals "~34 of 34 seats" and "~94 %"; seats-ever-logged-in counts from `ActivityLog`; any 90-365 day usage, trend or retention figure |
| **Uncertain** | feature-discovery "read manual" and any "has this seat ever done X" check that includes login, view_node, view_section or view_fleet; the premise of GitHub #49 |
| **Unaffected** | parts catalogue 6 seats / 314 uses; assistant 9 seats / 43 questions (matches the 43 rows in `ChatLog`); search 0; CSV export 3; team PDF 8; support-desk, knowledge-base, delivery (DORA), CI, coverage and security metrics |

No evidence was found, in the repository or in team chat, that any external evaluator received figures derived from the reconstructed rows. Whether any audit pack, dashboard or screenshot was shared outside the team is not recorded and is an open question for the product owner.

## What this directory deliberately does not contain

No database dump, no raw activity rows, no usernames, phone numbers, credentials or backup artifacts. Seat identifiers appear only as internal numeric ids where needed. Sensitive evidence stays in secure backup storage (see `EVIDENCE_PRESERVATION.md`).
