# 16 — Parts Catalog (کاتالوگ قطعات یدکی)

> Added 2026-08-04. OEM EPC parts data (Toyota Corolla Cross, PartSouq legacy-engine
> crawl) served as a per-vehicle Parts module, isolated to the parts-only test
> vehicles granted to the Test Company («شرکت تست قطعات»).

## What it is

A second content surface next to the Repair Manuals: per-vehicle **exploded-view
diagrams + structured parts tables** (part number, callout code, name EN/FA,
quantity, notes, production range). Navigation mirrors the manuals — CardGrid
tree until the last node — but the leaf renders `PartsViewer` (pan/zoom diagram
+ table), not manual HTML.

## Data flow

```
/root/Desktop/partsouq2/            raw crawl (101 frames, ~42.7k group pages)
        │  manage.py import_parts --stage scan|parse|validate|build|catalog|audit
        ▼
/root/parts_build/staging.db        staging + validation gates + reports
        ▼
Database_warehouse/_parts/<car_name>.db     per-vehicle serving DBs
static_warehouse/_parts_assets/*.gif        shared diagram images (nginx /kg-api/media/)
```

- **Vehicles** are parts-only `Car` rows (`db_address=''` → invisible on every
  public catalog surface and in `car_view`); stem pattern `"... (Parts <year>)"`.
- **Frames** (source configurations, e.g. `MXGA10L-AHXGHA`) group into vehicles
  per `vehicle_map.json`: US frames by (year, grade); other markets by engine
  family. Inside a vehicle the configuration picker (`?cfg=`) selects a frame.
- **Quality gates** (hard): every published row has part number + parsed
  quantity + name (xref rows are kept but flagged `is_xref`); every section's
  image exists; no empty groups/categories; no duplicate sibling titles;
  Cloudflare-failed pages excluded and reported. Reports live in
  `/root/parts_build/reports/` (`vehicle_map.md`, `validate.md`, `audit.json`)
  and `Database_warehouse/_parts/report_summary.json` (admin endpoint).

## Backend

- `api/partsingest.py` — parser/staging/build/audit (no module-level Django
  imports; parse uses a spawn pool).
- `api/management/commands/import_parts.py` — the pipeline CLI (idempotent,
  resumable; `build` refuses on hard validation issues unless
  `--allow-hard-issues`, which prunes the affected groups).
- `api/parts.py` — serving:
  - `GET /api/parts/<brand>/<year>/<model>/` → `{car, frames[], default_frame,
    counts}`; auth = portal token + **`'parts' ∈ user_car_documents`** (403
    otherwise, same Persian error as manuals), then `parts_db_ready` (404).
  - `?cfg=<frame>` [+ repeated `?seg=`] → node arrays (manuals-shaped dicts) or
    the leaf object `{leaf, group, sections:[{figure_code, caption, image,
    parts[]}]}`.
  - `GET /api/admin/parts/` (admin token) → import/audit summary.
- `portal.fleet_view` includes parts-ready cars and adds additive
  `has_manual` / `has_parts` flags; `admin_cars_view` rows gain `has_parts`;
  `_user_dict` access rows gain `parts_ready`.
- `dataquality.run_audit` reports parts-only vehicles under
  `parts_only_vehicles`, not as missing-DB errors. `remediate` never touches
  them (it only acts on top-level warehouse files).

## Frontend

- Routes: `[brand]/[year]/[model]/parts/page.jsx` (config picker + top groups)
  and `parts/[...ppath]/page.jsx` (tree levels / leaf). Static `parts` segment
  wins over the manuals catch-all. `?cfg=` rides as query; segments go to the
  API as `?seg=` (slash-safe).
- `components/PartsViewer.jsx` (leaf UX), `components/PartsNav.jsx`
  (breadcrumb/picker/frame info + `PARTS_CATEGORY_ANALYTICS`).
- `utils/api.jsx`: `fetchPartsRoot`, `fetchPartsNodes`.
- Vehicle root page fetches manuals + parts in parallel and renders whichever
  exists (parts-only vehicles no longer dead-end); fleet tiles show a
  «کاتالوگ قطعات» chip from `has_parts`.
- Styles: `.parts-*` block appended to `globals.css`.
- Activity: pages beacon `action='parts_view'` with an explicit canonical
  `category` (EPC category → engine/transmission/body/electrical).

## Known behaviours worth knowing before enabling the real company

- **The EPC tree is a DAG; we publish a tree.** A functional group can legitimately
  hang under two parents in the source treegrid (verified: ~1 node per frame).
  The importer keeps a node at its FIRST placement, so every group is reachable
  exactly once — no parts are lost, but a group visible under two parents on
  partsouq.com appears under one here. Duplicate placements are logged as
  `treegrid_dup_conflict` warnings.
- **Cross-reference rows.** ~21% of source rows carry a part number whose
  callout equals the number itself, with no name and no quantity. These are the
  catalog's own reference/substitution entries, not broken records: they are
  imported with `is_xref=1`, exempted from the quantity gate, and rendered
  distinctly as «مرجع جایگزین». Everything else must have number + quantity +
  name or it is excluded and counted in the report.
- **`X` quantity** means the EPC's "as required" (sealants, clips). It is a real
  published quantity, stored in `qty_display`, with `qty` left NULL.
- **Layer revocation is not retroactive** (pre-existing platform behaviour, not
  specific to parts): `access.effective_documents` returns a user's explicit
  document list without intersecting it with the company scope, so removing
  `parts` from a company's purchase does NOT revoke it from seats that hold it
  explicitly. To revoke, re-apply the seats' grants (or drop the car from the
  company scope entirely, which prunes user rows).
- **Diagram images are served unauthenticated** from `/kg-api/media/_parts_assets/`,
  exactly like manual images from `/kg-api/media/<car>/`. The JSON around them is
  grant-gated; the image bytes are not. This matches the platform's existing
  posture — change both together if that ever needs to tighten.

## Isolation / rollout

Parts vehicles are granted ONLY to the Test Company (`documents:['parts']`).
Company 1 (خدمات گستر) holds no rows for them; public brand/year/purchase
surfaces never list them (`car_db_ready` false). Enabling the real company
later = grant the same car ids to company 1 via the admin access endpoint —
no code change.

Licensing note: diagrams/data originate from partsouq.com (OEM content).
Internal test review is fine; **resolve redistribution rights (license Laximo)
before granting the real company** — see `/opt/partsouq/DESIGN_DECISIONS.md`.

## Tests

`api/tests_parts.py` — parser units (treegrid, sanitizer inversion, xref/qty
classification, section↔table pairing, Cloudflare pages) + pipeline-to-serving
integration (temp warehouse via `KG_PARTS_DIR`) + HTTP auth/isolation/walk/leaf
shapes + fleet flags + public-catalog invisibility.
