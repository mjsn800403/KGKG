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
    ActivityLog, AuthToken, Car, Company, InviteToken, PortalUser,
)
from .access import (
    CONTENT_CATEGORIES, PACKAGE_CHOICES, ROLE_CHOICES, ROLE_LEVEL, VALID_ROLES,
    apply_managed_access, category_label, default_capabilities_for_role,
    manager_can_target, manager_grantable_cars, normalize_role, role_can_manage,
    role_label, subtree_user_ids,
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


def _meta_payload(manager):
    """Form options for the team UI: assignable roles, managers, cars, packages."""
    my_level = ROLE_LEVEL.get(normalize_role(manager.role), 99)
    dept = manager.company.department_label
    roles = [
        {'id': r, 'label': role_label(r, dept), 'level': ROLE_LEVEL.get(r)}
        for r, _ in ROLE_CHOICES
        if (ROLE_LEVEL.get(r) or 99) > my_level  # only roles the manager outranks
    ]
    # Who a report can report to: the manager + everyone already in the subtree.
    sub_ids = subtree_user_ids(manager, include_self=True)
    managers = [
        {'id': u.id, 'name': u.display_name or u.username,
         'role_label': role_label(u.role, dept)}
        for u in PortalUser.objects.filter(id__in=sub_ids).order_by('display_name', 'username')
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
        'company': {'id': manager.company_id, 'name': manager.company.name,
                    'ai_assistant_enabled': manager.company.ai_assistant_enabled},
    }


def _members_qs(manager):
    ids = subtree_user_ids(manager)
    return (PortalUser.objects.filter(id__in=ids)
            .select_related('company', 'reports_to')
            .order_by('display_name', 'username'))


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
    role = normalize_role(b.get('role'))
    # Provisioning mode: 'invite' (email invite, employee sets own password) or
    # 'credentials' (manager creates a username + password on the spot — for
    # employees without an email). Defaults sensibly from whether an email exists.
    provision = (str(b.get('provision') or '')).strip().lower()
    if provision not in ('invite', 'credentials'):
        provision = 'invite' if email else 'credentials'

    if not display_name:
        return JsonResponse({'error': 'نام و نام خانوادگی الزامی است.'}, status=400)
    if role not in VALID_ROLES:
        return JsonResponse({'error': 'نقش سازمانی نامعتبر است.'}, status=400)
    if not role_can_manage(manager.role, role):
        return JsonResponse({'error': 'نمی‌توانید کاربری هم‌سطح یا بالاتر از خودتان ایجاد کنید.'}, status=403)
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

    # reports_to defaults to the creating manager; if given, must be in subtree+self.
    reports_to = manager
    if b.get('reports_to_id'):
        rid = b['reports_to_id']
        if rid not in subtree_user_ids(manager, include_self=True):
            return JsonResponse({'error': 'سرپرست انتخابی معتبر نیست.'}, status=400)
        reports_to = PortalUser.objects.filter(id=rid).first() or manager

    caps = default_capabilities_for_role(role)
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

    # Optional initial car/doc grants (clamped to what the manager can delegate).
    accesses = b.get('accesses')
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
    u = PortalUser.objects.filter(id=user_id).select_related('company', 'reports_to').first()
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
    if b.get('role'):
        role = normalize_role(b['role'])
        if role not in VALID_ROLES or not role_can_manage(manager.role, role):
            return JsonResponse({'error': 'نقش انتخابی مجاز نیست.'}, status=403)
        u.role = role
    if 'reports_to_id' in b:
        rid = b.get('reports_to_id')
        if not rid:
            u.reports_to = manager
        else:
            # Must be in the manager's subtree+self, and not this user or one of
            # their own descendants (no cycles).
            forbidden = subtree_user_ids(u, include_self=True)
            if rid in forbidden or rid not in subtree_user_ids(manager, include_self=True):
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
    """GET /api/team/org/ -> reports-to tree rooted at the manager."""
    manager = request.manager
    ids = subtree_user_ids(manager, include_self=True)
    users = list(PortalUser.objects.filter(id__in=ids).select_related('reports_to'))
    dept = manager.company.department_label
    by_parent = {}
    for u in users:
        by_parent.setdefault(u.reports_to_id, []).append(u)

    def node(u):
        return {
            'id': u.id, 'name': u.display_name or u.username,
            'role_label': role_label(u.role, dept),
            'invite_status': u.invite_status,
            'children': [node(c) for c in by_parent.get(u.id, [])],
        }

    return JsonResponse({'root': node(manager)})


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


@require_analytics
def team_analytics_view(request):
    """GET /api/team/analytics/?range=&member_id=&category=

    Scoped to the viewer's own reports subtree (+ self). Returns category usage,
    per-member usage, a daily time-series, and top vehicles.
    """
    viewer = request.viewer
    since = timezone.now() - timezone.timedelta(days=_range_days(request))
    sub_ids = subtree_user_ids(viewer, include_self=True)

    logs = ActivityLog.objects.filter(user_id__in=sub_ids, created_at__gte=since)
    member_id = request.GET.get('member_id')
    if member_id:
        try:
            mid = int(member_id)
        except (TypeError, ValueError):
            mid = None
        if mid in sub_ids:
            logs = logs.filter(user_id=mid)
    category = request.GET.get('category')
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
    for u in PortalUser.objects.filter(id__in=sub_ids).select_related('reports_to'):
        row = per_member_raw.get(u.id)
        members.append({
            'id': u.id, 'name': u.display_name or u.username,
            'role_label': role_label(u.role, dept),
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

    return JsonResponse({
        'range_days': _range_days(request),
        'total_events': logs.count(),
        'active_members': sum(1 for m in members if m['events'] > 0),
        'categories': categories,
        'members': members,
        'series': series,
        'top_cars': top_cars,
        'action_breakdown': {row['action']: row['n'] for row in
                             logs.values('action').annotate(n=Count('id'))},
    })
