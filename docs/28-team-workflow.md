# 28 — Team workflow: GitHub, Jira, Slack, Trello

How work is tracked and handed over. The repository is the engineering record; this document records the
conventions that exist outside it, so a new engineer or agent does not have to reconstruct them from chat.
Sources: Slack `#kg-dev`, `#kg-decisions`, `#kg-releases` and Jira KGTEC read on 2026-11-04 [D]; branch and PR rules from
`.github/` and `docs/11` [C]. Roles and availability of people are **[U]** beyond what is stated.

## 28.1 People and roles [D]

- Product manager and owner of decisions/acceptance: GitHub `mjsn800403` (owner label `owner-pm`).
- Engineering: Ali Sartipi (GitHub `alistp27`, label `owner-ali`). `alistp27` has push + triage, not admin; cannot delete
  protected-pattern branches.
- Both maintainers own every document (`docs/OWNERS.toml`).

## 28.2 Systems and their roles

| System | Role | Notes |
|---|---|---|
| GitHub `mjsn800403/KGKG` (public) | engineering record: code, PRs, issues, CI | default branch `main`; integration branch `work`; both protected (PR required, 0 approvals, checks backend/frontend/security/images/governance; no force-push) [D 2026-11-02, re-check settings before relying] |
| Jira project `KGTEC` (site `mohammad-javad-salimi-s-workspace`) | task status source of truth | Business project type: To Do / In Progress / Done, no board or sprints. Mirrors GitHub issues. KGTEC-1..24 existed on 2026-11-04 |
| Trello board "KGtechvault Delivery" | read-only visual mirror of Jira | cards titled `KGTEC-n`; lags (KGTEC-22..24 had no card on 2026-11-04) |
| Slack `#kg-dev` | communication, daily reconcile digest, deploy notes from Ali | |
| Slack `#kg-releases` | one post per release: version, SHA, Jira keys, staging result, who promoted | channel purpose text was stale on 2026-11-02 |
| Slack `#kg-decisions` | one thread per decision: Question, Options, Recommendation, decision + Jira key | open then: KGTEC-4, 5, 6 |
| Confluence | **empty** (templates only); not used | |

## 28.3 Conventions

- Jira labels: owner `owner-pm` / `owner-ali`; GitHub link `gh-<issue>`; PR link `gh-pr-<n>`; epics `epic-*`; state
  `in-review`, `blocked`, `needs-decision`, `needs-approval`; area `area-ops`, `area-security`.
- Branch `KGTEC-<n>-title` or `type/KGTEC-n-title`; PR to `work`; title/body reference Jira key and a GitHub issue
  (`check_traceability.py` enforces an issue reference). WIP limit two per person.
- Use `refs #N` or `fixes #N`: **neither closes the issue**, because GitHub only auto-closes when merging to the
  default branch (`main`) and PRs merge to `work`. Close issues by hand after production verification, and say so in the PR. [D Slack 2026-11-04]
- Every PR: `.github/pull_request_template.md` (tracking, how verified, checklist incl. `docs/` and ADR).
- Releases: CI stages on a green push to `work`; a person runs `kgkg-promote <sha>`; Ali has announced deploys in `#kg-dev`.

## 28.4 Automation that exists

- Scheduled task `kgkg-daily-reconcile` (Claude desktop app, 09:03 local): read-only comparison of GitHub, Jira and Trello,
  posts one digest to `#kg-dev` labelled "Proposed, not applied". It runs only while the desktop app is open. A separate
  proposal for a server-side, least-privilege version is KGTEC-21 (not approved). [D]
- No Jira automation rules, no GitHub-for-Jira app, no Slack-Jira integration are verified **[U]**.
- Dependabot (`.github/dependabot.yml`), CodeQL default setup, secret-scanning push protection are enabled [D 2026-11-02].

## 28.5 Pending decisions (owner-pm) — tracked in doc 27

KGTEC-4 pricing between 29 and 30 seats; KGTEC-5 production checkout branch and Tunnel vs SSH for CI; KGTEC-6 host
changes (hung probes, staging rows, xrdp); KGTEC-19 independent penetration test; KGTEC-20 reconstructed activity rows;
KGTEC-16 delete `rag-db-improvements`; KGTEC-18 backups (far-side retention, secrets escrow; extend to `kgkg_vec`, GitHub #80).
