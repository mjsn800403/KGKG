# 06 — Permissions & RBAC

Authorization is layered: **who you are** (auth), **what your company bought** (purchase
scope), **what you were granted** (user grants), **what you may do** (capabilities), and
**who you may manage** (org hierarchy). `api/access.py` is the single implementation; every
surface (admin panel, team API, content serving, RAG) calls into it.

## 6.1 Identity: two separate auth systems

| | Portal users | Platform admin |
|---|---|---|
| Model | `PortalUser` + `AuthToken` | `PlatformAdmin` + `AdminAuthToken` |
| Login | `/api/auth/login/` (username **or email**) at `/login` | `/api/admin/login/` at `/admin/login` |
| Presented as | `Authorization: Bearer` or `kg_portal_token` cookie (SSR) | `Bearer`/`X-Admin-Token`; the static `KG_ADMIN_TOKEN` env value also passes (ops/scripts) |
| Blockers | inactive user OR company, `locked`, `access_expires_at` past, invite not accepted (`password_set=False`) | inactive admin |

Password hashing is Django's default (PBKDF2). Login is timing-equalized against a dummy
hash so account existence can't be probed. There is **no self-service password change or
reset flow yet** for either population (known limitation, doc 12).

## 6.2 What a company bought: purchase scope

`CompanyCarAccess(company, car, documents)` — the ceiling for everyone in the company.
`documents` empty = **all layers**. Changing it via the admin panel prunes user grants that
fall outside the new scope — except `admin_granted` user rows, which the platform admin
placed deliberately and which survive re-scopes.

Document layers (= sellable packages): `manual`, `parts`, `standard_time`,
`special_tools`, `full_spec` (`access.PACKAGE_CHOICES`).

## 6.3 What a user holds: grants

`UserCarAccess(user, car, documents, admin_granted)`.

Resolution for one car — `access.user_car_documents(user, car)`:
1. No user row → **no access** (holding a company purchase alone grants nothing).
2. Row with `admin_granted=True` → its own documents (empty = all). Purchase-independent.
3. Otherwise the row must be inside the company scope for that car (else no access), and
   effective docs = user docs ∩ company scope (user empty = inherit company scope).

`user_can_open_car` = "documents is not None". The fleet endpoint additionally requires the
car's DB file to exist on disk (`car_db_ready`) before showing it.

**Writers** (never write `UserCarAccess` directly):
- `apply_user_access(user, accesses, allow_admin_grants=…)` — admin panel + generic path.
  Clamps to company scope unless the caller is the platform admin sending
  `admin_granted`/override. Atomic replace, dedup by car.
- `apply_managed_access(manager, employee, accesses)` — the manager delegation path,
  "give only what you have": accepted cars ⊆ `manager_grantable_cars(manager)` (company
  purchase ∪ the manager's own admin-granted extras); layers clamped to the manager's
  ceiling; an explicit layer list that fully misses the ceiling **skips the car** (no
  silent upgrades); out-of-purchase cars are stored as `admin_granted` on the employee so a
  company re-scope can't revoke them; grants outside the manager's purview are untouched.

## 6.4 Content-serving enforcement (the paywall)

Backend-enforced since 2026-07-09 (before that it was frontend-only — doc 12 history):

- `views._guard_car_content` runs on **every** content endpoint (`car_view` model level,
  `search`, `assist`, `diagnose`, feedback): resolve the car → 401 without a session, 403
  without a grant.
- For **car-less** queries (general assistant), the user's full grant set is passed down as
  `allowed_cars` into RAG retrieval and the diag engine — results, related links,
  cross-vehicle matches, and labor links are all filtered to it. Empty grants ⇒ no grounded
  content (never "the whole fleet"). `allowed_cars` is part of every service-cache key so a
  narrow user can never receive a broad cached answer.
- Brand/year catalog levels stay public (sales page); `db_address` never leaves the server.
- `/api/chat` (Next) independently validates the session + `ai_eligible` before spending
  Metis credit.

## 6.5 Capabilities (feature flags per user)

`can_manage_team` — team area + company requests; `can_view_analytics` — analytics + PDF;
`ai_assistant_enabled` — personal AI switch. Stored on the user, **seeded** from the
org-role's defaults at creation/role-change (explicit values in the request win), and
individually editable afterwards.

AI eligibility is three-way AND — `user_ai_eligible`: user flag ∧ company flag
(`Company.ai_assistant_enabled`) ∧ the `manual` package present in the user's effective
package set.

Frontend visibility mirrors these flags (Sidebar shows Team/Requests/Analytics only when
capable) but the backend decorators are the enforcement (`require_manager`,
`require_analytics`).

## 6.6 Org hierarchy: who manages whom

Each company defines its own **positions** (`OrgRole`): `rank` (1 = top; smaller outranks)
and `manage_scope`:

- `org` — sees/manages every company member of strictly larger rank (the pyramid,
  independent of reporting lines);
- `subtree` — only transitive `reports_to` descendants;
- `none` — nobody.

Legacy users without an `org_role` fall back to the fixed 4-level ladder
(`ROLE_LEVEL`) and subtree scope.

**The authorization spine** — `manager_can_target(actor, target)`: same company ∧ actor
outranks target (strict) ∧ target ∈ `manageable_user_ids(actor)`. Every team read/write and
analytics scope flows through this (list, update, access, org chart, analytics via
`build_team_analytics`).

**Reporting-edge invariant:** a supervisor must *strictly outrank* their report
(`rank(reports_to) < rank(user)`). Enforced with Persian validation errors on member
create/update/chart-move, and **auto-repaired** by `enforce_org_consistency(company_id)`
after any operation that can invalidate edges (position change, role re-rank, role
delete+reassign, admin user-update). Repair walks the old chain upward
(`find_valid_supervisor`), falls back to the company's top-ranked active user, and is
cycle-safe.

**Role editing rules:** an actor may only create/edit/delete roles ranked strictly below
their own; quick role change re-seeds capability flags from the new role's defaults
(explicit flags in the same request win); responses carry
`adjustments:{caps_reseeded, reparented}` so UIs can toast what happened.

## 6.7 Platform admin

The admin token bypasses company scoping entirely: cross-company user/grant CRUD, purchase
scope editing, `admin_granted` rows, request handling, ops panels. Admin actions that touch
org structure run the same consistency repair as the team API. There is exactly **one**
PlatformAdmin in production; its password was rotated 2026-07-08 (history in doc 12).

## 6.8 Adding a permission-adjacent feature — checklist

1. Enforce in the backend first (decorator or explicit check via `access.py` helpers);
   UI-hiding is UX, not security.
2. If it reads content or RAG output, thread the user's allow-list (`allowed_cars`) and put
   it in any cache key.
3. If it writes grants, go through `apply_user_access`/`apply_managed_access` — never raw
   ORM writes.
4. If it moves people/roles, call `enforce_org_consistency` afterwards and return
   `adjustments` to the UI.
5. Coerce request ids at the boundary (`team._as_id`) — HTML selects send strings.
6. Add tests beside the feature (`tests.py` / `test_org_consistency.py` patterns) and
   update this doc + doc 05.
