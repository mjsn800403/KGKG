"""Company self-service team management + employee invites + team analytics.

Audience: a company **manager** (a PortalUser with ``can_manage_team``). Unlike
the platform-admin panel (portal.py, which sees everything), everything here is
scoped to the manager's own company AND their explicit ``reports_to`` subtree —
see access.manager_can_target / subtree_user_ids. Managers can never exceed the
company's purchased car/doc scope (access.apply_user_access clamps them).

Employees are provisioned by email invite: created with an unusable password +
``invite_status='invited'``; they set their own password via /api/invite/<token>/.
"""
import json
import os
import re

from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError
from django.db.models import Count, Max
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .models import (
    ActivityLog, AuthToken, Car, Company, InviteToken, OrgRole, PortalUser,
)
from .access import (
    CONTENT_CATEGORIES, PACKAGE_CHOICES, ROLE_CHOICES, ROLE_LEVEL, VALID_ROLES,
    apply_managed_access, category_label, default_capabilities_for_org_role,
    default_capabilities_for_role, display_role_label, legacy_role_for_rank,
    manageable_user_ids, manager_can_target, manager_grantable_cars,
    normalize_role, role_can_manage, role_label, subtree_user_ids,
    user_manage_scope, user_rank,
)
from .portal import _body, _car_dict, _gen_password, _user_dict
from .portal_auth import require_analytics, require_manager
from .ratelimit import rate_limited


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _frontend_base():
    """Public origin of the Next.js frontend (for building invite links)."""
    return (os.environ.get('KG_FRONTEND_BASE_URL')
            or getattr(settings, 'FRONTEND_BASE_URL', '')
            or 'http://103.75.197.155').rstrip('/')


def _invite_url(raw_token):
    return f'{_frontend_base()}/invite/{raw_token}'


def _unique_username(base, company_id):
    """Derive a stable, unique username from an email local-part / name."""
    base = re.sub(r'[^a-zA-Z0-9_.-]', '', (base or '').split('@')[0]).strip('._-').lower()
    if not base:
        base = f'user{company_id}'
    candidate = base
    i = 1
    while PortalUser.objects.filter(username__iexact=candidate).exists():
        i += 1
        candidate = f'{base}{i}'
    return candidate[:100]


def _send_invite_email(user, url):
    """Best-effort invite email. Returns True if actually sent.

    Off by default: only attempts delivery when KG_INVITE_EMAIL is truthy AND the
    user has an email. Until SMTP is configured the copyable invite link is the
    delivery channel, so we never block on a missing mail server.
    """
    if not user.email or not os.environ.get('KG_INVITE_EMAIL'):
        return False
    try:
        send_mail(
            subject='دعوت به سامانه مستندات فنی KGtechvault',
            message=(f'{user.display_name or user.username} گرامی،\n\n'
                     f'برای فعال‌سازی حساب کاربری خود و تعیین رمز عبور روی لینک زیر کلیک کنید:\n{url}\n\n'
                     'این لینک تا ۷ روز معتبر است.'),
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
            recipient_list=[user.email],
            fail_silently=True,
        )
        return True
    except Exception:
        return False


def _role_dict(role, my_rank=None):
    """Serialize an OrgRole for the team UI."""
    d = {
        'id': role.id, 'name': role.name, 'rank': role.rank,
        'manage_scope': role.manage_scope,
        'can_manage_team': role.can_manage_team,
        'can_view_analytics': role.can_view_analytics,
        'ai_assistant_enabled': role.ai_assistant_enabled,
        'color': role.color,
        'default_accesses': role.default_accesses or [],
        'members_count': role.members.count(),
    }
    if my_rank is not None:
        # A viewer may assign/edit only positions strictly below their own.
        d['editable'] = role.rank > my_rank
    return d


def _company_roles(manager):
    return list(OrgRole.objects.filter(company_id=manager.company_id)
                .order_by('rank', 'id'))


def _sync_legacy_role(user):
    """Keep the legacy ``role`` charfield roughly in step with the org position
    so old admin flows / labels keep working for unmapped code paths."""
    if user.org_role_id and user.org_role:
        user.role = legacy_role_for_rank(user.org_role.rank)


def _meta_payload(manager):
    """Form options for the team UI: assignable positions, managers, cars, ..."""
    my_rank = user_rank(manager)
    dept = manager.company.department_label
    roles = [_role_dict(r, my_rank) for r in _company_roles(manager)]
    # Who a report can report to: the manager + anyone they can manage.
    vis_ids = manageable_user_ids(manager, include_self=True)
    managers = [
        {'id': u.id, 'name': u.display_name or u.username,
         'role_label': display_role_label(u, dept), 'rank': user_rank(u)}
        for u in PortalUser.objects.filter(id__in=vis_ids)
                                   .select_related('org_role')
                                   .order_by('display_name', 'username')
    ]
    # Cars the manager may delegate = every car the manager themselves can
    # access (company purchase + anything admin-granted to them), each capped at
    # the manager's own document layers. "Give what you can access."
    grantable = manager_grantable_cars(manager)
    cars = [
        {**_car_dict(car), 'documents': sorted(grantable[car.id])}
        for car in Car.objects.filter(id__in=grantable.keys())
                              .order_by('brand_name', 'car_name', 'year')
    ]
    return {
        'roles': roles,
        'managers': managers,
        'cars': cars,
        'packages': [{'id': p, 'label': l} for p, l in PACKAGE_CHOICES],
        'department_label': dept,
        'my_rank': my_rank,
        'my_role_id': manager.org_role_id,
        'my_scope': user_manage_scope(manager),
        'company': {'id': manager.company_id, 'name': manager.company.name,
                    'ai_assistant_enabled': manager.company.ai_assistant_enabled},
    }


def _members_qs(manager):
    ids = manageable_user_ids(manager)
    return (PortalUser.objects.filter(id__in=ids)
            .select_related('company', 'reports_to', 'org_role')
            .order_by('display_name', 'username'))


def _resolve_new_role(manager, body):
    """Position for a created/updated member from the request body.

    Accepts ``org_role_id`` (the company-defined position — preferred) or the
    legacy ``role`` id (mapped onto the seeded position of the same rank).
    Returns (org_role, error_response|None). The position must sit strictly
    below the acting manager.
    """
    my_rank = user_rank(manager)
    role_id = body.get('org_role_id')
    if role_id:
        role = OrgRole.objects.filter(id=role_id, company_id=manager.company_id).first()
        if role is None:
            return None, JsonResponse({'error': 'نقش انتخابی یافت نشد.'}, status=400)
        if role.rank <= my_rank:
            return None, JsonResponse(
                {'error': 'نمی‌توانید کاربری هم‌سطح یا بالاتر از خودتان ایجاد کنید.'}, status=403)
        return role, None
    legacy = normalize_role(body.get('role'))
    if legacy in VALID_ROLES:
        want_rank = ROLE_LEVEL.get(legacy, 99)
        if want_rank <= my_rank:
            return None, JsonResponse(
                {'error': 'نمی‌توانید کاربری هم‌سطح یا بالاتر از خودتان ایجاد کنید.'}, status=403)
        role = (OrgRole.objects.filter(company_id=manager.company_id, rank=want_rank)
                .order_by('id').first())
        if role is not None:
            return role, None
        return None, None  # legacy-only company: fall back to charfield role
    return None, JsonResponse({'error': 'نقش سازمانی نامعتبر است.'}, status=400)


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------

@csrf_exempt
@require_manager
def team_members_view(request):
    """GET  /api/team/members/  -> {members, meta}
    POST /api/team/members/  {display_name, email, role, reports_to_id?, phone?,
                              personnel_code?, can_manage_team?, can_view_analytics?,
                              ai_assistant_enabled?, accesses?} -> create + invite
    """
    manager = request.manager

    if request.method == 'GET':
        members = [_user_dict(u, with_access=True) for u in _members_qs(manager)]
        return JsonResponse({'members': members, 'meta': _meta_payload(manager)})

    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)

    b = _body(request)
    display_name = (str(b.get('display_name') or '')).strip()[:150]
    email = (str(b.get('email') or '')).strip().lower()[:254]
    # Provisioning mode: 'invite' (email invite, employee sets own password) or
    # 'credentials' (manager creates a username + password on the spot — for
    # employees without an email). Defaults sensibly from whether an email exists.
    provision = (str(b.get('provision') or '')).strip().lower()
    if provision not in ('invite', 'credentials'):
        provision = 'invite' if email else 'credentials'

    if not display_name:
        return JsonResponse({'error': 'نام و نام خانوادگی الزامی است.'}, status=400)
    org_role, role_err = _resolve_new_role(manager, b)
    if role_err is not None:
        return role_err
    role = (legacy_role_for_rank(org_role.rank) if org_role
            else normalize_role(b.get('role')))
    if provision == 'invite' and not email:
        return JsonResponse({'error': 'ایمیل برای ارسال دعوت‌نامه الزامی است.'}, status=400)
    if email and PortalUser.objects.filter(email__iexact=email).exists():
        return JsonResponse({'error': 'کاربری با این ایمیل قبلاً ثبت شده است.'}, status=400)

    # Username: manager may set one (credentials mode), else derive uniquely.
    username_in = (str(b.get('username') or '')).strip()[:100]
    if username_in:
        if PortalUser.objects.filter(username__iexact=username_in).exists():
            return JsonResponse({'error': 'این نام کاربری قبلاً استفاده شده است.'}, status=400)
        username = username_in
    else:
        username = _unique_username(email or display_name, manager.company_id)

    # Credentials-mode password: manager-supplied (>=8) or auto-generated.
    password = None
    if provision == 'credentials':
        pw_in = (str(b.get('password') or '')).strip()
        if pw_in and len(pw_in) < 8:
            return JsonResponse({'error': 'رمز عبور باید حداقل ۸ نویسه باشد.'}, status=400)
        password = pw_in or _gen_password()

    # reports_to defaults to the creating manager; if given, must be visible to them.
    reports_to = manager
    if b.get('reports_to_id'):
        rid = b['reports_to_id']
        if rid not in manageable_user_ids(manager, include_self=True):
            return JsonResponse({'error': 'سرپرست انتخابی معتبر نیست.'}, status=400)
        reports_to = PortalUser.objects.filter(id=rid).first() or manager

    caps = (default_capabilities_for_org_role(org_role) if org_role
            else default_capabilities_for_role(role))
    for k in ('can_manage_team', 'can_view_analytics', 'ai_assistant_enabled'):
        if k in b:
            caps[k] = bool(b[k])

    u = PortalUser(
        company=manager.company,
        username=username,
        email=email or None,
        display_name=display_name,
        phone=(str(b.get('phone') or '')).strip()[:40],
        personnel_code=(str(b.get('personnel_code') or '')).strip()[:60],
        role=role,
        org_role=org_role,
        reports_to=reports_to,
        invited_by=manager,
        can_manage_team=caps['can_manage_team'],
        can_view_analytics=caps['can_view_analytics'],
        ai_assistant_enabled=caps['ai_assistant_enabled'],
        invite_status='active' if provision == 'credentials' else 'invited',
    )
    if provision == 'credentials':
        u.set_password(password)   # active immediately, no invite needed
    else:
        u.set_unusable_password()
    try:
        u.save()
    except IntegrityError:
        return JsonResponse({'error': 'این ایمیل یا نام کاربری قبلاً استفاده شده است.'}, status=400)

    # Initial car/doc grants: explicit list wins; otherwise the position's
    # access template applies. Both are clamped to what the manager may delegate.
    accesses = b.get('accesses')
    if not isinstance(accesses, list) and org_role and org_role.default_accesses:
        accesses = org_role.default_accesses
    if isinstance(accesses, list):
        try:
            apply_managed_access(manager, u, accesses)
        except ValueError:
            pass

    ActivityLog.objects.create(user=manager, action='team_add',
                               detail=f'افزودن کارمند: {display_name}')

    if provision == 'credentials':
        # Hand the one-time credentials back to the manager to deliver.
        return JsonResponse({
            'ok': True,
            'user': _user_dict(u, with_access=True),
            'credentials': {'username': u.username, 'password': password},
        })

    _invite, raw = InviteToken.issue(u)
    url = _invite_url(raw)
    emailed = _send_invite_email(u, url)
    return JsonResponse({
        'ok': True,
        'user': _user_dict(u, with_access=True),
        'invite_url': url,
        'emailed': emailed,
    })


@csrf_exempt
@require_manager
def team_member_detail_view(request, user_id):
    """POST /api/team/members/<id>/ — update / deactivate / resend-invite.

    Fields: display_name, phone, personnel_code, role, reports_to_id,
    can_manage_team, can_view_analytics, ai_assistant_enabled, active,
    resend_invite.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)
    manager = request.manager
    u = (PortalUser.objects.filter(id=user_id)
         .select_related('company', 'reports_to', 'org_role').first())
    if not u or not manager_can_target(manager, u):
        return JsonResponse({'error': 'دسترسی به این کاربر ندارید.'}, status=403)
    b = _body(request)

    if b.get('resend_invite'):
        if u.password_set:
            return JsonResponse({'error': 'این کاربر قبلاً حساب خود را فعال کرده است.'}, status=400)
        _invite, raw = InviteToken.issue(u)
        url = _invite_url(raw)
        emailed = _send_invite_email(u, url)
        return JsonResponse({'ok': True, 'invite_url': url, 'emailed': emailed,
                             'user': _user_dict(u, with_access=True)})

    if 'display_name' in b:
        u.display_name = (str(b['display_name'] or '')).strip()[:150]
    if 'phone' in b:
        u.phone = (str(b['phone'] or '')).strip()[:40]
    if 'personnel_code' in b:
        u.personnel_code = (str(b['personnel_code'] or '')).strip()[:60]
    for cap in ('can_manage_team', 'can_view_analytics', 'ai_assistant_enabled'):
        if cap in b:
            setattr(u, cap, bool(b[cap]))
    if b.get('org_role_id') or b.get('role'):
        org_role, role_err = _resolve_new_role(manager, b)
        if role_err is not None:
            return role_err
        if org_role is not None:
            u.org_role = org_role
            u.role = legacy_role_for_rank(org_role.rank)
        else:  # legacy-only fallback (no seeded positions)
            u.role = normalize_role(b.get('role'))
    if 'reports_to_id' in b:
        rid = b.get('reports_to_id')
        if not rid:
            u.reports_to = manager
        else:
            # Must be visible to the manager, and not this user or one of
            # their own descendants (no cycles).
            forbidden = subtree_user_ids(u, include_self=True)
            if rid in forbidden or rid not in manageable_user_ids(manager, include_self=True):
                return JsonResponse({'error': 'سرپرست انتخابی معتبر نیست.'}, status=400)
            u.reports_to = PortalUser.objects.filter(id=rid).first() or u.reports_to
    if 'active' in b:
        u.active = bool(b['active'])
        if not u.active:
            u.tokens.all().delete()
        u.invite_status = 'active' if (u.active and u.password_set) else (
            'disabled' if not u.active else u.invite_status)
    try:
        u.save()
    except IntegrityError:
        return JsonResponse({'error': 'به‌روزرسانی ناموفق بود.'}, status=400)
    return JsonResponse({'user': _user_dict(u, with_access=True)})


@csrf_exempt
@require_manager
def team_member_access_view(request, user_id):
    """POST /api/team/members/<id>/access/ {accesses:[{car_id, documents[]}]}

    Clamped to the company's purchased scope (managers can never grant beyond it).
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)
    manager = request.manager
    u = PortalUser.objects.filter(id=user_id).select_related('company').first()
    if not u or not manager_can_target(manager, u):
        return JsonResponse({'error': 'دسترسی به این کاربر ندارید.'}, status=403)
    accesses = _body(request).get('accesses') or []
    try:
        apply_managed_access(manager, u, accesses)
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)
    return JsonResponse({'user': _user_dict(u, with_access=True)})


@require_manager
def team_org_view(request):
    """GET /api/team/org/ -> the manager's visible slice of the org chart.

    Returns a FLAT member list (id, role, reports_to_id, ...) plus the
    company's positions; the client assembles whatever tree/grouping it wants
    (explicit reporting lines, by-rank pyramid, ...).
    """
    manager = request.manager
    ids = manageable_user_ids(manager, include_self=True)
    users = list(PortalUser.objects.filter(id__in=ids)
                 .select_related('reports_to', 'org_role')
                 .order_by('display_name', 'username'))
    dept = manager.company.department_label
    my_rank = user_rank(manager)
    visible = {u.id for u in users}
    members = []
    for u in users:
        members.append({
            'id': u.id,
            'name': u.display_name or u.username,
            'username': u.username,
            'role_id': u.org_role_id,
            'role_label': display_role_label(u, dept),
            'rank': user_rank(u),
            'color': (u.org_role.color if u.org_role_id and u.org_role else ''),
            # Parent only if it's visible to this viewer, so the client never
            # renders edges into users it may not see.
            'reports_to_id': u.reports_to_id if u.reports_to_id in visible else None,
            'invite_status': u.invite_status,
            'active': u.active,
            'is_self': u.id == manager.id,
            'can_manage_team': u.can_manage_team,
            'can_view_analytics': u.can_view_analytics,
            'ai_assistant_enabled': u.ai_assistant_enabled,
            'last_login_at': u.last_login_at.isoformat() if u.last_login_at else None,
        })
    return JsonResponse({
        'members': members,
        'roles': [_role_dict(r, my_rank) for r in _company_roles(manager)],
        'me': {'id': manager.id, 'rank': my_rank, 'scope': user_manage_scope(manager)},
    })


# ---------------------------------------------------------------------------
# Positions (company-defined hierarchy) — manager-configurable
# ---------------------------------------------------------------------------

def _shift_ranks(company_id, from_rank):
    """Open a slot at ``from_rank`` by pushing every rank >= it down one."""
    for r in OrgRole.objects.filter(company_id=company_id, rank__gte=from_rank).order_by('-rank'):
        r.rank += 1
        r.save(update_fields=['rank'])


def _clean_default_accesses(raw):
    """Normalize a position's access template: [{car_id:int, documents:[ids]}]."""
    if not isinstance(raw, list):
        return []
    out, seen = [], set()
    for item in raw[:200]:
        if not isinstance(item, dict):
            continue
        try:
            car_id = int(item.get('car_id'))
        except (TypeError, ValueError):
            continue
        if car_id in seen:
            continue
        docs = [d for d in (item.get('documents') or []) if isinstance(d, str)][:20]
        out.append({'car_id': car_id, 'documents': docs})
        seen.add(car_id)
    return out


@csrf_exempt
@require_manager
def team_roles_view(request):
    """GET  /api/team/roles/ -> {roles}
    POST /api/team/roles/ {name, manage_scope?, can_manage_team?,
                           can_view_analytics?, ai_assistant_enabled?, color?,
                           rank?, default_accesses?} -> create a position
    """
    manager = request.manager
    my_rank = user_rank(manager)

    if request.method == 'GET':
        return JsonResponse({'roles': [_role_dict(r, my_rank) for r in _company_roles(manager)],
                             'my_rank': my_rank})
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)

    b = _body(request)
    name = (str(b.get('name') or '')).strip()[:80]
    if not name:
        return JsonResponse({'error': 'نام نقش الزامی است.'}, status=400)
    if OrgRole.objects.filter(company_id=manager.company_id, name=name).exists():
        return JsonResponse({'error': 'نقشی با این نام وجود دارد.'}, status=400)
    scope = b.get('manage_scope') or 'none'
    if scope not in dict(OrgRole.MANAGE_SCOPE_CHOICES):
        return JsonResponse({'error': 'محدوده دسترسی نامعتبر است.'}, status=400)

    # New positions always sit strictly below the creator. Default: at the end.
    try:
        rank = int(b.get('rank') or 0)
    except (TypeError, ValueError):
        rank = 0
    max_rank = (OrgRole.objects.filter(company_id=manager.company_id)
                .order_by('-rank').values_list('rank', flat=True).first() or 0)
    if rank <= my_rank or rank > max_rank + 1:
        rank = max_rank + 1
    else:
        _shift_ranks(manager.company_id, rank)

    role = OrgRole.objects.create(
        company_id=manager.company_id, name=name, rank=rank, manage_scope=scope,
        can_manage_team=bool(b.get('can_manage_team')),
        can_view_analytics=bool(b.get('can_view_analytics')),
        ai_assistant_enabled=('ai_assistant_enabled' not in b) or bool(b.get('ai_assistant_enabled')),
        color=(str(b.get('color') or '')).strip()[:16],
        default_accesses=_clean_default_accesses(b.get('default_accesses')),
    )
    ActivityLog.objects.create(user=manager, action='role_add', detail=f'ایجاد نقش: {name}')
    return JsonResponse({'ok': True, 'role': _role_dict(role, my_rank),
                         'roles': [_role_dict(r, my_rank) for r in _company_roles(manager)]})


@csrf_exempt
@require_manager
def team_role_detail_view(request, role_id):
    """POST /api/team/roles/<id>/ — update / delete / bulk-apply a position.

    Fields: name, manage_scope, can_manage_team, can_view_analytics,
    ai_assistant_enabled, color, default_accesses,
    apply_defaults (bool — push caps+accesses onto current members),
    delete (bool) + reassign_to (required when the position has members).
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)
    manager = request.manager
    my_rank = user_rank(manager)
    role = OrgRole.objects.filter(id=role_id, company_id=manager.company_id).first()
    if role is None:
        return JsonResponse({'error': 'نقش یافت نشد.'}, status=404)
    if role.rank <= my_rank:
        return JsonResponse({'error': 'فقط نقش‌های پایین‌تر از جایگاه خودتان قابل ویرایش هستند.'}, status=403)
    b = _body(request)

    if b.get('delete'):
        member_ids = list(role.members.values_list('id', flat=True))
        target = None
        if member_ids:
            target = OrgRole.objects.filter(
                id=b.get('reassign_to'), company_id=manager.company_id).first()
            if target is None or target.id == role.id or target.rank <= my_rank:
                return JsonResponse(
                    {'error': 'برای حذف این نقش، نقش جایگزین معتبری برای اعضا انتخاب کنید.'},
                    status=400)
            role.members.update(org_role=target, role=legacy_role_for_rank(target.rank))
        name = role.name
        role.delete()
        ActivityLog.objects.create(user=manager, action='role_delete', detail=f'حذف نقش: {name}')
        return JsonResponse({'ok': True,
                             'roles': [_role_dict(r, my_rank) for r in _company_roles(manager)]})

    if 'name' in b:
        name = (str(b.get('name') or '')).strip()[:80]
        if not name:
            return JsonResponse({'error': 'نام نقش الزامی است.'}, status=400)
        clash = OrgRole.objects.filter(company_id=manager.company_id, name=name).exclude(id=role.id)
        if clash.exists():
            return JsonResponse({'error': 'نقشی با این نام وجود دارد.'}, status=400)
        role.name = name
    if 'manage_scope' in b:
        if b['manage_scope'] not in dict(OrgRole.MANAGE_SCOPE_CHOICES):
            return JsonResponse({'error': 'محدوده دسترسی نامعتبر است.'}, status=400)
        role.manage_scope = b['manage_scope']
    for cap in ('can_manage_team', 'can_view_analytics', 'ai_assistant_enabled'):
        if cap in b:
            setattr(role, cap, bool(b[cap]))
    if 'color' in b:
        role.color = (str(b.get('color') or '')).strip()[:16]
    if 'default_accesses' in b:
        role.default_accesses = _clean_default_accesses(b.get('default_accesses'))
    role.save()

    applied = 0
    if b.get('apply_defaults'):
        # Push the position's defaults onto its current members — but only the
        # ones this manager may actually manage, and only within what the
        # manager may delegate (apply_managed_access clamps).
        targets = manageable_user_ids(manager)
        for member in role.members.select_related('company', 'org_role'):
            if member.id not in targets:
                continue
            member.can_manage_team = role.can_manage_team
            member.can_view_analytics = role.can_view_analytics
            member.ai_assistant_enabled = role.ai_assistant_enabled
            member.save(update_fields=['can_manage_team', 'can_view_analytics',
                                       'ai_assistant_enabled'])
            if role.default_accesses:
                try:
                    apply_managed_access(manager, member, role.default_accesses)
                except ValueError:
                    pass
            applied += 1
        ActivityLog.objects.create(
            user=manager, action='role_apply',
            detail=f'اعمال دسترسی‌های نقش «{role.name}» به {applied} عضو')

    return JsonResponse({'ok': True, 'applied': applied,
                         'role': _role_dict(role, my_rank),
                         'roles': [_role_dict(r, my_rank) for r in _company_roles(manager)]})


@csrf_exempt
@require_manager
def team_roles_reorder_view(request):
    """POST /api/team/roles/reorder/ {order: [role_id, ...]}

    Re-ranks the positions BELOW the acting manager to match ``order`` (top to
    bottom). Positions at or above the manager keep their ranks.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)
    manager = request.manager
    my_rank = user_rank(manager)
    order = _body(request).get('order')
    if not isinstance(order, list) or not order:
        return JsonResponse({'error': 'ترتیب نقش‌ها نامعتبر است.'}, status=400)
    editable = {r.id: r for r in OrgRole.objects.filter(
        company_id=manager.company_id, rank__gt=my_rank)}
    wanted = [rid for rid in order if rid in editable]
    if set(wanted) != set(editable.keys()):
        return JsonResponse({'error': 'فهرست ارسالی با نقش‌های قابل ویرایش مطابقت ندارد.'}, status=400)
    next_rank = my_rank + 1
    for rid in wanted:
        role = editable[rid]
        if role.rank != next_rank:
            role.rank = next_rank
            role.save(update_fields=['rank'])
        next_rank += 1
    # Legacy charfield stays roughly in step with the new ordering.
    for u in PortalUser.objects.filter(company_id=manager.company_id,
                                       org_role_id__in=list(editable.keys())
                                       ).select_related('org_role'):
        legacy = legacy_role_for_rank(u.org_role.rank)
        if u.role != legacy:
            u.role = legacy
            u.save(update_fields=['role'])
    return JsonResponse({'ok': True,
                         'roles': [_role_dict(r, my_rank) for r in _company_roles(manager)]})


# ---------------------------------------------------------------------------
# Invite accept (public, token-gated)
# ---------------------------------------------------------------------------

@csrf_exempt
@rate_limited('invite', 30, 60)
def invite_view(request, token):
    """GET  /api/invite/<token>/          -> validate, {user}
    POST /api/invite/<token>/ {password} -> set password, activate, auto-login
    """
    invite = InviteToken.resolve(token)
    if not invite:
        return JsonResponse({'error': 'این لینک دعوت نامعتبر یا منقضی شده است.'}, status=400)
    u = invite.user
    if not u.active or not u.company.active:
        return JsonResponse({'error': 'این حساب غیرفعال است.'}, status=403)

    if request.method == 'GET':
        return JsonResponse({'ok': True, 'user': {
            'display_name': u.display_name, 'email': u.email,
            'username': u.username, 'company': u.company.name,
            'role_label': role_label(u.role, u.company.department_label),
        }})

    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)

    password = (str(_body(request).get('password') or '')).strip()
    if len(password) < 8:
        return JsonResponse({'error': 'رمز عبور باید حداقل ۸ نویسه باشد.'}, status=400)
    u.set_password(password)
    u.invite_status = 'active'
    u.last_login_at = timezone.now()
    u.save(update_fields=['password_hash', 'password_set', 'invite_status', 'last_login_at'])
    invite.consume()
    auth = AuthToken.issue(u)
    ActivityLog.objects.create(user=u, action='invite_accept', detail='فعال‌سازی حساب و ورود')
    return JsonResponse({'token': auth.key, 'user': _user_dict(u, with_access=True)})


# ---------------------------------------------------------------------------
# Team analytics (manager-scoped)  — Phase 2
# ---------------------------------------------------------------------------

def _range_days(request, default=30):
    try:
        return max(1, min(int(request.GET.get('range', default) or default), 365))
    except (TypeError, ValueError):
        return default


def build_team_analytics(viewer, days, member_id=None, category=None):
    """Usage analytics for everyone the viewer may see (+ themselves).

    Shared by the JSON analytics endpoint and the PDF report generator so the
    numbers can never diverge between the screen and the document.
    """
    since = timezone.now() - timezone.timedelta(days=days)
    vis_ids = manageable_user_ids(viewer, include_self=True)

    logs = ActivityLog.objects.filter(user_id__in=vis_ids, created_at__gte=since)
    if member_id:
        try:
            mid = int(member_id)
        except (TypeError, ValueError):
            mid = None
        if mid in vis_ids:
            logs = logs.filter(user_id=mid)
    if category:
        logs = logs.filter(category=category)

    dept = viewer.company.department_label
    # Category breakdown (only content-tagged events).
    cat_counts = {row['category']: row['n'] for row in
                  logs.exclude(category='').values('category').annotate(n=Count('id'))}
    categories = [
        {'id': cid, 'label': category_label(cid, 'fa'), 'label_en': category_label(cid, 'en'),
         'count': cat_counts.get(cid, 0)}
        for cid, _ in CONTENT_CATEGORIES
    ]
    categories = [c for c in categories if c['count'] > 0] or categories

    # Per-member usage.
    per_member_raw = {row['user_id']: row for row in
                      logs.values('user_id').annotate(n=Count('id'), last=Max('created_at'))}
    members = []
    for u in (PortalUser.objects.filter(id__in=vis_ids)
              .select_related('reports_to', 'org_role')):
        row = per_member_raw.get(u.id)
        members.append({
            'id': u.id, 'name': u.display_name or u.username,
            'role_label': display_role_label(u, dept),
            'rank': user_rank(u),
            'invite_status': u.invite_status,
            'active': u.active,
            'events': row['n'] if row else 0,
            'last_active': row['last'].isoformat() if row and row['last'] else None,
        })
    members.sort(key=lambda m: m['events'], reverse=True)

    # Daily time-series (events per day).
    day_counts = {}
    for a in logs.values_list('created_at', flat=True):
        key = a.date().isoformat()
        day_counts[key] = day_counts.get(key, 0) + 1
    series = [{'date': k, 'count': v} for k, v in sorted(day_counts.items())]

    # Top vehicles.
    top_cars = []
    for row in (logs.exclude(car__isnull=True)
                .values('car_id', 'car__brand_name', 'car__car_name', 'car__year')
                .annotate(n=Count('id')).order_by('-n')[:8]):
        top_cars.append({
            'car_id': row['car_id'],
            'label': f"{row['car__brand_name']} {row['car__car_name']} {row['car__year']}",
            'count': row['n'],
        })

    return {
        'range_days': days,
        'total_events': logs.count(),
        'active_members': sum(1 for m in members if m['events'] > 0),
        'categories': categories,
        'members': members,
        'series': series,
        'top_cars': top_cars,
        'action_breakdown': {row['action']: row['n'] for row in
                             logs.values('action').annotate(n=Count('id'))},
    }


@require_analytics
def team_analytics_view(request):
    """GET /api/team/analytics/?range=&member_id=&category=

    Scoped to everyone the viewer may see (their position's reach + self).
    Returns category usage, per-member usage, a daily series, top vehicles.
    """
    data = build_team_analytics(
        request.viewer, _range_days(request),
        member_id=request.GET.get('member_id'),
        category=request.GET.get('category'))
    return JsonResponse(data)


@require_analytics
def team_report_pdf_view(request):
    """GET /api/team/report/?range=30 -> a designed PDF usage report (fa/RTL).

    Heavy imports live inside api.reporting so the module (and its native
    Pango/Cairo deps) only load when a report is actually requested.
    """
    from .reporting import render_team_report_pdf  # lazy: heavy import
    viewer = request.viewer
    days = _range_days(request)
    data = build_team_analytics(viewer, days)
    try:
        pdf_bytes = render_team_report_pdf(viewer, data)
    except Exception:
        import logging
        logging.getLogger(__name__).exception('team report PDF failed')
        return JsonResponse({'error': 'ساخت گزارش PDF ناموفق بود.'}, status=500)
    from django.http import HttpResponse
    resp = HttpResponse(pdf_bytes, content_type='application/pdf')
    stamp = timezone.now().strftime('%Y%m%d')
    resp['Content-Disposition'] = f'attachment; filename="kgtechvault-team-report-{stamp}.pdf"'
    ActivityLog.objects.create(user=viewer, action='report_pdf',
                               detail=f'دریافت گزارش PDF ({days} روز)')
    return resp
