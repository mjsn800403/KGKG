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

from .models import (
    ActivityLog, AuthToken, Car, Company, CompanyCarAccess,
    DOC_TYPE_CHOICES, PortalUser, PurchaseRequest, ROLE_CHOICES, UserCarAccess,
)
from .ratelimit import rate_limited, require_admin_token

VALID_ROLES = {r for r, _ in ROLE_CHOICES}
VALID_DOCS = {d for d, _ in DOC_TYPE_CHOICES}


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


def portal_user(request):
    """Resolve the PortalUser from a Bearer token, or None."""
    key = _bearer(request)
    if not key:
        return None
    token = AuthToken.objects.filter(key=key).select_related('user', 'user__company').first()
    if token and token.user.active and token.user.company.active:
        return token.user
    return None


def _car_dict(car):
    return {'id': car.id, 'brand': car.brand_name, 'model': car.car_name, 'year': car.year}


def _user_dict(u, with_access=False):
    d = {
        'id': u.id, 'username': u.username, 'display_name': u.display_name,
        'role': u.role, 'role_label': dict(ROLE_CHOICES).get(u.role, u.role),
        'company_id': u.company_id, 'company': u.company.name,
        'ai_assistant_enabled': u.ai_assistant_enabled, 'active': u.active,
        'created_at': u.created_at.isoformat(),
        'last_login_at': u.last_login_at.isoformat() if u.last_login_at else None,
    }
    if with_access:
        d['accesses'] = [
            {'car': _car_dict(a.car), 'documents': a.documents}
            for a in u.car_accesses.select_related('car')
        ]
    return d


def _company_dict(c, deep=False):
    d = {
        'id': c.id, 'name': c.name, 'reg_no': c.reg_no,
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
    """POST /api/auth/login {username, password} -> {token, user}"""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)
    b = _body(request)
    username = (b.get('username') or '').strip()
    password = b.get('password') or ''
    user = PortalUser.objects.filter(username__iexact=username).select_related('company').first()
    if not user or not user.check_password(password):
        return JsonResponse({'error': 'نام کاربری یا رمز عبور اشتباه است.'}, status=401)
    if not user.active or not user.company.active:
        return JsonResponse({'error': 'این حساب غیرفعال شده است. با پشتیبانی تماس بگیرید.'}, status=403)
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


@csrf_exempt
@rate_limited('activity', 120, 60)
def activity_view(request):
    """POST /api/activity/ {action, detail?} — usage signal for the admin report."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)
    user = portal_user(request)
    if not user:
        return JsonResponse({'error': 'unauthorized'}, status=401)
    b = _body(request)
    action = (str(b.get('action') or '')).strip()[:60]
    detail = (str(b.get('detail') or '')).strip()[:400]
    if action:
        ActivityLog.objects.create(user=user, action=action, detail=detail)
    return JsonResponse({'ok': True})


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
def admin_cars_view(request):
    """GET /api/admin/cars/ — the FULL catalog (admin sees everything)."""
    return JsonResponse({'items': [_car_dict(c) for c in Car.objects.order_by('brand_name', 'car_name')]})


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
        for f in ('name', 'reg_no', 'landline', 'mobile', 'note'):
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
        role = b.get('role')
        if role not in VALID_ROLES:
            return JsonResponse({'error': 'نقش سازمانی نامعتبر است.'}, status=400)
        username = (str(b.get('username') or '')).strip()[:100]
        if not username:
            return JsonResponse({'error': 'نام کاربری الزامی است.'}, status=400)
        password = (str(b.get('password') or '')).strip() or _gen_password()
        u = PortalUser(
            company=company, username=username, role=role,
            display_name=(str(b.get('display_name') or '')).strip()[:150],
            ai_assistant_enabled=bool(b.get('ai_assistant_enabled')) and company.ai_assistant_enabled,
        )
        u.set_password(password)
        try:
            u.save()
        except IntegrityError:
            return JsonResponse({'error': 'این نام کاربری قبلاً استفاده شده است.'}, status=400)
        return JsonResponse({'ok': True, 'user': _user_dict(u, with_access=True), 'password': password})

    qs = PortalUser.objects.select_related('company')
    company_id = request.GET.get('company_id')
    if company_id:
        qs = qs.filter(company_id=company_id)
    return JsonResponse({'items': [_user_dict(u, with_access=True) for u in qs]})


@csrf_exempt
@require_admin_token
def admin_user_detail_view(request, user_id):
    """POST /api/admin/users/<id>/ {active?, ai_assistant_enabled?, display_name?,
    role?, reset_password?} — returns the new password when reset."""
    u = PortalUser.objects.filter(id=user_id).select_related('company').first()
    if not u:
        return JsonResponse({'error': 'not found'}, status=404)
    new_password = None
    if request.method == 'POST':
        b = _body(request)
        if 'active' in b:
            u.active = bool(b['active'])
            if not u.active:
                u.tokens.all().delete()
        if 'ai_assistant_enabled' in b:
            u.ai_assistant_enabled = bool(b['ai_assistant_enabled']) and u.company.ai_assistant_enabled
        if 'display_name' in b:
            u.display_name = (str(b['display_name'] or '')).strip()[:150]
        if b.get('role') in VALID_ROLES:
            u.role = b['role']
        if b.get('reset_password'):
            new_password = _gen_password()
            u.set_password(new_password)
            u.tokens.all().delete()
        u.save()
    resp = {'user': _user_dict(u, with_access=True)}
    if new_password:
        resp['password'] = new_password
    return JsonResponse(resp)


@csrf_exempt
@require_admin_token
def admin_user_access_view(request, user_id):
    """POST /api/admin/users/<id>/access/ {accesses: [{car_id, documents[]}]}

    Replaces the user's grants. Every grant is clamped to the company's
    purchased scope — a user can never see a car or a document layer the
    company didn't buy.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)
    u = PortalUser.objects.filter(id=user_id).select_related('company').first()
    if not u:
        return JsonResponse({'error': 'not found'}, status=404)
    accesses = _body(request).get('accesses') or []
    if not isinstance(accesses, list):
        return JsonResponse({'error': 'accesses must be a list'}, status=400)

    company_scope = {
        a.car_id: (set(a.documents) if a.documents else VALID_DOCS)
        for a in u.company.car_accesses.all()
    }
    u.car_accesses.all().delete()
    for a in accesses:
        car_id = a.get('car_id')
        if car_id not in company_scope:
            continue  # outside what the company bought
        docs = [d for d in (a.get('documents') or []) if d in company_scope[car_id]]
        UserCarAccess.objects.create(user=u, car_id=car_id, documents=docs)
    return JsonResponse({'user': _user_dict(u, with_access=True)})


# ---------------------------------------------------------------------------
# Admin: activity report
# ---------------------------------------------------------------------------

@require_admin_token
def admin_activity_view(request):
    """GET /api/admin/activity/?limit=&user_id=&company_id= — usage report."""
    try:
        limit = max(1, min(int(request.GET.get('limit', 200) or 200), 1000))
    except (TypeError, ValueError):
        limit = 200
    qs = ActivityLog.objects.select_related('user', 'user__company')
    if request.GET.get('user_id'):
        qs = qs.filter(user_id=request.GET['user_id'])
    if request.GET.get('company_id'):
        qs = qs.filter(user__company_id=request.GET['company_id'])
    items = [{
        'id': a.id, 'user': a.user.username, 'company': a.user.company.name,
        'role_label': dict(ROLE_CHOICES).get(a.user.role, a.user.role),
        'action': a.action, 'detail': a.detail,
        'created_at': a.created_at.isoformat(),
    } for a in qs[:limit]]
    return JsonResponse({'items': items})
