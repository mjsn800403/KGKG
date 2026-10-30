# Improvement programme — 2026-10-30

The 2026-10-30 evaluation raised four critical findings: no verifiable team and
task management, no business-intelligence infrastructure, no formal knowledge
transfer, and customer feedback collected by telephone. This directory is the
engineering response.

Read in this order:

| File | What it is |
|---|---|
| `ROOT_CAUSE_ANALYSIS.md` | Each finding taken apart: what the evaluators saw, why the implementation failed it, whether the cause is architectural, functional, operational, organisational or evidential, what already exists, the alternatives considered and rejected with reasons, and what evidence would prove resolution |
| `CRITERIA_10_MATRIX.md` | The ten criteria and the four findings with an honest status each, and a list of the claims this package deliberately does not make |
| `IMPLEMENTATION_PHASE1.md` | What was actually built and tested on this branch, with the verification method — and a full statement of what is not done |
| `METRIC_DEFINITIONS.md` | The BI semantic layer: one entry per metric with its calculation, source column, hand-reproducible query and test. A metric not defined here may not appear on a dashboard |
| `ROADMAP.md` | Phases 1b–6 in dependency order, with falsifiable acceptance criteria, and what the programme refuses to do |
| `evidence/` | Machine output: baseline and branch failure sets (identical), the verbose run of the new suites, a reproducible sample of the metrics endpoint and the script that produces it |

## The one-paragraph summary

The repository was already strong where it had been audited — CI, security
scanning, load testing, mutation testing, an SRS, ADRs, an enforced OpenAPI
spec, containerised gated deployment, monitoring. The four findings sit in the
gaps between that work and the organisation around it. Three of the four have
causes that are organisational or evidential, and are fixed by configuring and
defining rather than by building. **The fourth was a bug**: the support API was
gated on `can_manage_team`, so most seats could not file a ticket at all and
the telephone was their only channel. That is now removed, together with the
single-`admin_note` design that forced even managers onto the phone for any
back-and-forth. The channel, the SLA clocks, the ownership, the satisfaction
question, the feedback channel, the knowledge base and the metrics exist as a
tested API; none of it has an interface yet, and that is the next piece of work.

Nothing here is evidence of production usage, and no development history,
test result, customer feedback or operational figure in this directory was
fabricated.
