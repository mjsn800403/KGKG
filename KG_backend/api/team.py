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
    apply_managed_access, category_label, 
    default_capabilities_for_role, display_role_label, enforce_org_consistency,
    find_valid_supervisor, legacy_role_for_rank,
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

def _as_id(value):
    """Coerce a client-supplied id (int or numeric string) to int, else None.

    Form controls serialize ids as strings; every id comparison downstream is
    against integer sets, so normalize once at the boundary.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _emit_team(event_type, company_id, payload):
    """Best-effort team event so every open team view stays in sync live."""
    try:
        from . import events
        events.emit_company(event_type, company_id, payload)
    except Exception:
        pass


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


# ---------------------------------------------------------------------------
# NOTE: the OrgRole-based team/member/role CRUD endpoints were removed when the
# org-graph canvas (api/orggraph_api.py) replaced them. What remains here is the
# legacy invite-acceptance view plus company usage analytics + the PDF report.
# ---------------------------------------------------------------------------


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
              .select_related('reports_to')):
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
