"""Org-graph resolver: compile a seat's root-assigned permissions down into the
existing enforcement primitives, plus break-glass root reassignment and initial
seeding from the legacy OrgRole world.

The canvas (OrgGraph / OrgNode / NodePermission) is only an AUTHORING surface.
Content / RAG / chat gating still reads UserCarAccess + PortalUser flags. This
module is the one-way bridge: whenever a node's permission or occupant changes,
``sync_node_to_user`` rewrites the occupant's enforcement state to match.
"""

from django.db import transaction

from .access import apply_user_access
from .models import NodePermission, OrgGraph, OrgNode, PortalUser


# Admin-panel keys the root may grant to a seat. Kept in sync with the admin
# hubs surfaced in the frontend; enforcement reads ``user_admin_panels``.
ADMIN_PANEL_KEYS = [
    ('metrics', 'متریک‌ها و ترافیک'),
    ('data_quality', 'کیفیت داده'),
    ('ingest', 'ورود داده و پردازش'),
    ('terminology', 'اصطلاح‌نامه'),
    ('reports', 'گزارش‌های تیم'),
]
VALID_ADMIN_PANELS = {k for k, _ in ADMIN_PANEL_KEYS}


def _permission_for(node):
    perm, _ = NodePermission.objects.get_or_create(node=node)
    return perm


# ---------------------------------------------------------------------------
# Resolver: NodePermission -> enforcement primitives
# ---------------------------------------------------------------------------

def sync_node_to_user(node):
    """Rewrite the occupant's enforcement state from the node's permission.

    Root is the company super-admin, so car grants are applied as admin grants
    (``override_purchase``) — they are not capped by the company's purchase.
    An empty/occupant-less node is a no-op. The root node's own occupant is
    always fully AI-eligible and holds every admin panel implicitly.
    """
    user = node.occupant
    if user is None:
        return
    perm = _permission_for(node)

    if node.is_root:
        # The super-admin: everything on, panels handled by ``user_admin_panels``.
        ai_eligible = True
        accesses = perm.car_access or []
    else:
        ai_eligible = bool(perm.ai_eligible)
        accesses = perm.car_access or []

    # A seat can never exceed what the company bought: purchase grants are
    # clamped to the company scope by apply_user_access. The only exception is
    # a grant the PLATFORM admin already gave this user (admin_granted row
    # outside the scope), which a /team save must preserve but may not widen.
    scope_ids = set(user.company.car_accesses.values_list('car_id', flat=True))
    held_admin = {a.car_id: set(a.documents or [])
                  for a in user.car_accesses.filter(admin_granted=True)
                  if a.car_id not in scope_ids}
    rows = []
    for a in accesses:
        cid = a.get('car_id')
        if cid in held_admin:
            rows.append({'car_id': cid, 'admin_granted': True,
                         'documents': [d for d in (a.get('documents') or []) if d in held_admin[cid]]})
        else:
            rows.append({'car_id': cid, 'documents': a.get('documents') or []})

    with transaction.atomic():
        apply_user_access(user, rows, override_purchase=False, allow_admin_grants=True)
        if user.ai_assistant_enabled != ai_eligible:
            user.ai_assistant_enabled = ai_eligible
            user.save(update_fields=['ai_assistant_enabled'])


def sync_user_to_node(user):
    """Mirror a user's CURRENT enforcement state back onto their seat.

    The reverse of ``sync_node_to_user``. The platform admin edits a user's
    grants directly (portal.admin_user_access_view -> UserCarAccess), which would
    otherwise leave the seat's NodePermission stale: /admin and /team would
    disagree, and the next node-side save would silently revert the admin. Call
    this after any admin-side access/AI edit so both views stay identical in both
    directions. No-op for a user without a seat.
    """
    node = getattr(user, 'seat', None)
    if node is None:
        return
    perm, _ = NodePermission.objects.get_or_create(node=node)
    perm.car_access = [
        {'car_id': a.car_id, 'documents': list(a.documents or [])}
        for a in user.car_accesses.all()
    ]
    perm.ai_eligible = bool(user.ai_assistant_enabled)
    perm.save(update_fields=['car_access', 'ai_eligible', 'updated_at'])


def user_admin_panels(user):
    """Set of admin-panel keys ``user`` may open, from their seat's permission.

    The root occupant implicitly holds every panel. A user with no seat (or an
    empty permission) holds none.
    """
    node = getattr(user, 'seat', None)
    if node is None:
        return set()
    if node.is_root:
        return set(VALID_ADMIN_PANELS)
    perm = getattr(node, 'permission', None)
    if perm is None:
        return set()
    return {p for p in (perm.admin_panels or []) if p in VALID_ADMIN_PANELS}


def is_graph_root(user):
    """True iff ``user`` occupies the root node — the only editor of the graph."""
    node = getattr(user, 'seat', None)
    return bool(node and node.is_root)


# ---------------------------------------------------------------------------
# Reach: who sits below a seat on the canvas
# ---------------------------------------------------------------------------

def graph_subtree_user_ids(user, include_self=False):
    """Occupant ids of every seat below ``user``'s seat on the canvas.

    The canvas is the live org structure, so this — not the legacy ``reports_to``
    chain — is what team management and analytics scope to. Empty seats are
    transparent: an occupied seat under an empty one still resolves as reporting
    upward, so an unfilled middle seat never hides a whole branch.

    Returns None when ``user`` has no seat at all, which is the caller's signal
    to fall back to the legacy chain (companies whose graph was never seeded).
    Cycle-safe: the API rejects cycles, but a stale row must not hang a request.
    """
    from .models import OrgNode  # lazy: models imports this module
    seat = getattr(user, 'seat', None)
    if seat is None:
        return None
    children = {}
    occupant = {}
    for nid, pid, oid in (OrgNode.objects.filter(graph_id=seat.graph_id)
                          .values_list('id', 'parent_id', 'occupant_id')):
        children.setdefault(pid, []).append(nid)
        occupant[nid] = oid
    ids = set()
    frontier = [seat.id]
    seen = {seat.id}
    while frontier:
        for child in children.get(frontier.pop(), []):
            if child in seen:
                continue
            seen.add(child)
            frontier.append(child)
            if occupant.get(child):
                ids.add(occupant[child])
    ids.discard(user.id)
    if include_self:
        ids.add(user.id)
    return ids


def seat_has_children(user):
    """True iff the user's seat has at least one child seat on the canvas
    (occupied or empty). A seat with no children is a *leaf*. A user with no
    seat at all is treated as a leaf (no team below them)."""
    from .models import OrgNode  # lazy: models imports this module
    seat = getattr(user, 'seat', None)
    if seat is None:
        return False
    return OrgNode.objects.filter(parent_id=seat.id).exists()


def user_can_view_team(user):
    """Who may open the /team page. Everyone EXCEPT a leaf on the org graph:
    the root (which always has the org below it) and any node that has children
    qualify; a leaf seat — or a seatless user — does not. Root is allowed even
    on a brand-new graph with no children yet, so it can build the team."""
    return bool(is_graph_root(user) or seat_has_children(user))


def sync_reports_to_from_graph(company):
    """Mirror the canvas's parent edges onto the legacy ``reports_to`` field.

    ``reports_to`` still feeds analytics ordering and enforce_org_consistency, so
    it has to track the canvas rather than drift from it. A user's supervisor is
    the occupant of the nearest ANCESTOR seat that has one (empty seats are
    skipped). Occupants of the root — and of any branch with no occupied ancestor
    — get ``reports_to = None``. Returns how many rows changed.
    """
    from .models import PortalUser  # lazy: models imports this module
    graph = OrgGraph.objects.filter(company=company).first()
    if graph is None:
        return 0
    nodes = {}
    for nid, pid, oid in (OrgNode.objects.filter(graph=graph)
                          .values_list('id', 'parent_id', 'occupant_id')):
        nodes[nid] = (pid, oid)
    wanted = {}
    for nid, (pid, oid) in nodes.items():
        if not oid:
            continue
        supervisor = None
        seen = {nid}
        while pid is not None and pid not in seen:
            seen.add(pid)
            parent = nodes.get(pid)
            if parent is None:
                break
            if parent[1] and parent[1] != oid:
                supervisor = parent[1]
                break
            pid = parent[0]
        wanted[oid] = supervisor
    current = dict(PortalUser.objects.filter(id__in=wanted)
                   .values_list('id', 'reports_to_id'))
    changed = 0
    for uid, supervisor in wanted.items():
        if current.get(uid, ...) != supervisor:
            PortalUser.objects.filter(id=uid).update(reports_to=supervisor)
            changed += 1
    return changed


# ---------------------------------------------------------------------------
# Break-glass: reassign the root seat (server-side super-admin only)
# ---------------------------------------------------------------------------

def reassign_root(company, new_occupant):
    """Move the company's root seat onto ``new_occupant`` (a PortalUser in the
    same company). Used by the platform super-admin when the current root is
    locked out. Idempotent; re-syncs both affected occupants.
    """
    if new_occupant.company_id != company.id:
        raise ValueError('occupant must belong to the company')
    graph = OrgGraph.objects.filter(company=company).first()
    if graph is None:
        graph = seed_graph_for_company(company)
    root = graph.root_node
    with transaction.atomic():
        # If the new occupant already sits elsewhere, vacate that seat first
        # (one seat per person).
        prior_seat = OrgNode.objects.filter(occupant=new_occupant).exclude(
            pk=getattr(root, 'pk', None)).first()
        if prior_seat is not None:
            prior_seat.occupant = None
            prior_seat.save(update_fields=['occupant'])
        old_root_user = root.occupant if root else None
        if root is None:
            root = OrgNode.objects.create(graph=graph, is_root=True, label='مدیر ارشد')
        root.occupant = new_occupant
        root.save(update_fields=['occupant'])
        sync_node_to_user(root)
        if old_root_user and old_root_user.id != new_occupant.id:
            # Demoted user keeps their account but loses root powers; their
            # access now flows from whatever seat they occupy (none by default).
            old_root_user.ai_assistant_enabled = False
            old_root_user.save(update_fields=['ai_assistant_enabled'])
        sync_reports_to_from_graph(company)
    return root


def add_root_on_top(company, new_user):
    """Transfer 0-level ownership to ``new_user`` without touching the chart:
    the current root seat (occupant, subtree, permissions) becomes an ordinary
    seat under a NEW root seat for ``new_user``. The company access window
    (the root occupant's expiry) carries over to the new root."""
    if new_user.company_id != company.id:
        raise ValueError('occupant must belong to the company')
    graph = OrgGraph.objects.filter(company=company).first()
    old_root = graph.root_node if graph else None
    if old_root is None:
        return reassign_root(company, new_user)
    old_user = old_root.occupant
    with transaction.atomic():
        old_root.is_root = False        # one_root_per_graph: demote first
        old_root.save(update_fields=['is_root'])
        root = OrgNode.objects.create(
            graph=graph, is_root=True, label='مدیر ارشد', occupant=new_user,
            canvas_x=old_root.canvas_x, canvas_y=old_root.canvas_y - 180)
        NodePermission.objects.create(
            node=root, car_access=company_scope_access(company),
            ai_eligible=True, admin_panels=list(VALID_ADMIN_PANELS))
        old_root.parent = root
        old_root.save(update_fields=['parent'])
        if old_user is not None:
            new_user.access_expires_at = old_user.access_expires_at
            new_user.save(update_fields=['access_expires_at'])
        sync_node_to_user(root)
        sync_node_to_user(old_root)
        sync_reports_to_from_graph(company)
    return root


# ---------------------------------------------------------------------------
# Seeding: build a graph from the current company/user state
# ---------------------------------------------------------------------------

def _pick_root_user(company):
    """Best guess for the company's top person: a can_manage_team user, else
    the earliest-created active user."""
    qs = company.users.filter(active=True)
    top = qs.filter(can_manage_team=True).order_by('created_at', 'id').first()
    return top or qs.order_by('created_at', 'id').first()


def seed_graph_for_company(company):
    """Create the org graph for a company if missing: one root seat (the top
    user) plus a flat seat for every other active user, each seat's permission
    mirroring that user's CURRENT effective access so nothing changes on cutover.
    """
    graph, created = OrgGraph.objects.get_or_create(company=company)
    if graph.nodes.exists():
        return graph

    root_user = _pick_root_user(company)
    with transaction.atomic():
        root = OrgNode.objects.create(
            graph=graph, is_root=True, label='مدیر ارشد',
            occupant=root_user, canvas_x=0, canvas_y=0)
        NodePermission.objects.create(
            node=root, car_access=_current_access(root_user),
            ai_eligible=True, admin_panels=list(VALID_ADMIN_PANELS))
        i = 0
        for u in company.users.filter(active=True).order_by('created_at', 'id'):
            if root_user and u.id == root_user.id:
                continue
            i += 1
            node = OrgNode.objects.create(
                graph=graph, parent=root, label=u.display_name or u.username,
                occupant=u, canvas_x=(i % 6) * 220 - 550, canvas_y=180 + (i // 6) * 140)
            NodePermission.objects.create(
                node=node, car_access=_current_access(u),
                ai_eligible=bool(u.ai_assistant_enabled), admin_panels=[])
        sync_reports_to_from_graph(company)
    return graph


def company_scope_access(company):
    """The company's purchased scope as NodePermission.car_access rows."""
    return [
        {'car_id': a.car_id, 'documents': list(a.documents or [])}
        for a in company.car_accesses.all()
    ]


def grant_root_company_scope(company):
    """The root (the buyer) holds everything the company bought: every car in
    the company scope, AI on. Run after the root is seated and after every
    company-scope save, so the root is never left with an empty fleet."""
    graph = OrgGraph.objects.filter(company=company).first()
    root = graph.root_node if graph else None
    if root is None or root.occupant_id is None:
        return
    perm = _permission_for(root)
    perm.car_access = company_scope_access(company)
    perm.ai_eligible = True
    perm.save(update_fields=['car_access', 'ai_eligible', 'updated_at'])
    sync_node_to_user(root)


def _role_title(user):
    from .access import display_role_label
    return display_role_label(user)[:120] or user.display_name or user.username


def seat_new_user(company, user, ai_eligible):
    """Give an admin-created employee a seat under the root, holding the
    company's full scope, so /team shows them and they can actually use what
    the company bought. No-op when the company has no graph/root yet."""
    graph = OrgGraph.objects.filter(company=company).first()
    root = graph.root_node if graph else None
    if root is None or getattr(user, 'seat', None) is not None:
        return
    n = graph.nodes.filter(is_root=False).count() + 1
    with transaction.atomic():
        node = OrgNode.objects.create(
            graph=graph, parent=root, label=_role_title(user),
            occupant=user, canvas_x=(n % 6) * 220 - 550, canvas_y=180 + (n // 6) * 140)
        NodePermission.objects.create(
            node=node, car_access=company_scope_access(company),
            ai_eligible=bool(ai_eligible), admin_panels=[])
        sync_node_to_user(node)
        sync_reports_to_from_graph(company)


def _current_access(user):
    """Snapshot a user's existing per-car grants as NodePermission.car_access."""
    if user is None:
        return []
    return [
        {'car_id': a.car_id, 'documents': list(a.documents or [])}
        for a in user.car_accesses.all()
    ]


def seed_all():
    """Seed graphs for every company. Returns the count created."""
    from .models import Company
    n = 0
    for c in Company.objects.all():
        g = OrgGraph.objects.filter(company=c).first()
        if g and g.nodes.exists():
            continue
        seed_graph_for_company(c)
        n += 1
    return n


# ---------------------------------------------------------------------------
# Seat title <-> PortalUser.role (one value, shown identically in /admin + /team)
# ---------------------------------------------------------------------------

def role_from_title(company, title):
    """The ``PortalUser.role`` value for a seat title: a built-in key when the
    title is exactly a built-in role's label, otherwise the title text itself
    (a custom role, same as a custom role typed in the admin picker)."""
    from .access import ROLE_CHOICES, role_label
    title = (title or '').strip()
    dept = company.department_label if company else ''
    for rid, _ in ROLE_CHOICES:
        if role_label(rid, dept) == title:
            return rid
    return title[:80]


def reconcile_seat_title(node):
    """Make the seat title and its occupant's role the same value.

    The seat title wins when it is a real title; an empty title, or one that is
    just the person's name (old seeding), is replaced by the role label."""
    from .access import display_role_label
    u = node.occupant
    if u is None:
        return
    label = (node.label or '').strip()
    if label and label not in ((u.display_name or '').strip(), u.username):
        role = role_from_title(u.company, label)
        if u.role != role:
            u.role = role
            u.save(update_fields=['role'])
    else:
        title = display_role_label(u)[:120]
        if node.label != title:
            node.label = title
            node.save(update_fields=['label'])


def sync_user_title_to_seat(user):
    """After an admin-side role edit: copy the role label onto the seat."""
    from .access import display_role_label
    node = getattr(user, 'seat', None)
    if node is None:
        return
    title = display_role_label(user)[:120]
    if node.label != title:
        node.label = title
        node.save(update_fields=['label'])
