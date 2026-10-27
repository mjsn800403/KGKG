# Team, roles and domain evidence (criteria 11, 12, 13)

**Status: pending verification.** This package contains no personnel data.
Names, degrees, employment history and time allocation must come from the
company's own authorized records (employment contracts, insurance lists,
diplomas, CVs signed by the person). Nothing below was inferred from the
repository, and nothing should be.

## What the repository can show honestly

Contribution history (`git shortlog -sne --all`, 2026-06-19 → 2026-10-27):
two human contributors appear under several identities, plus CI and deploy
bots. Commit counts measure activity, not role or allocation, and must not be
presented as a staffing percentage.

Domain mastery visible in the code itself (verifiable by reading it):

* Automotive after-sales domain model: role ladder for after-sales
  departments, per-vehicle and per-document-layer entitlements (repair
  manual, special tools, parts catalog, standard labour times, full specs)
  — `api/access.py`, `api/models.py`.
* OEM service-information ingestion: crawler and parsers for manufacturer
  manual sites and ZIP packages, per-vehicle SQLite manual stores, a parts
  catalog builder — `api/ingest.py`, `api/partsingest.py`,
  `api/tis_crawler.py`, `tis_parser.py`, `htmlparser_logical.py`.
* Diagnostic knowledge: DTC/symptom rule engine built per vehicle from
  manual content — `api/rag/diag.py`, `api/rag/diag_build.py`.
* Bilingual (English → Persian) automotive terminology store with QA-gated
  translation and 3,415 adjudicated term pairs — `api/rag/terms.py`,
  `docs/14-terminology.md`.
* Retrieval system designed in-house: hybrid lexical/semantic scoring,
  graph centrality, adaptive depth, semantic cache, human-feedback loop,
  offline evaluation against versioned gold sets —
  `api/rag/*`, `docs/08-ai-assistant-rag.md`.

Market/competitor analysis is not in the repository. If such work exists
(sales deck, market study), add it here with its date and author.

## Templates to complete from authorized records

### T-12 Human resources per lifecycle role (criterion 12)

| Person (as in contract) | Role(s): analyst / developer / tester / DevOps / UX / PM / domain expert | FTE share on KGTechVault (%) | Period (from–to) | Source document |
|---|---|---|---|---|
| | | | | |

Totals must be computed from this table, not estimated.

### T-13 Key personnel qualifications (criterion 13)

| Person | Degree, field, institution, year | Relevant prior projects (with dates) | Technical skills used on this product (languages, frameworks, tools) | Evidence attached (file name) |
|---|---|---|---|---|
| | | | | |

### T-11 Domain and market knowledge (criterion 11)

| Item | Owner | Date | Evidence |
|---|---|---|---|
| Customer interviews / requirement sessions with workshops | | | |
| Competitor analysis (domestic and international) | | | |
| Technology trend review (e.g. OEM service-information access, AI assistants for technicians) | | | |
