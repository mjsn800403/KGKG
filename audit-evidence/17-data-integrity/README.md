# 17 · Data integrity: reconstructed activity in production

Opened 2026-11-02, revised after review the same day. GitHub #64, Jira KGTEC-20. Status: **open**. Investigation complete; remediation not started. Nothing was deleted, rewritten or moved, in production or in this repository's history.

## One-paragraph summary

On 2026-08-12 a one-off script (`KG_backend/gen_manual_activity.py`) inserted 102,054 rows into `api_activitylog` and marked each with the suffix « — بازسازی‌شده » ("reconstructed") in `detail`. The script's manifest says the rows were generated for evaluation/demo and are **not genuine user history**. On 2026-11-02, 83,486 of those rows are still in production, out of 86,212 rows in the table (96.8%). Analytics, recommendations, onboarding checks and some audit-evidence figures read that table without distinguishing them. This directory records what is established, what is not, how the numbers reconcile, and how to correct the record without losing any history.

**What this directory does and does not claim.** It establishes which rows are reconstructed, which are back-filled, and which existed before the batch. It does **not** establish that any other row is real human activity: the unmarked rows include demo-account, administrative and possibly test or scripted events, and none has been attested. Unmarked does not mean genuine.

## Decision on record (PM, 2026-11-02)

Preserve all records. Do not delete, rewrite, relocate or anonymize activity rows. Never present synthetic activity as genuine user behaviour. Do not use contaminated metrics as evidence of adoption, engagement or operational performance. Preserve historical evidence and production availability.

## Contents

| File | What it holds |
|---|---|
| `FINDINGS.md` | Verified inventory, the explanation of the 102,054 vs 83,486 gap, reconciliation of every figure, what is and is not established about the unmarked rows |
| `EVIDENCE_PRESERVATION.md` | Secure procedure for preserving the original data (not yet executed; needs authorization) |
| `REMEDIATION_DESIGN.md` | Provenance-and-attribution model, registry, migration and rollback, approval gates |
| `ATTESTATION_POLICY.md` | The evidence required before any rows may be treated as human activity |
| `COMPATIBILITY_ASSESSMENT.md` | What the change does to dashboards, onboarding and recommendations, and how uncertain data is shown |
| `TEST_PLAN.md` | Tests to write before any implementation, with acceptance criteria |
| `DISTRIBUTION_STATUS.md` | External distribution of the superseded figures: status unknown, outstanding questions |
| `CHECKSUMS.txt` | SHA-256 of the repository artifacts the findings depend on |

## Corrections made elsewhere (documentation only, originals preserved)

Each affected statement keeps its original text and gains a dated correction directly beside it:

- `audit-evidence/16-improvement-programme/METRIC_DEFINITIONS.md` (baseline paragraph)
- `audit-evidence/16-improvement-programme/evidence/ui/README.md` (feature-discovery baseline table)
- `docs/superpowers/specs/2026-10-30-feature-discovery-onboarding-design.md` (measured-problem table)
- `docs/CHANGELOG.md` (new Correction entry; the old entry is tagged superseded)
- `docs/13-guidance-system.md` §13.11 (denominator clarification and a caution)

## Metric status at a glance (as of 2026-11-02)

| Status | Metrics |
|---|---|
| **Superseded, do not use** | manual views 71,886 / 71,888; manuals "~34 of 34 seats" and "~94 %"; seats-ever-logged-in counts from `ActivityLog`; any 90-365 day usage, trend or retention figure; the claim that the assistant was "asked by 9" (9 seats opened it, 3 asked it; independent of #64) |
| **Uncertain** | feature-discovery "read manual" and any "has this seat ever done X" check that includes login, view_node, view_section or view_fleet; the premise of GitHub #49 |
| **Not affected by the reconstruction, but not verified as human activity** | parts catalogue 6 seats / 314 uses; assistant 3 seats asked / 43 questions (the 43 rows also appear in `ChatLog`, same 3 seats) and 9 seats opened it; search 0; CSV export 3; team PDF 8 (by 1 seat). They may include demo, test, administrative or scripted use |
| **Different source** | support-desk, knowledge-base, delivery (DORA), CI, coverage and security metrics were not examined for this issue |

**External distribution is UNKNOWN.** Whether any audit pack, report, dashboard view or screenshot containing the superseded figures left the team is not recorded anywhere this work could see, and the lack of a record is not evidence that nothing was shared. The open questions (recipients, artifacts, versions, dates, channel, correction delivery) are in `DISTRIBUTION_STATUS.md`. No correction has been sent to anyone.

## What this directory deliberately does not contain

No database dump, no raw activity rows, no usernames, phone numbers, credentials or backup artifacts. Seat identifiers appear only as internal numeric ids where needed. Sensitive evidence stays in secure backup storage (see `EVIDENCE_PRESERVATION.md`).
