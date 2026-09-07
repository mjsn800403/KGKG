"""Root-only CRUD for the org-graph canvas.

Every mutating endpoint is gated by ``require_root``: only the occupant of the
graph's root node (the company super-admin) may edit. Everyone else gets a
READ-ONLY view of the same graph (their own seat flagged). Reads are open to any
authenticated portal user in the company.
"""
import json
from functools import wraps

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .access import PACKAGE_CHOICES
from .models import Car, NodePermission, OrgGraph, OrgNode, PortalUser
from . import orggraph as og
from .portal import portal_user


def _body(request):
    try:
        return json.loads((request.body or b'{}').decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return {}


def _graph_for(user):
    graph, _ = OrgGraph.objects.get_or_create(company=user.company)
    if not graph.nodes.exists():
        og.seed_graph_for_company(user.company)
        graph.refresh_from_db()
    return graph


def require_authed(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        user = portal_user(request)
        if not user:
            return JsonResponse({'error': 'unauthorized'}, status=401)
        request.portal = user
        return view(request, *args, **kwargs)
    return wrapped


def require_root(view):
    """Only the root-seat occupant may proceed."""
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        user = portal_user(request)
        if not user:
            return JsonResponse({'error': 'unauthorized'}, status=401)
        if not og.is_graph_root(user):
            return JsonResponse(
                {'error': 'فقط مدیر ارشد (گره ریشه) می‌تواند ساختار را ویرایش کند.'},
                status=403)
        request.root_user = user
        return view(request, *args, **kwargs)
    return wrapped


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def _node_dict(node):
    perm = getattr(node, 'permission', None)
    occ = node.occupant
    return {
        'id': node.id,
        'parent_id': node.parent_id,
        'is_root': node.is_root,
        'label': node.label,
        'x': node.canvas_x,
        'y': node.canvas_y,
        'occupant': ({
            'id': occ.id,
            'username': occ.username,
            'display_name': occ.display_name,
            'email': occ.email,
            'invite_status': occ.invite_status,
        } if occ else None),
        'permission': {
            'car_access': (perm.car_access if perm else []),
            'ai_eligible': (perm.ai_eligible if perm else False),
        },
    }


def _graph_dict(graph, viewer):
    is_root = og.is_graph_root(viewer)
    my_node = getattr(viewer, 'seat', None)
    nodes = list(graph.nodes.select_related('occupant', 'permission').all())
    # EVERY active employee of the company is assignable, not just the unseated
    # ones: the root manages the whole organisation, so it can pull anyone into
    # any seat. Seating someone who already sits elsewhere MOVES them (the prior
    # seat is vacated — one seat per person). ``seated_in`` lets the UI say so.
    seat_of = {n.occupant_id: n for n in nodes if n.occupant_id}
    employees = graph.company.users.filter(active=True).order_by('display_name', 'username')

    # The car picker must cover EVERY car any node already holds, not just the
    # company's purchased ones: the platform admin can grant a company's users
    # cars beyond the purchase (admin_granted), and those show up in /admin. If
    # we offered only the purchased set, saving a node here would silently drop
    # the admin-granted extras — /admin and /team would disagree and access
    # would vanish. Purchased ∪ currently-held, labelled from the catalog.
    purchased = {a.car_id: (a.documents or []) for a in graph.company.car_accesses.all()}
    held = set()
    for n in nodes:
        perm = getattr(n, 'permission', None)
        for row in (perm.car_access if perm else []) or []:
            if row.get('car_id') is not None:
                held.add(row['car_id'])
    car_ids = set(purchased) | held
    catalog = {c.id: c for c in Car.objects.filter(id__in=car_ids)}
    seat_cap = graph.company.seats_count
    seats_used = sum(1 for n in nodes if not n.is_root)
    return {
        'can_edit': is_root,
        'my_node_id': (my_node.id if my_node else None),
        'seat_cap': seat_cap,
        'seats_used': seats_used,
        'nodes': [_node_dict(n) for n in nodes],
        'employees': [
            {'id': u.id, 'username': u.username, 'display_name': u.display_name,
             'email': u.email,
             'seated_node_id': (seat_of[u.id].id if u.id in seat_of else None),
             'seated_label': (seat_of[u.id].label if u.id in seat_of else '')}
            for u in employees],
        # brand/model/year are sent apart from the joined label so the shared
        # vehicle filter can facet on them (see components/VehicleFilter.jsx).
        'company_cars': sorted(
            ({'car_id': cid,
              'brand': catalog[cid].brand_name,
              'model': catalog[cid].car_name,
              'year': catalog[cid].year,
              'label': f'{catalog[cid].brand_name} {catalog[cid].car_name} '
                       f'{catalog[cid].year}'.strip(),
              'documents': list(purchased.get(cid) or []),
              'purchased': cid in purchased}
             for cid in car_ids if cid in catalog),
            key=lambda c: c['label']),
        'packages': [{'id': p, 'label': l} for p, l in PACKAGE_CHOICES],
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@csrf_exempt
@require_authed
def graph_view(request):
    """GET /api/org/graph/ — the whole graph document + pickers."""
    graph = _graph_for(request.portal)
    return JsonResponse(_graph_dict(graph, request.portal))


@csrf_exempt
@require_root
def nodes_view(request):
    """POST /api/org/nodes/ — create a seat. Body: {label?, parent_id?, x, y}."""
    if request.method != 'POST':
        return JsonResponse({'error': 'method'}, status=405)
    b = _body(request)
    graph = _graph_for(request.root_user)
    # Seat cap: the platform super-admin bounds how many seats a root may create
    # via Company.seats_count (the root's own node does not count). None = no cap.
    cap = graph.company.seats_count
    if cap is not None:
        used = graph.nodes.filter(is_root=False).count()
        if used >= cap:
            return JsonResponse(
                {'error': f'به سقف مجاز صندلی‌ها رسیده‌اید ({cap}).', 'code': 'seat_cap',
                 'cap': cap, 'used': used}, status=403)
    parent = None
    if b.get('parent_id'):
        parent = graph.nodes.filter(id=b['parent_id']).first()
        if parent is None:
            return JsonResponse({'error': 'parent not found'}, status=400)
    node = OrgNode.objects.create(
        graph=graph, parent=parent, is_root=False,
        label=(b.get('label') or '').strip()[:120],
        canvas_x=float(b.get('x') or 0), canvas_y=float(b.get('y') or 0))
    NodePermission.objects.create(node=node)
    graph.updated_by = request.root_user
    graph.save(update_fields=['updated_by', 'updated_at'])
    return JsonResponse(_node_dict(node), status=201)


@csrf_exempt
@require_root
def node_detail_view(request, node_id):
    """PATCH / DELETE /api/org/nodes/<id>/.

    PATCH body may carry any of: label, x, y, parent_id, occupant_id (assign an
    existing free employee; null to vacate). Structural + occupant edits only —
    permissions go through the permission endpoint.
    """
    graph = _graph_for(request.root_user)
    node = graph.nodes.select_related('occupant').filter(id=node_id).first()
    if node is None:
        return JsonResponse({'error': 'not found'}, status=404)

    if request.method == 'DELETE':
        if node.is_root:
            return JsonResponse({'error': 'گره ریشه حذف نمی‌شود.'}, status=400)
        # Edges are cosmetic: re-parent children up to this node's parent (or
        # the root) rather than cascading. Occupant is freed, not deleted.
        fallback = node.parent or graph.root_node
        node.children.update(parent=fallback)
        node.delete()
        # Re-parenting moved people under a new supervisor: mirror that onto the
        # legacy reporting field so team/analytics scoping matches the canvas.
        og.sync_reports_to_from_graph(graph.company)
        return JsonResponse({'ok': True})

    if request.method != 'PATCH':
        return JsonResponse({'error': 'method'}, status=405)

    b = _body(request)
    fields = []
    if 'label' in b:
        node.label = (b.get('label') or '').strip()[:120]
        fields.append('label')
    if 'x' in b:
        node.canvas_x = float(b.get('x') or 0)
        fields.append('canvas_x')
    if 'y' in b:
        node.canvas_y = float(b.get('y') or 0)
        fields.append('canvas_y')
    if 'parent_id' in b and not node.is_root:
        raw = b.get('parent_id')
        if raw is None:
            node.parent = None
        else:
            parent = graph.nodes.filter(id=raw).first()
            if parent is None:
                return JsonResponse({'error': 'parent not found'}, status=400)
            if _would_cycle(node, parent):
                return JsonResponse({'error': 'حلقه در ساختار مجاز نیست.'}, status=400)
            node.parent = parent
        fields.append('parent')

    occupant_changed = False
    if 'occupant_id' in b:
        raw = b.get('occupant_id')
        if raw is None:
            node.occupant = None
        else:
            u = graph.company.users.filter(id=raw, active=True).first()
            if u is None:
                return JsonResponse({'error': 'employee not found'}, status=400)
            # One seat per person: vacate any prior seat.
            OrgNode.objects.filter(occupant=u).exclude(id=node.id).update(occupant=None)
            node.occupant = u
        fields.append('occupant')
        occupant_changed = True

    if fields:
        node.save(update_fields=list(set(fields)))
    if occupant_changed:
        og.sync_node_to_user(node)
    if occupant_changed or 'parent' in fields:
        og.sync_reports_to_from_graph(graph.company)
    return JsonResponse(_node_dict(node))


def _would_cycle(node, new_parent):
    """True if making new_parent the parent of node introduces a cycle."""
    cur = new_parent
    seen = set()
    while cur is not None and cur.id not in seen:
        if cur.id == node.id:
            return True
        seen.add(cur.id)
        cur = cur.parent
    return False


@csrf_exempt
@require_root
def node_permission_view(request, node_id):
    """POST /api/org/nodes/<id>/permission/ — set the seat's permission set and
    re-sync the occupant. Body: {car_access[], ai_eligible, admin_panels[]}."""
    if request.method != 'POST':
        return JsonResponse({'error': 'method'}, status=405)
    graph = _graph_for(request.root_user)
    node = graph.nodes.filter(id=node_id).first()
    if node is None:
        return JsonResponse({'error': 'not found'}, status=404)
    b = _body(request)
    perm, _ = NodePermission.objects.get_or_create(node=node)

    if 'car_access' in b:
        ca = b.get('car_access') or []
        clean = []
        for row in ca if isinstance(ca, list) else []:
            cid = row.get('car_id')
            if cid is None:
                continue
            docs = [d for d in (row.get('documents') or []) if isinstance(d, str)]
            clean.append({'car_id': cid, 'documents': docs})
        perm.car_access = clean
    if 'ai_eligible' in b:
        perm.ai_eligible = bool(b.get('ai_eligible'))
    perm.save()
    og.sync_node_to_user(node)
    return JsonResponse(_node_dict(node))


@csrf_exempt
@require_root
def node_create_user_view(request, node_id):
    """POST /api/org/nodes/<id>/create-user/ — create a NEW employee directly
    into an empty seat. Body: {display_name, phone, username?, password?, email?}.

    Replaces the old email-invite flow: the root builds its own sub-organisation,
    so the account is created ACTIVE immediately and the credentials are handed
    back once for the root to pass on. An auto-generated password is returned
    when none is supplied.
    """
    from django.db import IntegrityError, transaction
    from .portal import _gen_password
    from .team import _unique_username

    if request.method != 'POST':
        return JsonResponse({'error': 'method'}, status=405)
    graph = _graph_for(request.root_user)
    node = graph.nodes.filter(id=node_id).first()
    if node is None:
        return JsonResponse({'error': 'not found'}, status=404)
    if node.occupant_id:
        return JsonResponse({'error': 'این صندلی اشغال شده است.'}, status=400)

    b = _body(request)
    display_name = (b.get('display_name') or '').strip()[:150]
    if not display_name:
        return JsonResponse({'error': 'نام کاربر لازم است.'}, status=400)
    # Every account logs in through the SMS second factor, so a seat created
    # without a number would be unusable from the moment it exists.
    phone = (b.get('phone') or '').strip()[:40]
    if not phone:
        return JsonResponse({'error': 'شماره موبایل کاربر لازم است (کد ورود پیامکی به آن ارسال می‌شود).'}, status=400)
    company = graph.company
    raw_username = (b.get('username') or '').strip()[:100]
    username = raw_username or _unique_username(
        (b.get('email') or display_name).split('@')[0] or 'user', company.id)
    password = (b.get('password') or '').strip() or _gen_password()
    email = (b.get('email') or '').strip().lower()[:254] or None

    try:
        with transaction.atomic():
            user = PortalUser(
                company=company, username=username, email=email,
                phone=phone,
                display_name=display_name, role='after_sales_specialist',
                invite_status='active', active=True)
            user.set_password(password)
            user.save()
            node.occupant = user
            node.save(update_fields=['occupant'])
            og.sync_node_to_user(node)
            og.sync_reports_to_from_graph(company)
    except IntegrityError:
        return JsonResponse(
            {'error': 'این نام کاربری یا ایمیل قبلاً استفاده شده است.'}, status=400)

    return JsonResponse({'ok': True, 'node': _node_dict(node),
                         'credentials': {'username': username, 'password': password}},
                        status=201)


# ---------------------------------------------------------------------------
# Break-glass: PlatformAdmin reassigns a company's root seat (server-side super
# admin only — the sole actor above a company's own root).
# ---------------------------------------------------------------------------

@csrf_exempt
def admin_reassign_root_view(request):
    """POST /api/admin/org/reassign-root/  {company_id, occupant_id|username}

    PlatformAdmin-gated. Moves the company's root seat onto the named PortalUser
    (same company). Used when the current root is locked out.
    """
    from .admin_auth import require_admin_token

    @require_admin_token
    def _inner(request):
        if request.method != 'POST':
            return JsonResponse({'error': 'method'}, status=405)
        b = _body(request)
        company_id = b.get('company_id')
        company = Company.objects.filter(id=company_id).first() if company_id else None
        if company is None:
            return JsonResponse({'error': 'company not found'}, status=404)
        q = PortalUser.objects.filter(company=company, active=True)
        if b.get('occupant_id'):
            user = q.filter(id=b['occupant_id']).first()
        elif b.get('username'):
            user = q.filter(username=b['username']).first()
        else:
            return JsonResponse({'error': 'occupant_id یا username لازم است.'}, status=400)
        if user is None:
            return JsonResponse({'error': 'کاربر یافت نشد.'}, status=404)
        root = og.reassign_root(company, user)
        return JsonResponse({'ok': True, 'root_node_id': root.id,
                             'occupant': {'id': user.id, 'username': user.username}})

    return _inner(request)


from .models import Company  # noqa: E402  (used by admin_reassign_root_view)
