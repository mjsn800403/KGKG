# External distribution: status UNKNOWN

Opened 2026-11-02. This document records what is **not known** about whether figures derived from the reconstructed activity left the team. It does not conclude that nothing was shared, and no one should read it that way: the absence of a record in the repository or in team chat is not evidence that no distribution happened. No correction has been sent to anyone as part of this work, and none will be sent without the product owner's decision.

## What is known

The superseded figures appear in these tracked documents (each now carries a dated correction):

| Artifact | Figure |
|---|---|
| `audit-evidence/16-improvement-programme/METRIC_DEFINITIONS.md` | 71,886 manual views, 34 active seats, "assistant asked by 9" |
| `audit-evidence/16-improvement-programme/evidence/ui/README.md` | manuals "~34 of 34", 71,886; assistant 9 |
| `docs/superpowers/specs/2026-10-30-feature-discovery-onboarding-design.md` | same, with "~94 %" and "~50 %" discovery |
| `docs/CHANGELOG.md` | 71,886 manual views, "assistant asked by 9" |
| `docs/13-guidance-system.md` | "unopened by 28 of 34 active seats" |

The reconstructed rows also feed live admin and team reports, so any export, screenshot or dashboard view taken from them is potentially affected. The search for other documents was keyword-based and may have missed some.

## Outstanding questions

All are for the product owner, who is the only person able to answer them. Until they are answered, distribution stays "unknown".

### Recipients
1. Who has received any audit pack, evaluation material, report or screenshot containing activity-derived figures? Names, organisations, roles.
2. Were any customers, resellers, vendors, auditors, funders or other third parties shown a dashboard or report from the live admin or team views?
3. Who has read access to the repository (collaborators, deploy keys, installed apps)? Automated third-party readers such as the pull-request review connector, CI and code-scanning services process repository contents; are they within the intended audience?
4. Who has access to the Jira, Trello and Slack spaces where figures were quoted, including guests?

### Artifacts
5. Which artifacts were shared: whole audit-evidence directories, specific files, exported PDFs or slide decks, spreadsheets, admin-panel exports, screenshots of the traffic, usage, funnel or onboarding views, or the metrics endpoint?
6. Did any shared artifact quote the reconstructed rows' totals, trends or seat counts directly, or only a conclusion drawn from them (for example "the manuals are widely used")?

### Versions and dates
7. For each shared artifact: which version (commit SHA, file date, export date) and when was it sent or shown?
8. Was anything shared before the reconstructed rows were identified on 2026-11-02, and does any shared version predate the 2026-10-30 baseline text?

### Channel
9. How was each item delivered (email, shared drive, repository access, meeting, screen share, chat)? Is a copy retained, and can it be recalled or marked superseded?

### Correction delivery (decisions, not actions taken)
10. Who decides whether a correction is sent, to whom, and in what words? The documents in this PR can serve as the erratum text, but nothing has been sent.
11. How will delivery and receipt be recorded, and who owns recalling or annotating superseded copies?
12. If a recipient relied on a superseded figure for a decision, who is responsible for contacting them?

## Handling until answered

- Treat the superseded figures as potentially distributed.
- Do not describe the situation as "not shared" in any document, issue or message.
- Record each answer in GitHub #64 with the question number, the answerer and the date, and update this file in a reviewed PR.
