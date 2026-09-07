"""Shared RBAC, subscription package, and AI eligibility helpers."""

# Top-down hierarchy (1 = highest). Department name is configurable per company;
# the level numbers never change.
ROLE_CHOICES = [
    ('after_sales_manager', 'مدیر خدمات پس از فروش'),
    ('after_sales_head', 'رئیس خدمات پس از فروش'),
    ('after_sales_supervisor', 'سرپرست خدمات پس از فروش'),
    ('after_sales_specialist', 'کارشناس خدمات پس از فروش'),
]

ROLE_LEVEL = {
    'after_sales_manager': 1,
    'after_sales_head': 2,
    'after_sales_supervisor': 3,
    'after_sales_specialist': 4,
}

# Legacy role ids mapped to the new hierarchy (migration + runtime tolerance).
LEGACY_ROLE_MAP = {
    'technical_expert': 'after_sales_specialist',
    'technical_staff': 'after_sales_specialist',
}

# Subscription packages (modular — add new ids here and in DOC_TYPE_CHOICES).
PACKAGE_CHOICES = [
    ('manual', 'راهنمای تعمیرات'),
    ('special_tools', 'ابزارهای مخصوص'),
    ('parts', 'کاتالوگ قطعات یدکی'),
    ('standard_time', 'زمان استاندارد تعمیرات'),
    ('full_spec', 'مشخصات کامل خودرو'),
]

DOC_TYPE_CHOICES = PACKAGE_CHOICES  # same ids, used in car/doc grants

VALID_PACKAGES = {p for p, _ in PACKAGE_CHOICES}
VALID_DOCS = VALID_PACKAGES
VALID_ROLES = {r for r, _ in ROLE_CHOICES}

AI_REQUIRED_PACKAGE = 'manual'


def normalize_role(role):
    return LEGACY_ROLE_MAP.get(role, role)


def role_label(role, department_label=''):
    rid = normalize_role(role)
    base = dict(ROLE_CHOICES).get(rid, rid)
    if department_label and department_label != 'خدمات پس از فروش':
        return base.replace('خدمات پس از فروش', department_label)
    return base


def role_can_manage(actor_role, target_role):
    """Higher-level roles inherit authority over lower-level roles."""
    a = ROLE_LEVEL.get(normalize_role(actor_role), 99)
    t = ROLE_LEVEL.get(normalize_role(target_role), 99)
    return a < t


def effective_documents(access_row, company_scope=None):
    """Resolved package list for one car grant."""
    docs = access_row.documents or []
    if docs:
        return [d for d in docs if d in VALID_PACKAGES]
    if company_scope is not None:
        return [d for d in company_scope if d in VALID_PACKAGES]
    return list(VALID_PACKAGES)


def user_package_set(user):
    """All subscription packages a user effectively holds (any car)."""
    pkgs = set()
    company_scope = {
        a.car_id: (a.documents or list(VALID_PACKAGES))
        for a in user.company.car_accesses.all()
    }
    for a in user.car_accesses.select_related('car'):
        if a.admin_granted:
            pkgs.update(effective_documents(a))
        elif a.car_id in company_scope:
            scope = company_scope[a.car_id] or list(VALID_PACKAGES)
            pkgs.update(effective_documents(a, scope))
    return pkgs


def parse_seat_plan(raw):
    """Validate and normalize seat_plan rows from a purchase request.

    Returns (rows, total_seats) on success or (None, error_message) on failure.
    """
    if not isinstance(raw, list) or not raw:
        return None, 'حداقل یک نقش/واحد سازمانی را مشخص کنید.'
    rows = []
    total = 0
    for item in raw[:50]:
        if not isinstance(item, dict):
            continue
        role = normalize_role(str(item.get('role') or '').strip())
        if role not in VALID_ROLES:
            return None, 'نقش سازمانی نامعتبر است.'
        department = (str(item.get('department') or 'خدمات پس از فروش')).strip()[:80]
        try:
            count = int(item.get('count'))
            if count < 1 or count > 1000:
                return None, 'تعداد کاربر هر نقش باید بین ۱ تا ۱۰۰۰ باشد.'
        except (TypeError, ValueError):
            return None, 'تعداد کاربر هر نقش الزامی است.'
        note = (str(item.get('note') or '')).strip()[:500]
        rows.append({'role': role, 'department': department, 'count': count, 'note': note})
        total += count
    if not rows:
        return None, 'حداقل یک نقش/واحد سازمانی را مشخص کنید.'
    return rows, total


def user_ai_eligible(user):
    """AI requires Repair Manual (manual) in the user's effective packages."""
    if not user.ai_assistant_enabled:
        return False
    if not user.company.ai_assistant_enabled:
        return False
    return AI_REQUIRED_PACKAGE in user_package_set(user)


def user_car_documents(user, car):
    """Resolved document layers ``user`` effectively holds for ``car``, or None
    if the user has no access to that car at all.

    Mirrors ``user_package_set`` but for a single car: an admin-granted row wins
    outright; a purchase-based row must fall inside the company's purchased scope
    for that car (a company that lost the car in a re-scope revokes it for every
    seat). This is the per-car authorization used to gate content serving.
    """
    ua = user.car_accesses.filter(car_id=car.id).first()
    if ua is None:
        return None
    if ua.admin_granted:
        return set(effective_documents(ua))
    cca = user.company.car_accesses.filter(car_id=car.id).first()
    if cca is None:
        return None
    scope = cca.documents or list(VALID_PACKAGES)
    return set(effective_documents(ua, scope))


def user_can_open_car(user, car):
    """True iff ``user`` may open ``car``'s manual (any effective grant to it)."""
    return user_car_documents(user, car) is not None


def manager_grantable_cars(manager):
    """``{car_id: set(grantable_docs)}`` — every car this manager may delegate.

    A manager may ALWAYS distribute the company's purchased cars (capped at the
    company's purchased layers), PLUS any car the platform admin granted the
    manager directly beyond that purchase (capped at the manager's own layers,
    and delivered by apply_managed_access as an admin grant so a later company
    re-scope can't silently revoke it). This is the source of truth for what the
    team UI offers and what apply_managed_access accepts.
    """
    company_scope = {
        a.car_id: (set(a.documents) if a.documents else set(VALID_PACKAGES))
        for a in manager.company.car_accesses.all()
    }
    out = {cid: set(docs) for cid, docs in company_scope.items()}
    for a in manager.car_accesses.all():
        if a.admin_granted and a.car_id not in company_scope:
            out[a.car_id] = set(effective_documents(a))
    return out


def apply_managed_access(manager, employee, accesses):
    """Replace ``employee``'s car grants with a MANAGER-delegated set.

    Rules ("give only what you have"):
      * only cars the manager can access are accepted (manager_grantable_cars);
      * granted document layers are clamped to the manager's own layers;
      * a car the manager holds beyond the company's purchase (admin-granted to
        the manager) is delegated as ``admin_granted`` on the employee so a later
        company re-scope prune can't silently revoke it;
      * grants for cars OUTSIDE the manager's purview (e.g. set directly by the
        platform admin) are left untouched — the manager only manages its own.
    """
    from django.db import transaction
    from .models import UserCarAccess  # lazy
    if not isinstance(accesses, list):
        raise ValueError('accesses must be a list')
    grantable = manager_grantable_cars(manager)
    company_car_ids = set(employee.company.car_accesses.values_list('car_id', flat=True))
    seen = set()
    with transaction.atomic():
        # Only clear the portion of the employee's grants the manager controls.
        employee.car_accesses.filter(car_id__in=grantable.keys()).delete()
        for a in accesses:
            car_id = a.get('car_id')
            if car_id in seen or car_id not in grantable:
                continue
            allowed = grantable[car_id]
            requested = a.get('documents')
            if requested:
                # An explicit layer list: clamp to what the manager holds. If the
                # request names ONLY layers the manager lacks, the intersection is
                # empty — skip the car entirely rather than silently upgrading the
                # employee to every layer the manager happens to hold.
                docs = [d for d in requested if d in allowed]
                if not docs:
                    continue
            else:
                # Omitted/empty documents == "grant this whole car" — default to
                # the manager's full ceiling (never store empty, which reads as
                # "all packages" and would exceed that ceiling).
                docs = sorted(allowed)
            UserCarAccess.objects.create(
                user=employee, car_id=car_id, documents=docs,
                admin_granted=(car_id not in company_car_ids))
            seen.add(car_id)


def car_db_path(car):
    """Absolute path to a car's content database on this server."""
    from django.conf import settings
    from pathlib import Path
    main_dir = Path(settings.DATABASES['default']['NAME']).parent
    return main_dir / (car.db_address or '').replace('\\', '/')


def car_db_ready(car):
    """True when the car's per-vehicle database file exists on disk.

    TTL-cached (see cardb.ready_path): catalog listings check the whole fleet
    per request, and one stat() per car per request does not scale."""
    from .cardb import ready_path
    return bool(car.db_address) and ready_path(car_db_path(car))


# ---------------------------------------------------------------------------
# Per-user capabilities + company-manager authorization
# ---------------------------------------------------------------------------
# Capabilities are stored per-user (see PortalUser). Roles only *seed* sensible
# defaults at creation; every flag stays individually editable afterwards.

def legacy_role_for_rank(rank):
    """Nearest legacy fixed-ladder id for a custom rank (compat shim: the
    ``PortalUser.role`` charfield keeps working for old admin flows)."""
    if rank <= 1:
        return 'after_sales_manager'
    if rank == 2:
        return 'after_sales_head'
    if rank == 3:
        return 'after_sales_supervisor'
    return 'after_sales_specialist'


def default_capabilities_for_role(role):
    """Seed capability defaults for a freshly created employee of ``role``.

    Manager (level 1) and Head (level 2) get team-management + analytics by
    default; everyone gets the AI assistant on (still gated by package + the
    company toggle in user_ai_eligible). Fully overridable by the creator.
    """
    level = ROLE_LEVEL.get(normalize_role(role), 99)
    return {
        'can_manage_team': level <= 2,
        'can_view_analytics': level <= 3,
        'ai_assistant_enabled': True,
    }


def user_rank(u):
    """Position of ``u`` in the legacy fixed ladder (1 = top, smaller wins).

    Retained only for analytics ordering; the live structure is the org graph.
    """
    return ROLE_LEVEL.get(normalize_role(u.role), 99)


def user_manage_scope(u):
    """Legacy analytics-visibility breadth: 'subtree' for everyone now that the
    org graph — not a per-role scope — governs management."""
    return 'subtree'


def display_role_label(u, department_label=None):
    """Human label of ``u``'s legacy role."""
    if department_label is None:
        department_label = u.company.department_label if u.company_id else ''
    return role_label(u.role, department_label)


def manageable_user_ids(actor, include_self=False):
    """IDs of every user ``actor`` may see/manage in the team area.

    The org-graph canvas is the live structure, so the actor's reach is the set
    of seats below their own — see orggraph.graph_subtree_user_ids. Only when the
    actor has no seat (a company whose graph was never seeded) does this fall
    back to the legacy ``reports_to`` chain:
      * 'org'     — every company user whose rank is strictly larger
                    (the manager sees everyone; the head sees everyone except
                    the manager; a supervisor sees the specialists — exactly
                    the pyramid, independent of explicit reporting lines);
      * 'subtree' — only the actor's transitive reports;
      * 'none'    — nobody.
    """
    from .models import PortalUser  # lazy: models imports this module
    from .orggraph import graph_subtree_user_ids  # lazy: imports models
    graph_ids = graph_subtree_user_ids(actor, include_self=include_self)
    if graph_ids is not None:
        return graph_ids
    scope = user_manage_scope(actor)
    if scope == 'none':
        ids = set()
    elif scope == 'subtree':
        ids = subtree_user_ids(actor)
    else:
        my_rank = user_rank(actor)
        ids = {
            u.id for u in (PortalUser.objects
                           .filter(company_id=actor.company_id))
            if u.id != actor.id and user_rank(u) > my_rank
        }
    if include_self:
        ids.add(actor.id)
    return ids


def subtree_user_ids(manager, include_self=False):
    """IDs of everyone reporting (transitively) to ``manager``.

    Walks the explicit ``reports_to`` chain within the manager's company. Cycle
    safe. Used to scope every team read/write to the manager's own org subtree.
    """
    from .models import PortalUser  # lazy: models imports this module
    ids = set()
    frontier = [manager.id]
    company_reports = list(
        PortalUser.objects.filter(company_id=manager.company_id)
        .values_list('id', 'reports_to_id')
    )
    children = {}
    for uid, parent in company_reports:
        children.setdefault(parent, []).append(uid)
    while frontier:
        cur = frontier.pop()
        for child in children.get(cur, []):
            if child not in ids:
                ids.add(child)
                frontier.append(child)
    if include_self:
        ids.add(manager.id)
    return ids


def find_valid_supervisor(start, child_rank, company_id, exclude_ids=()):
    """Nearest user at/above ``start`` in the reporting chain who strictly
    outranks ``child_rank`` (may supervise a member of that rank).

    Walks the explicit ``reports_to`` chain upward, cycle-safe. Returns None
    when the chain holds nobody suitable.
    """
    seen = set()
    cur = start
    while cur is not None and cur.id not in seen:
        seen.add(cur.id)
        if (cur.company_id == company_id and cur.id not in exclude_ids
                and cur.active and user_rank(cur) < child_rank):
            return cur
        cur = cur.reports_to
    return None


def enforce_org_consistency(company_id):
    """Repair every reporting edge that no longer points strictly upward.

    The org-chart invariant is: a user's supervisor must hold a strictly
    higher position (smaller rank number). Position changes, re-ranking and
    role deletion can all invalidate existing edges; this pass re-parents each
    violating user to the nearest valid ancestor (walking their old chain
    upward), falling back to the company's top-ranked active user. Returns the
    number of users re-parented.
    """
    from .models import PortalUser  # lazy: models imports this module
    users = list(PortalUser.objects.filter(company_id=company_id)
                 .select_related('reports_to'))
    by_id = {u.id: u for u in users}
    top = min((u for u in users if u.active), key=user_rank, default=None)
    fixed = 0
    for u in users:
        parent = by_id.get(u.reports_to_id)
        if parent is None:
            continue
        my_rank = user_rank(u)
        if user_rank(parent) < my_rank and parent.id != u.id:
            continue
        new_parent = find_valid_supervisor(
            parent, my_rank, company_id, exclude_ids={u.id})
        if new_parent is None and top is not None and top.id != u.id \
                and user_rank(top) < my_rank:
            new_parent = top
        if new_parent is not None and new_parent.id == u.reports_to_id:
            continue
        u.reports_to = new_parent
        u.save(update_fields=['reports_to'])
        fixed += 1
    return fixed


def manager_can_target(actor, target):
    """True iff ``actor`` (a manager) may view/manage ``target``.

    Same company, and target sits below the actor on the org-graph canvas.
    Sitting below IS the authority: the canvas is the live structure, so the
    legacy role ladder must not veto it (every seat the root creates is a
    'specialist' by default, and a rank comparison would make each of them
    unmanageable). The rank check survives only on the legacy path, for an
    actor with no seat. This is the authorization spine for every team write.
    """
    if not actor or not target or not getattr(actor, 'can_manage_team', False):
        return False
    if actor.id == target.id:
        return False
    if actor.company_id != target.company_id:
        return False
    from .orggraph import graph_subtree_user_ids  # lazy: imports models
    graph_ids = graph_subtree_user_ids(actor)
    if graph_ids is not None:
        return target.id in graph_ids
    if user_rank(actor) >= user_rank(target):
        return False
    return target.id in manageable_user_ids(actor)


def apply_user_access(user, accesses, override_purchase=False, allow_admin_grants=False):
    """Replace ``user``'s per-car grants from a list of {car_id, documents[], admin_granted?}.

    Single source of truth (used by both the platform-admin panel and the
    company-manager team API). Purchase-based grants are clamped to the
    company's purchased scope; admin-granted / override entries bypass that
    limit but ONLY when the caller is allowed to (``allow_admin_grants`` — the
    platform admin). Company managers can never exceed the company's purchase.
    """
    from django.db import transaction
    from .models import Car, UserCarAccess  # lazy
    if not isinstance(accesses, list):
        raise ValueError('accesses must be a list')
    company_scope = {
        a.car_id: (set(a.documents) if a.documents else set(VALID_DOCS))
        for a in user.company.car_accesses.all()
    }
    # One row per car: dedupe by car_id (last write wins) so a duplicated car_id
    # in the payload can't hit the (user, car) unique constraint mid-loop and
    # leave the grants half-rewritten. The whole replace is atomic for the same
    # reason — any failure rolls back to the pre-request grants.
    seen = set()
    with transaction.atomic():
        user.car_accesses.all().delete()
        for a in accesses:
            car_id = a.get('car_id')
            if car_id in seen:
                continue
            if not Car.objects.filter(id=car_id).exists():
                continue
            wants_admin = allow_admin_grants and (bool(a.get('admin_granted')) or override_purchase)
            if wants_admin:
                docs = [d for d in (a.get('documents') or []) if d in VALID_DOCS]
                UserCarAccess.objects.create(user=user, car_id=car_id, documents=docs, admin_granted=True)
                seen.add(car_id)
                continue
            if car_id not in company_scope:
                continue
            docs = [d for d in (a.get('documents') or []) if d in company_scope[car_id]]
            UserCarAccess.objects.create(user=user, car_id=car_id, documents=docs)
            seen.add(car_id)


# ---------------------------------------------------------------------------
# Content-category taxonomy (analytics dimension)
# ---------------------------------------------------------------------------
# Each per-car manual is a tree; the depth-2 nodes are the technical areas
# ("Engine Mechanical", "Body & Frame", "Electrical", ...). We map those raw
# English section titles onto a small set of canonical, bilingual categories
# so usage can be reported by area (engine / body / electrical / ...).

CONTENT_CATEGORIES = [
    ('engine',      {'fa': 'موتور',                 'en': 'Engine',
                     'aliases': ['engine mechanical', 'engine performance', 'engine']}),
    ('transmission', {'fa': 'گیربکس و انتقال قدرت', 'en': 'Transmission & Driveline',
                     'aliases': ['transmission', 'drivelines & axles', 'drivelines and axles', 'driveline']}),
    ('brakes',      {'fa': 'ترمز',                  'en': 'Brakes',
                     'aliases': ['brakes', 'brake']}),
    ('steering',    {'fa': 'فرمان',                 'en': 'Steering',
                     'aliases': ['steering']}),
    ('suspension',  {'fa': 'سیستم تعلیق',           'en': 'Suspension',
                     'aliases': ['suspension']}),
    ('electrical',  {'fa': 'برق و الکترونیک',       'en': 'Electrical',
                     'aliases': ['electrical', 'wiring diagrams', 'wiring']}),
    ('hvac',        {'fa': 'تهویه و کولر (HVAC)',   'en': 'HVAC',
                     'aliases': ['heating, ventilation & a/c (hvac)', 'hvac', 'heating',
                                 'heating, ventilation & a/c', 'air conditioning']}),
    ('body',        {'fa': 'بدنه و شاسی',           'en': 'Body & Frame',
                     'aliases': ['body & frame', 'body and frame', 'body', 'restraints']}),
    ('accessories', {'fa': 'تجهیزات و آپشن',        'en': 'Accessories & Equipment',
                     'aliases': ['accessories & equipment', 'accessories and equipment', 'accessories']}),
    ('maintenance', {'fa': 'سرویس و نگهداری',       'en': 'Maintenance',
                     'aliases': ['maintenance', 'quick lookups', 'general information']}),
    ('other',       {'fa': 'سایر',                  'en': 'Other',
                     'aliases': ['external pages']}),
]

CATEGORY_MAP = dict(CONTENT_CATEGORIES)
VALID_CATEGORIES = {c for c, _ in CONTENT_CATEGORIES}

# Reverse lookup: normalized raw title -> canonical id.
_CATEGORY_ALIAS = {}
for _cid, _meta in CONTENT_CATEGORIES:
    _CATEGORY_ALIAS[_cid] = _cid
    for _al in _meta['aliases']:
        _CATEGORY_ALIAS[_al] = _cid


def category_label(cid, lang='fa'):
    meta = CATEGORY_MAP.get(cid)
    return meta[lang] if meta else cid


def _normalize_title(s):
    return (str(s or '')).strip().lower()


def resolve_category(segments_or_path):
    """Map a browse path / node path onto a canonical category id.

    Accepts a list of path segments (e.g. ['Repair and Diagnosis',
    'Engine Mechanical', ...]) or a '/'-joined string. The technical area is the
    segment right under the "Repair and Diagnosis" root; we scan segments and
    return the first that matches a known alias. Returns 'other' if nothing
    matches, '' if there is nothing to classify.
    """
    if not segments_or_path:
        return ''
    if isinstance(segments_or_path, str):
        segments = [s for s in segments_or_path.split('/') if s]
    else:
        segments = [s for s in segments_or_path if s]
    for seg in segments:
        cid = _CATEGORY_ALIAS.get(_normalize_title(seg))
        if cid:
            return cid
    # Substring fallback (titles like "Engine Mechanical > ...").
    for seg in segments:
        norm = _normalize_title(seg)
        for alias, cid in _CATEGORY_ALIAS.items():
            if alias and alias in norm:
                return cid
    return 'other'
