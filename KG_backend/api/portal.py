"""Portal auth + admin panel API.

Two audiences:

* Portal users (company seats): token login, "me" (their granted cars/docs),
  activity self-logging. Issued and managed by the admin.
* The platform admin: gated by KG_ADMIN_TOKEN (same shared-secret gate the
  review queue uses; in DEBUG with no token configured it stays open so local
  dev works without ceremony). Sees everything: purchase requests, companies,
  users, per-user grants, the full car catalog, and the usage/activity report.

Deliberately dependency-free (no DRF) to match the rest of the project.
"""
import json
import secrets
import string

from django.db import IntegrityError
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from django.db.models import Count, Q

from .models import (
    ActivityLog, AdminAuthToken, AuthToken, Car, Company, CompanyCarAccess,
    PlatformAdmin, PortalUser, PurchaseRequest, UserCarAccess,
)
from .access import (
    CONTENT_CATEGORIES, DOC_TYPE_CHOICES, PACKAGE_CHOICES, ROLE_CHOICES, ROLE_LEVEL,
    VALID_CATEGORIES, VALID_DOCS, VALID_ROLES,
    apply_user_access, car_db_ready, category_label, normalize_role, resolve_category,
    role_label, user_ai_eligible, user_package_set,
)
from .admin_auth import require_admin_token
from .ratelimit import rate_limited


# A valid-format hash to check bad/absent logins against, so the wrong-password
# and no-such-user paths take the same (constant) time — no user enumeration.
# Computed once; the password it encodes is never used to authenticate anything.
from django.contrib.auth.hashers import make_password as _make_password
_DUMMY_PASSWORD_HASH = _make_password('kg-login-timing-equalizer')


def _body(request):
    try:
        return json.loads(request.body or '{}')
    except (ValueError, TypeError):
        return {}


def _bearer(request):
    auth = request.META.get('HTTP_AUTHORIZATION', '')
    if auth.lower().startswith('bearer '):
        return auth[7:].strip()
    return ''


def _portal_token(request):
    """Session token from the Authorization header OR the ``kg_portal_token``
    cookie. The cookie path is what lets Next.js server components (SSR) carry
    the session when they fetch content — the browser sends the cookie to the
    Next server, which forwards it here."""
    key = _bearer(request)
    if key:
        return key
    try:
        return (request.COOKIES.get('kg_portal_token') or '').strip()
    except Exception:
        return ''


def portal_user(request):
    """Resolve the PortalUser from a Bearer token or session cookie, or None."""
    key = _portal_token(request)
    if not key:
        return None
    token = AuthToken.objects.filter(key=key).select_related('user', 'user__company').first()
    if not token or not token.user.active or not token.user.company.active:
        return None
    u = token.user
    if u.locked:
        return None
    if u.access_expires_at and u.access_expires_at <= timezone.now():
        return None
    return u


def _car_dict(car):
    return {'id': car.id, 'brand': car.brand_name, 'model': car.car_name, 'year': car.year}


def _user_dict(u, with_access=False):
    dept = u.company.department_label if hasattr(u, 'company') else ''
    reports_to = None
    if u.reports_to_id:
        reports_to = {'id': u.reports_to_id,
                      'name': (u.reports_to.display_name or u.reports_to.username)
                      if u.reports_to else None}
    d = {
        'id': u.id, 'username': u.username, 'display_name': u.display_name,
        'email': u.email, 'phone': u.phone, 'personnel_code': u.personnel_code,
        'role': normalize_role(u.role),
        'role_label': role_label(u.role, dept),
        'role_level': ROLE_LEVEL.get(normalize_role(u.role)),
        'company_id': u.company_id, 'company': u.company.name,
        'department_label': u.company.department_label,
        'reports_to': reports_to,
        'can_manage_team': u.can_manage_team,
        'can_view_analytics': u.can_view_analytics,
        'ai_assistant_enabled': u.ai_assistant_enabled,
        'ai_eligible': user_ai_eligible(u),
        'packages': sorted(user_package_set(u)) if with_access else [],
        'active': u.active, 'locked': u.locked,
        'invite_status': u.invite_status, 'password_set': u.password_set,
        'access_expires_at': u.access_expires_at.isoformat() if u.access_expires_at else None,
        'created_at': u.created_at.isoformat(),
        'last_login_at': u.last_login_at.isoformat() if u.last_login_at else None,
    }
    if with_access:
        # Show the user's full set of granted vehicles (entitlements). Whether a
        # car's content DB is on disk yet is a serve-time concern (car_view 404s),
        # not a reason to hide the grant from the manager/admin who set it.
        d['accesses'] = [
            {'car': _car_dict(a.car), 'documents': a.documents, 'admin_granted': a.admin_granted,
             'ready': car_db_ready(a.car)}
            for a in u.car_accesses.select_related('car')
        ]
    return d


def _company_dict(c, deep=False):
    d = {
        'id': c.id, 'name': c.name, 'department_label': c.department_label,
        'reg_no': c.reg_no,
        'landline': c.landline, 'mobile': c.mobile,
        'employees_count': c.employees_count, 'seats_count': c.seats_count,
        'is_demo': c.is_demo, 'ai_assistant_enabled': c.ai_assistant_enabled,
        'active': c.active, 'note': c.note, 'created_at': c.created_at.isoformat(),
        'users_count': c.users.count(),
    }
    if deep:
        d['accesses'] = [
            {'car': _car_dict(a.car), 'documents': a.documents}
            for a in c.car_accesses.select_related('car')
        ]
        d['users'] = [_user_dict(u, with_access=True) for u in c.users.all()]
    return d


# ---------------------------------------------------------------------------
# Portal user auth
# ---------------------------------------------------------------------------

@csrf_exempt
@rate_limited('login', 15, 60)
def login_view(request):
    """POST /api/auth/login {username, password} -> {token, user}

    ``username`` may be a username OR an email (invited employees log in with
    their email). Invited-but-not-accepted accounts are rejected until they
    set a password via the invite link.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)
    b = _body(request)
    username = (b.get('username') or '').strip()
    password = b.get('password') or ''
    user = (PortalUser.objects
            .filter(Q(username__iexact=username) | Q(email__iexact=username))
            .select_related('company').first())
    if not user or not user.password_set:
        # Equalise timing with the wrong-password path so a missing/invited
        # account isn't distinguishable from a bad password (no user enumeration).
        from django.contrib.auth.hashers import check_password as _cp
        _cp(password, _DUMMY_PASSWORD_HASH)
        return JsonResponse({'error': 'نام کاربری یا رمز عبور اشتباه است.'}, status=401)
    if not user.check_password(password):
        return JsonResponse({'error': 'نام کاربری یا رمز عبور اشتباه است.'}, status=401)
    if not user.active or not user.company.active:
        return JsonResponse({'error': 'این حساب غیرفعال شده است. با پشتیبانی تماس بگیرید.'}, status=403)
    if user.locked:
        return JsonResponse({'error': 'این حساب قفل شده است. با پشتیبانی تماس بگیرید.'}, status=403)
    if user.access_expires_at and user.access_expires_at <= timezone.now():
        return JsonResponse({'error': 'دسترسی این حساب منقضی شده است.'}, status=403)
    user.last_login_at = timezone.now()
    user.save(update_fields=['last_login_at'])
    token = AuthToken.issue(user)
    ActivityLog.objects.create(user=user, action='login', detail='ورود به سامانه')
    return JsonResponse({'token': token.key, 'user': _user_dict(user, with_access=True)})


@csrf_exempt
def logout_view(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)
    key = _bearer(request)
    if key:
        AuthToken.objects.filter(key=key).delete()
    return JsonResponse({'ok': True})


def me_view(request):
    """GET /api/auth/me -> the logged-in user + their granted cars/docs."""
    user = portal_user(request)
    if not user:
        return JsonResponse({'error': 'unauthorized'}, status=401)
    return JsonResponse({'user': _user_dict(user, with_access=True)})


def fleet_view(request):
    """GET /api/auth/fleet/ -> catalog rows for cars this user may open."""
    user = portal_user(request)
    if not user:
        return JsonResponse({'error': 'unauthorized'}, status=401)
    car_ids = list(user.car_accesses.values_list('car_id', flat=True))
    if not car_ids:
        return JsonResponse({'items': []})
    cars = [c for c in Car.objects.filter(id__in=car_ids).order_by('brand_name', 'car_name', 'year') if car_db_ready(c)]
    return JsonResponse({
        'items': [
            {
                'brand_name': c.brand_name,
                'car_name': c.car_name,
                'year': c.year,
            }
            for c in cars
        ],
    })


@csrf_exempt
@rate_limited('activity', 120, 60)
def activity_view(request):
    """POST /api/activity/ {action, detail?, category?, car_id?, node_title?}

    Usage signal for the admin report + analytics. ``category`` (if supplied) is
    validated against the canonical taxonomy; ``segments`` may be sent instead
    and the server resolves the category from them.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)
    user = portal_user(request)
    if not user:
        return JsonResponse({'error': 'unauthorized'}, status=401)
    b = _body(request)
    action = (str(b.get('action') or '')).strip()[:60]
    detail = (str(b.get('detail') or '')).strip()[:400]
    category = (str(b.get('category') or '')).strip()
    if not category and b.get('segments'):
        category = resolve_category(b.get('segments'))
    if category and category not in VALID_CATEGORIES:
        category = ''
    car = None
    if b.get('car_id'):
        car = Car.objects.filter(id=b['car_id']).first()
    node_title = (str(b.get('node_title') or '')).strip()[:300]
    if action:
        ActivityLog.objects.create(
            user=user, action=action, detail=detail,
            category=category, car=car, node_title=node_title)
    return JsonResponse({'ok': True})


# ---------------------------------------------------------------------------
# Platform admin login (default dev: admin / admin)
# ---------------------------------------------------------------------------

@csrf_exempt
@rate_limited('admin_login', 20, 60)
def admin_login_view(request):
    """POST /api/admin/login/ {username, password} -> {token, admin}"""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)
    b = _body(request)
    username = (b.get('username') or '').strip()
    password = b.get('password') or ''
    admin = PlatformAdmin.objects.filter(username__iexact=username).first()
    if not admin or not admin.check_password(password):
        return JsonResponse({'error': 'نام کاربری یا رمز عبور ادمین اشتباه است.'}, status=401)
    if not admin.active:
        return JsonResponse({'error': 'حساب ادمین غیرفعال است.'}, status=403)
    token = AdminAuthToken.issue(admin)
    return JsonResponse({'token': token.key, 'admin': {'username': admin.username}})


# ---------------------------------------------------------------------------
# Admin: overview / purchase requests
# ---------------------------------------------------------------------------

@require_admin_token
def admin_overview_view(request):
    """GET /api/admin/overview/ — dashboard counters."""
    return JsonResponse({
        'requests_new': PurchaseRequest.objects.filter(status='new').count(),
        'requests_total': PurchaseRequest.objects.count(),
        'companies': Company.objects.count(),
        'users': PortalUser.objects.count(),
        'cars': Car.objects.count(),
        'activities_today': ActivityLog.objects.filter(
            created_at__date=timezone.now().date()).count(),
    })


@require_admin_token
def admin_requests_view(request):
    """GET /api/admin/requests/ -> all purchase/demo requests, newest first."""
    items = [{
        'id': r.id, 'brand': r.brand, 'model': r.model, 'year': r.year,
        'documents': r.documents, 'company': r.company, 'landline': r.landline,
        'mobile': r.mobile, 'reg_no': r.reg_no, 'note': r.note,
        'employees_count': r.employees_count, 'seats_count': r.seats_count,
        'seat_plan': r.seat_plan or [],
        'wants_demo': r.wants_demo, 'wants_ai_assistant': r.wants_ai_assistant,
        'status': r.status, 'handled': r.handled,
        'created_at': r.created_at.isoformat(),
    } for r in PurchaseRequest.objects.all()[:500]]
    return JsonResponse({'items': items})


@csrf_exempt
@require_admin_token
def admin_request_status_view(request, req_id):
    """POST /api/admin/requests/<id>/status/ {status}"""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)
    status = (_body(request).get('status') or '').strip()
    if status not in dict(PurchaseRequest.STATUS_CHOICES):
        return JsonResponse({'error': 'invalid status'}, status=400)
    updated = PurchaseRequest.objects.filter(id=req_id).update(
        status=status, handled=status in ('approved', 'rejected'))
    if not updated:
        return JsonResponse({'error': 'not found'}, status=404)
    return JsonResponse({'ok': True})


# ---------------------------------------------------------------------------
# Admin: catalog / companies / access
# ---------------------------------------------------------------------------

@require_admin_token
def admin_packages_view(request):
    """GET /api/admin/packages/ — subscription package catalog."""
    return JsonResponse({'items': [{'id': p, 'label': l} for p, l in PACKAGE_CHOICES]})


@require_admin_token
def admin_cars_view(request):
    """GET /api/admin/cars/ — the FULL catalog (admin sees everything)."""
    items = []
    for c in Car.objects.order_by('brand_name', 'car_name'):
        row = _car_dict(c)
        row['ready'] = car_db_ready(c)
        items.append(row)
    return JsonResponse({'items': items})


@csrf_exempt
@require_admin_token
def admin_companies_view(request):
    """GET (list) / POST (create) /api/admin/companies/"""
    if request.method == 'POST':
        b = _body(request)
        name = (str(b.get('name') or '')).strip()[:200]
        if not name:
            return JsonResponse({'error': 'نام شرکت الزامی است.'}, status=400)
        try:
            c = Company.objects.create(
                name=name,
                department_label=(str(b.get('department_label') or 'خدمات پس از فروش')).strip()[:80],
                reg_no=(str(b.get('reg_no') or '')).strip()[:60],
                landline=(str(b.get('landline') or '')).strip()[:40],
                mobile=(str(b.get('mobile') or '')).strip()[:40],
                employees_count=b.get('employees_count') or None,
                seats_count=b.get('seats_count') or None,
                is_demo=bool(b.get('is_demo')),
                ai_assistant_enabled=bool(b.get('ai_assistant_enabled')),
                note=(str(b.get('note') or '')).strip()[:2000],
            )
        except IntegrityError:
            return JsonResponse({'error': 'شرکتی با این نام قبلاً ثبت شده است.'}, status=400)
        return JsonResponse({'ok': True, 'company': _company_dict(c, deep=True)})
    return JsonResponse({'items': [_company_dict(c) for c in Company.objects.all()]})


@csrf_exempt
@require_admin_token
def admin_company_detail_view(request, company_id):
    """GET / PATCH-via-POST /api/admin/companies/<id>/"""
    c = Company.objects.filter(id=company_id).first()
    if not c:
        return JsonResponse({'error': 'not found'}, status=404)
    if request.method == 'POST':
        b = _body(request)
        for f in ('name', 'reg_no', 'landline', 'mobile', 'note', 'department_label'):
            if f in b:
                setattr(c, f, (str(b[f] or '')).strip())
        for f in ('employees_count', 'seats_count'):
            if f in b:
                setattr(c, f, b[f] or None)
        for f in ('is_demo', 'ai_assistant_enabled', 'active'):
            if f in b:
                setattr(c, f, bool(b[f]))
        try:
            c.save()
        except IntegrityError:
            return JsonResponse({'error': 'شرکتی با این نام قبلاً ثبت شده است.'}, status=400)
    return JsonResponse({'company': _company_dict(c, deep=True)})


@csrf_exempt
@require_admin_token
def admin_company_access_view(request, company_id):
    """POST /api/admin/companies/<id>/access/ {accesses: [{car_id, documents[]}]}

    Replaces the company's purchased-car list. Per-user grants outside the new
    company scope are pruned automatically (users can never exceed the company).
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)
    c = Company.objects.filter(id=company_id).first()
    if not c:
        return JsonResponse({'error': 'not found'}, status=404)
    accesses = _body(request).get('accesses') or []
    if not isinstance(accesses, list):
        return JsonResponse({'error': 'accesses must be a list'}, status=400)

    keep_car_ids = set()
    c.car_accesses.all().delete()
    for a in accesses:
        car = Car.objects.filter(id=a.get('car_id')).first()
        if not car:
            continue
        docs = [d for d in (a.get('documents') or []) if d in VALID_DOCS]
        CompanyCarAccess.objects.create(company=c, car=car, documents=docs)
        keep_car_ids.add(car.id)

    # Prune user grants that fell outside the company's new scope.
    UserCarAccess.objects.filter(user__company=c).exclude(car_id__in=keep_car_ids).delete()
    return JsonResponse({'company': _company_dict(c, deep=True)})


# ---------------------------------------------------------------------------
# Admin: users + per-user grants
# ---------------------------------------------------------------------------

def _gen_password(n=10):
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(n))


@csrf_exempt
@require_admin_token
def admin_users_view(request):
    """GET (list, ?company_id=) / POST (create) /api/admin/users/

    Creating returns the generated one-time password so the admin can hand it
    to the company; only the hash is stored.
    """
    if request.method == 'POST':
        b = _body(request)
        company = Company.objects.filter(id=b.get('company_id')).first()
        if not company:
            return JsonResponse({'error': 'شرکت یافت نشد.'}, status=400)
        role = normalize_role(b.get('role'))
        if role not in VALID_ROLES:
            return JsonResponse({'error': 'نقش سازمانی نامعتبر است.'}, status=400)
        username = (str(b.get('username') or '')).strip()[:100]
        if not username:
            return JsonResponse({'error': 'نام کاربری الزامی است.'}, status=400)
        password = (str(b.get('password') or '')).strip() or _gen_password()
        expires = b.get('access_expires_at')
        access_expires_at = None
        if expires:
            try:
                access_expires_at = timezone.datetime.fromisoformat(str(expires).replace('Z', '+00:00'))
                if timezone.is_naive(access_expires_at):
                    access_expires_at = timezone.make_aware(access_expires_at)
            except (ValueError, TypeError):
                access_expires_at = None
        reports_to = None
        if b.get('reports_to_id'):
            reports_to = PortalUser.objects.filter(
                id=b['reports_to_id'], company=company).first()
        u = PortalUser(
            company=company, username=username, role=role,
            display_name=(str(b.get('display_name') or '')).strip()[:150],
            email=(str(b.get('email') or '')).strip()[:254] or None,
            phone=(str(b.get('phone') or '')).strip()[:40],
            personnel_code=(str(b.get('personnel_code') or '')).strip()[:60],
            reports_to=reports_to,
            can_manage_team=bool(b.get('can_manage_team')),
            can_view_analytics=bool(b.get('can_view_analytics')),
            ai_assistant_enabled=bool(b.get('ai_assistant_enabled')),
            locked=bool(b.get('locked')),
            access_expires_at=access_expires_at,
        )
        u.set_password(password)
        try:
            u.save()
        except IntegrityError:
            return JsonResponse({'error': 'این نام کاربری یا ایمیل قبلاً استفاده شده است.'}, status=400)
        return JsonResponse({'ok': True, 'user': _user_dict(u, with_access=True), 'password': password})

    qs = PortalUser.objects.select_related('company')
    company_id = request.GET.get('company_id')
    if company_id:
        qs = qs.filter(company_id=company_id)
    return JsonResponse({'items': [_user_dict(u, with_access=True) for u in qs]})


@csrf_exempt
@require_admin_token
def admin_user_detail_view(request, user_id):
    """POST /api/admin/users/<id>/ — update, delete, reset password."""
    u = PortalUser.objects.filter(id=user_id).select_related('company').first()
    if not u:
        return JsonResponse({'error': 'not found'}, status=404)
    new_password = None
    if request.method == 'POST':
        b = _body(request)
        if b.get('delete'):
            u.tokens.all().delete()
            u.delete()
            return JsonResponse({'ok': True, 'deleted': True})
        if 'active' in b:
            u.active = bool(b['active'])
            if not u.active:
                u.tokens.all().delete()
        if 'locked' in b:
            u.locked = bool(b['locked'])
            if u.locked:
                u.tokens.all().delete()
        if 'ai_assistant_enabled' in b:
            u.ai_assistant_enabled = bool(b['ai_assistant_enabled'])
        if 'can_manage_team' in b:
            u.can_manage_team = bool(b['can_manage_team'])
        if 'can_view_analytics' in b:
            u.can_view_analytics = bool(b['can_view_analytics'])
        if 'display_name' in b:
            u.display_name = (str(b['display_name'] or '')).strip()[:150]
        if 'email' in b:
            u.email = (str(b['email'] or '')).strip()[:254] or None
        if 'phone' in b:
            u.phone = (str(b['phone'] or '')).strip()[:40]
        if 'personnel_code' in b:
            u.personnel_code = (str(b['personnel_code'] or '')).strip()[:60]
        if 'reports_to_id' in b:
            rid = b.get('reports_to_id')
            if not rid:
                u.reports_to = None
            else:
                mgr = PortalUser.objects.filter(id=rid, company=u.company).first()
                if mgr and mgr.id != u.id:
                    u.reports_to = mgr
        if b.get('role'):
            role = normalize_role(b['role'])
            if role in VALID_ROLES:
                u.role = role
        if 'access_expires_at' in b:
            exp = b.get('access_expires_at')
            if not exp:
                u.access_expires_at = None
            else:
                try:
                    dt = timezone.datetime.fromisoformat(str(exp).replace('Z', '+00:00'))
                    u.access_expires_at = timezone.make_aware(dt) if timezone.is_naive(dt) else dt
                except (ValueError, TypeError):
                    pass
        if b.get('password'):
            new_password = (str(b['password'] or '')).strip() or _gen_password()
            u.set_password(new_password)
            u.tokens.all().delete()
        elif b.get('reset_password'):
            new_password = _gen_password()
            u.set_password(new_password)
            u.tokens.all().delete()
        try:
            u.save()
        except IntegrityError:
            return JsonResponse({'error': 'این ایمیل قبلاً استفاده شده است.'}, status=400)
    resp = {'user': _user_dict(u, with_access=True)}
    if new_password:
        resp['password'] = new_password
    return JsonResponse(resp)


@csrf_exempt
@require_admin_token
def admin_user_access_view(request, user_id):
    """POST /api/admin/users/<id>/access/ {accesses: [{car_id, documents[], admin_granted?}],
    override_purchase?: bool}

    Purchase-based grants are clamped to company scope. Admin-granted entries
    (admin_granted or override_purchase) bypass purchase limits.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)
    u = PortalUser.objects.filter(id=user_id).select_related('company').first()
    if not u:
        return JsonResponse({'error': 'not found'}, status=404)
    b = _body(request)
    accesses = b.get('accesses') or []
    override = bool(b.get('override_purchase'))
    # The platform admin may bypass the company's purchase scope (admin_granted).
    try:
        apply_user_access(u, accesses, override_purchase=override, allow_admin_grants=True)
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)
    return JsonResponse({'user': _user_dict(u, with_access=True)})


# ---------------------------------------------------------------------------
# Admin: activity report
# ---------------------------------------------------------------------------

@require_admin_token
def admin_activity_view(request):
    """GET /api/admin/activity/?limit=&user_id=&company_id=&category= — usage report."""
    try:
        limit = max(1, min(int(request.GET.get('limit', 200) or 200), 1000))
    except (TypeError, ValueError):
        limit = 200
    qs = ActivityLog.objects.select_related('user', 'user__company')
    if request.GET.get('user_id'):
        qs = qs.filter(user_id=request.GET['user_id'])
    if request.GET.get('company_id'):
        qs = qs.filter(user__company_id=request.GET['company_id'])
    if request.GET.get('category'):
        qs = qs.filter(category=request.GET['category'])
    items = [{
        'id': a.id, 'user': a.user.username, 'company': a.user.company.name,
        'role_label': role_label(a.user.role, a.user.company.department_label),
        'action': a.action, 'detail': a.detail,
        'category': a.category, 'category_label': category_label(a.category) if a.category else '',
        'created_at': a.created_at.isoformat(),
    } for a in qs[:limit]]
    return JsonResponse({'items': items})


# ---------------------------------------------------------------------------
# Admin: cross-company analytics (platform-wide)
# ---------------------------------------------------------------------------

@require_admin_token
def admin_analytics_view(request):
    """GET /api/admin/analytics/?range= — platform-wide usage analytics.

    Aggregated in SQL (no per-row transfer): platform totals, per-company usage,
    per-category breakdown, and the most active employees across all companies.
    """
    try:
        days = max(1, min(int(request.GET.get('range', 30) or 30), 365))
    except (TypeError, ValueError):
        days = 30
    since = timezone.now() - timezone.timedelta(days=days)
    logs = ActivityLog.objects.filter(created_at__gte=since)
    if request.GET.get('company_id'):
        logs = logs.filter(user__company_id=request.GET['company_id'])

    # Category breakdown.
    cat_counts = {row['category']: row['n'] for row in
                  logs.exclude(category='').values('category').annotate(n=Count('id'))}
    categories = [
        {'id': cid, 'label': category_label(cid, 'fa'), 'label_en': category_label(cid, 'en'),
         'count': cat_counts.get(cid, 0)}
        for cid, _ in CONTENT_CATEGORIES
    ]

    # Per-company usage.
    companies = []
    for row in (logs.values('user__company_id', 'user__company__name')
                .annotate(n=Count('id')).order_by('-n')):
        companies.append({
            'company_id': row['user__company_id'],
            'company': row['user__company__name'],
            'events': row['n'],
        })

    # Most active employees, cross-company.
    top_users = []
    for row in (logs.values('user_id', 'user__username', 'user__display_name',
                            'user__company__name')
                .annotate(n=Count('id')).order_by('-n')[:20]):
        top_users.append({
            'user_id': row['user_id'],
            'user': row['user__display_name'] or row['user__username'],
            'company': row['user__company__name'],
            'events': row['n'],
        })

    # Daily series.
    day_counts = {}
    for dt in logs.values_list('created_at', flat=True):
        key = dt.date().isoformat()
        day_counts[key] = day_counts.get(key, 0) + 1
    series = [{'date': k, 'count': v} for k, v in sorted(day_counts.items())]

    return JsonResponse({
        'range_days': days,
        'totals': {
            'events': logs.count(),
            'companies': Company.objects.count(),
            'users': PortalUser.objects.count(),
            'active_users': logs.values('user_id').distinct().count(),
        },
        'categories': categories,
        'companies_usage': companies,
        'top_users': top_users,
        'series': series,
        'action_breakdown': {row['action']: row['n'] for row in
                             logs.values('action').annotate(n=Count('id'))},
    })
