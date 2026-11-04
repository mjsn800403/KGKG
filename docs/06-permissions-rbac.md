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
hash so account existence can't be probed. Portal users have an SMS second factor (OTP) and SMS-based account recovery
(`api/auth/recover/start|reset`, [26-auth-and-sessions.md](26-auth-and-sessions.md)); the admin login has an SMS second factor too
(`ADMIN_REQUIRE_2FA` can make it mandatory). *Historical:* when this chapter was written (2026-07) neither population had a reset flow.

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
`ai_assistant_enabled` — personal AI switch. Stored on the user and driven by the user's seat permission (`NodePermission.ai_eligible`,
synced by `orggraph.sync_node_to_user`) and, for admin-created users, by `access.default_capabilities_for_role`; they remain
individually editable by the platform admin.

AI eligibility is three-way AND — `user_ai_eligible`: user flag ∧ company flag
(`Company.ai_assistant_enabled`) ∧ the `manual` package present in the user's effective
package set.

Frontend visibility mirrors these flags (Sidebar shows Team/Requests/Analytics only when
capable) but the backend decorators are the enforcement (`require_manager`,
`require_analytics`).

## 6.6 Org hierarchy: who manages whom

**Current model: the org-graph canvas** (`OrgGraph`, `OrgNode`, `NodePermission`; `api/orggraph.py`, `api/orggraph_api.py`).
The old per-company position model (`OrgRole` with `rank` and `manage_scope`) was removed in migration 0016; `CompanyRole` now only holds
selectable role *labels*. What replaced it:

- One graph per company; each `OrgNode` is a seat with an optional `parent` and at most one occupant. Exactly one root per graph (database
  constraint `one_root_per_graph`). **Only the root-seat occupant (the company super-admin) may edit** the graph, create users into seats and set
  seat permissions (`require_root` in `orggraph_api.py`); everybody else gets a read-only view.
- `NodePermission` (per seat): `car_access` (list of `{car_id, documents}`), `ai_eligible`, `admin_panels` (subset of `metrics`, `data_quality`, `ingest`,
  `terminology`, `reports`). It is an **authoring** surface: `orggraph.sync_node_to_user` is the one-way bridge that rewrites the occupant's real
  enforcement state (`UserCarAccess` rows, `PortalUser` flags) whenever a seat's permission or occupant changes. Content, RAG and chat gating still read
  `UserCarAccess` and the user flags, not the graph. The root's grants are applied as admin grants (not capped by purchase) and the root is always AI
  eligible and holds every admin panel implicitly; any other seat can never exceed what the company bought (clamped by `apply_user_access`).
- **Who may manage whom**, `manager_can_target(actor, target)`: same company, actor has `can_manage_team`, and target sits **below the actor on the canvas**
  (`graph_subtree_user_ids`). Sitting below *is* the authority; the old strict-rank comparison survives only as a legacy path for an actor with no seat
  (a company whose graph was never seeded), where the former `rank` / `manage_scope` / `reports_to` rules apply. `manageable_user_ids` is the matching set used
  for the team chats, analytics and recommendations scope.
- **Who sees the team page:** `user_can_view_team`: the root seat, or any seat that has children. Leaf seats and seatless users do not.
- `reports_to` is kept mirrored from the canvas parent edges (`sync_reports_to_from_graph`) because analytics ordering and
  `enforce_org_consistency` still use it. Break-glass: the platform admin can move the root onto another user (`api/admin/org/reassign-root/`,
  `reassign_root`), and `add_root_on_top` transfers 0-level ownership without redrawing the chart.
- A company's graph is seeded on first use (`seed_graph_for_company`, called from the org API and from root reassignment: root = the top person, who holds the company's whole purchased scope); admin-created
  employees are seated under the root (`seat_new_user`, called from the admin user-create path).

**Legacy invariants that still run:** `enforce_org_consistency(company_id)` (called from the admin user-update path) re-parents any user whose
`reports_to` no longer points to a strictly higher legacy rank, walking the old chain upward (`find_valid_supervisor`) and falling back to the company's top
active user; it is cycle-safe. Whether this repair is still meaningful for graph-seated companies is **[U]**: the canvas parent edge is the live truth and
`reports_to` is its mirror.

## 6.7 Platform admin

The admin token bypasses company scoping entirely: cross-company user/grant CRUD, purchase
scope editing, `admin_granted` rows, request handling, ops panels. Admin actions that touch
org structure run `enforce_org_consistency` and, for the root seat, `reassign_root`. There is exactly **one**
PlatformAdmin in production; its password was rotated 2026-07-08 (history in doc 12).

## 6.8 Adding a permission-adjacent feature — checklist

1. Enforce in the backend first (decorator or explicit check via `access.py` helpers);
   UI-hiding is UX, not security.
2. If it reads content or RAG output, thread the user's allow-list (`allowed_cars`) and put
   it in any cache key.
3. If it writes grants, go through `apply_user_access`/`apply_managed_access` — never raw
   ORM writes.
4. If it moves people between seats, go through the org-graph API (`api/org/*`) so `sync_node_to_user` and `sync_reports_to_from_graph` run; do not
   edit `reports_to` or grants directly.
5. Coerce request ids at the boundary (`team._as_id`) — HTML selects send strings.
6. Add tests beside the feature (`tests.py` / `test_org_consistency.py` patterns) and
   update this doc + doc 05.
