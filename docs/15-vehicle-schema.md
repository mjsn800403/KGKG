# 15 — Structured Vehicle Data (schema.org) & the Ingestion Pipeline Extension

> Built 2026-07-18. Covers two related systems added together: the **download →
> parse** front half of the processing pipeline (LeMon downloader + ZIP inbox),
> and the **schema.org vehicle spec** layer built on top of the ingested data.

## 1. The full pipeline (7 stages)

Every ProcessingJob now runs (empty stages auto-skip, so a job with no queued
downloads/ZIPs behaves exactly like the old 4-stage pipeline):

| # | stage      | what it does | code |
|---|-----------|--------------|------|
| 1 | `download` | executes queued `DownloadRequest`s against lemon-manuals.org.ua via `lemon-downloader/downloader.py` (imported with importlib; 3s pacing, 429 backoff, atomic `.part` writes, LEMON filename convention), registers fetched ZIPs | `run_pipeline.stage_download`, `api/ingest.py execute_download_request` |
| 2 | `parse`    | runs pending `ZipPackage`s through `htmlparser_logical.process_single_zip` → `Database_warehouse/<stem>.db` + `static_warehouse/<stem>/` + catalog upsert; deletes the extracted tree + intermediate crawl DB afterwards (ZIPs are kept); disk guard pauses below 20 GB free (`KG_PIPELINE_MIN_FREE_GB`) | `stage_parse`, `ingest.parse_zip_package` |
| 3 | `catalog`  | `sync_car_catalog` (validating backstop; parse already upserted) | unchanged |
| 4 | `schema`   | builds/refreshes `VehicleSpec` rows for stale/missing cars | `stage_schema`, `api/vehicleschema.py` |
| 5 | `rag`      | ingest + embed + graph | unchanged |
| 6 | `diag`     | diagnostic sidecars | unchanged |
| 7 | `audit`    | data-quality report | unchanged |

`pending_work()` gained `need_download`, `need_parse`, `need_schema`; all feed
`has_work`, so `pipeline_tick` auto-starts jobs for queued downloads/ZIPs too.
Because download/parse CREATE work for the later stages mid-job, the worker
calls `replan_pending_stages()` after them — a stage planned at 0 items when
the job started is re-planned instead of wrongly auto-skipping.

## 2. ZIP inbox & queue

* Inbox roots: `/root/downloads` + `/root/Downloads` (env `KG_ZIP_INBOX`,
  colon-separated; first root receives new downloads).
* `manage.py scan_zips [--normalize] [--dry-run]` — discovers `*.zip`,
  reads `"<year> <brand> <model>/"` from each ZIP's inner top-level folder
  (no extraction needed), renames legacy model-only files to
  `LEMON <year> <brand> <model>.zip`, registers `ZipPackage` rows.
* **Duplicate guard**: a ZIP whose target stem already has a warehouse `.db`,
  or whose stem is already covered by another queued/done package, becomes
  `skipped_duplicate` — re-downloads of ingested cars can never clobber or
  duplicate a car. Admin can `skip_zip` / `requeue_zip`.
* The parser's own `processing_status` ledger (inside db.sqlite3) remains the
  parser-internal record; `ZipPackage` is the pipeline-facing queue.

## 3. Multi-year stems

Warehouse stem == catalog `car_name` == RAG `car_stem` (invariant, doc 03
§3.5). The 2025 fleet keeps plain names; **any other model year gets a
`" (YYYY)"` suffix**: `Corolla Cross LE, FWD (2023)`. Implemented in
`htmlparser_logical.warehouse_stem(car_name, year)` (DEFAULT_STEM_YEAR=2025)
and understood by:

* `api/rag/config.py` — `split_stem_year()`, `display_name()` (strips the
  suffix for UI labels; year lives in the catalog column), suffix-aware
  `car_meta()`.
* `api/dataquality.py` — a plausible model year (1980–2100) in a `"(N)"`
  suffix is **not** a copy counter (so 2023 cars are never flagged as
  duplicate uploads of the 2025 car).
* Public listings return `display_name` alongside `car_name`; URLs keep the
  full stem (`/Toyota/2023/Corolla%20Cross%20LE%2C%20FWD%20(2023)/`).

Also: `dataquality.is_electrified/is_pure_ev` now know whole-model
powertrains (Prius/Sienna/Venza/Crown/Mirai/RAV4 Prime…; Mirai counts as
no-combustion), so section expectations stay correct for the expanded fleet.

## 4. VehicleSpec (schema.org/Car)

One row per catalog car: `data` (schema.org `Car` dict, JSON-LD-ready),
`provenance` (`{field: {source: catalog|stem|manual|curated|derived,
detail}}`), `sections_used`, `builder_version`.

**Strict leave-null policy** — absent key = unknown, never guessed. Populated
tiers:

* catalog/stem: name, brand, manufacturer, model, vehicleModelDate/modelDate,
  vehicleConfiguration (trim), fuelType, driveWheelConfiguration,
  vehicleEngine (displacement + VIN engine code), vehicleTransmission
  ("Standard Trans" ⇒ Manual).
* manual (parsed from the car's own repair manual — `Quick Lookups/Fluids`,
  falling back to `Common Specs & Procedures`, plus `Tire Fitment`): fluid
  capacities/types as `additionalProperty` PropertyValues, refrigerant, ATF
  row ⇒ vehicleTransmission=Automatic, Fuel-Tank row ⇒ fuelCapacity, tire
  sizes.
* curated (`CURATED_MODEL_FACTS`, hand-reviewed, provenance-tagged):
  bodyType, numberOfDoors, whole-model fuelType (Prius=hybrid,
  Mirai=hydrogen, Prime=PHEV…).
* **Never populated** (no in-fleet source): enginePower, rated torque,
  weight, dimensions, wheelbase, seating, acceleration, emissions, VIN.

Build: `manage.py build_vehicle_schema [--stems ...] [--force]` or the
pipeline `schema` stage (staleness = missing row, older builder_version, or
car DB newer than built_at).

## 5. Where it surfaces

* **API**: `/​<brand>/<year>/<car>/?spec=1` (grant-gated; data + jsonld +
  provenance); public brand/year listings carry `display_name` + `spec`
  (identity-only `public_jsonld` — no manual-derived service data).
* **Public pages**: `[brand]/[year]/page.jsx` emits an
  `application/ld+json` ItemList of the identity specs.
* **Chatbot**: `/api/assist/` attaches `vehicle_specs` (a ≤15-line compact
  text block) for the pinned car; the chat route prepends it INSIDE the
  grounding context, so the phraser can answer spec questions while staying
  context-only.
* **Admin**: section «مشخصات خودروها» (`/api/admin/vehicle-specs/`) — fleet
  coverage, per-field counts, per-car spec + provenance viewer. The pipeline
  section gained the LEMON source-check form («بررسی منبع» dry-run listing,
  «افزودن به صف دانلود»), the ZIP queue table, and download-request rows.

## 6. Admin API additions (`/api/admin/pipeline/` POST)

`list_source {brand,year|url, filter}` (synchronous listing annotated with
downloaded/ingested flags) · `download {…}` (creates DownloadRequest) ·
`cancel_download {request_id}` · `scan_zips {normalize?, dry_run?}` ·
`skip_zip/requeue_zip {zip_id}`. GET payload gained `download_requests`,
`zip_queue{counts,rows}`, queue fields in `pending`/`settings`.

## 7. Gotchas

* `requests` had to be added to the backend venv (downloader dependency);
  bs4/html5lib were already present.
* The downloader stays standalone-usable (`bash run.sh <url> --filter
  "corolla cross" --dry-run`); it now names files with the LEMON convention
  itself, and still skips model-only-named leftovers.
* Legacy ProcessingJob rows predate the new stages — `Runner.stage()` returns
  None for unknown keys and `run_stage` no-ops, so resuming an old job never
  crashes.
* Parse-stage cleanup deletes the extracted tree AND the intermediate crawl
  `.db` next to the ZIPs — the old manual runs left ~57 GB of such residue.
* schema stage runs BEFORE rag on purpose: specs are ready in minutes while
  embedding can take days on a big backlog.
