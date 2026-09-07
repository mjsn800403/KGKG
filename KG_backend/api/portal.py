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
import logging
import os
import urllib.request
import urllib.parse
import time
import re as _re

from django.db import IntegrityError
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from django.db.models import Count, Q

from .models import (
    ActivityLog, AdminAuthToken, AuthToken, Car, Company, CompanyCarAccess,
    OtpChallenge, PlatformAdmin, PortalUser, PurchaseRequest, UserCarAccess,
)
from .access import (
    CONTENT_CATEGORIES, DOC_TYPE_CHOICES, PACKAGE_CHOICES, ROLE_CHOICES, ROLE_LEVEL,
    VALID_CATEGORIES, VALID_DOCS, VALID_ROLES,
    apply_user_access, car_db_ready, category_label, display_role_label,
    normalize_role, resolve_category, role_label,
    user_ai_eligible, user_manage_scope,
    user_package_set, user_rank,
)
from .admin_auth import require_admin_token
from .ratelimit import rate_limited
from . import events


# A valid-format hash to check bad/absent logins against, so the wrong-password
# and no-such-user paths take the same (constant) time — no user enumeration.
# Computed once; the password it encodes is never used to authenticate anything.
from django.contrib.auth.hashers import make_password as _make_password
_DUMMY_PASSWORD_HASH = _make_password('kg-login-timing-equalizer')


# ---------------------------------------------------------------------------
# SMS OTP session store (in-process, TTL-based)
# ---------------------------------------------------------------------------
_logger_sms = logging.getLogger("kgkg.sms")
def _otp_phone_hint(phone: str) -> str:
    if len(phone) > 6:
        return phone[:3] + '*' * (len(phone) - 5) + phone[-2:]
    return phone


# Persian bodies are only accepted with the trailing "لغو11" opt-out line;
# without it the operator returns Value 11. ASCII bodies do not need it.
_OTP_SMS_TEXT = "خدمات گستر\nکد ورود : {0}\nلغو11"
_OTP_SMS_ASCII = "Khadamat Gostar\nlogin code : {0}"


def _post_sms(phone: str, text: str):
    """Send one SMS. Returns (sent, value), value being Melipayamak's status.

    RetStatus/StrRetStatus only say the request parsed; the real outcome is in
    Value -- a long RecID when sent, otherwise a documented failure code
    ("11" unicode rejected, "14" contains a link, "2" no credit, "5" bad line).
    """
    sms_user = os.environ.get("SMS_USERNAME", "")
    sms_key = os.environ.get("SMS_API_KEY", "")
    sms_from = os.environ.get("SMS_FROM", "")
    if not sms_user or not sms_key or not sms_from:
        _logger_sms.warning("SMS not configured (SMS_USERNAME/SMS_API_KEY/SMS_FROM missing)")
        return False, ""
    payload = json.dumps({
        "username": sms_user,
        "password": sms_key,
        "to": phone,
        "from": sms_from,
        "text": text,
        "isFlash": False,
    }).encode("utf-8")
    try:
        req = urllib.request.Request(
            "https://rest.payamak-panel.com/api/SendSMS/SendSMS",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        _logger_sms.warning("SendSMS transport error: %s", exc)
        return False, ""
    value = str(result.get("Value", "")).strip().split(",")[0]
    try:
        if int(value) > 1000:
            return True, value
    except ValueError:
        pass
    return False, value


def _send_sms_otp(phone: str, code: int) -> bool:
    """Send the login code, preferring the Persian body.

    """
    sent, value = _post_sms(phone, _OTP_SMS_TEXT.format(code))
    if sent:
        return True
    _logger_sms.warning("SendSMS failed for %s (Value=%s)", phone, value)
    return False


def _body(request):
    """Parsed JSON request body, always a dict.

    A body that is valid JSON but not an object (a bare string, list, or
    number) would otherwise flow into ``.get()`` and raise AttributeError →
    HTTP 500. Anything that isn't a JSON object collapses to ``{}`` so callers
    can treat missing fields uniformly.
    """
    try:
        data = json.loads(request.body or '{}')
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


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


# --- session cookie -------------------------------------------------------
# The session token is delivered as an HttpOnly cookie so page JavaScript (and
# therefore any XSS) cannot read it. `_portal_token` already accepts either the
# cookie or an Authorization header, so this is additive: clients still sending
# the bearer header keep working while the frontend migrates off localStorage.
PORTAL_COOKIE = 'kg_portal_token'


def _cookie_max_age():
    """Match the cookie lifetime to the token's own idle TTL, so the cookie can
    never outlive the credential it carries."""
    idle, absolute = AuthToken._ttls()
    return int(min(idle, absolute).total_seconds())


def _set_portal_cookie(response, raw_token):
    response.set_cookie(
        PORTAL_COOKIE, raw_token,
        max_age=_cookie_max_age(),
        httponly=True,
        secure=True,
        samesite='Lax',
        path='/',
    )
    return response


def _clear_portal_cookie(response):
    response.delete_cookie(PORTAL_COOKIE, path='/', samesite='Lax')
    return response


def portal_user(request):
    """Resolve the PortalUser from a Bearer token or session cookie, or None.

    ``AuthToken.resolve`` looks the token up by sha256 and refuses anything past
    its expiry; a live hit then slides the idle window forward (rate-limited
    internally to one write per 5 minutes, since this runs on every request).
    """
    key = _portal_token(request)
    if not key:
        return None
    token = AuthToken.resolve(key, select_related=('user', 'user__company'))
    if not token or not token.user.active or not token.user.company.active:
        return None
    u = token.user
    if u.locked:
        return None
    if u.access_expires_at and u.access_expires_at <= timezone.now():
        return None
    token.touch()
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
        'role_label': display_role_label(u, dept),
        'role_level': user_rank(u),
        'manage_scope': user_manage_scope(u),
        'company_id': u.company_id, 'company': u.company.name,
        'department_label': u.company.department_label,
        'reports_to': reports_to,
        'can_manage_team': u.can_manage_team,
        'can_view_analytics': u.can_view_analytics,
        'ai_assistant_enabled': u.ai_assistant_enabled,
        'browse_mode': getattr(u, 'browse_mode', 'modern'),
        'ai_eligible': user_ai_eligible(u),
        'packages': sorted(user_package_set(u)) if with_access else [],
        'active': u.active, 'locked': u.locked,
        # Lets the admin UI show the phone field only where it matters:
        # a phone is required to log in only for org-graph root seats.
        'otp_required': _otp_required(u),
        'invite_status': u.invite_status, 'password_set': u.password_set,
        'access_expires_at': u.access_expires_at.isoformat() if u.access_expires_at else None,
        'created_at': u.created_at.isoformat(),
        'last_login_at': u.last_login_at.isoformat() if u.last_login_at else None,
    }
    if with_access:
        # Show the user's full set of granted vehicles (entitlements). Whether a
        # car's content DB is on disk yet is a serve-time concern (car_view 404s),
        # not a reason to hide the grant from the manager/admin who set it.
        from .parts import parts_db_ready  # lazy: parts imports portal (cycle)
        d['accesses'] = [
            {'car': _car_dict(a.car), 'documents': a.documents, 'admin_granted': a.admin_granted,
             'ready': car_db_ready(a.car), 'parts_ready': parts_db_ready(a.car)}
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

def _client_ip(request):
    # Behind Cloudflare+nginx the real client is in CF-Connecting-IP; fall back
    # to the first X-Forwarded-For hop, then REMOTE_ADDR.
    ip = request.META.get("HTTP_CF_CONNECTING_IP")
    if ip:
        return ip.strip()
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def _verify_turnstile(request, token, expected_action="login"):
    """Canonical Cloudflare Turnstile server-side verification. Fails closed."""
    secret = os.environ.get("TURNSTILE_SECRET", "")
    if not secret:
        from django.conf import settings
        return bool(getattr(settings, "DEBUG", False))
    if not isinstance(token, str) or not token or len(token) > 2048:
        return False
    hostnames = {h.strip() for h in os.environ.get("TURNSTILE_HOSTNAMES", "").split(",") if h.strip()}
    data = urllib.parse.urlencode({
        "secret": secret,
        "response": token,
        "remoteip": _client_ip(request),
    }).encode()
    try:
        req = urllib.request.Request(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode())
    except Exception:
        return False
    _tlog = logging.getLogger("kgkg.turnstile")
    if not result.get("success"):
        _tlog.warning("turnstile FAIL success=false codes=%s hostname=%s action=%s", result.get("error-codes"), result.get("hostname"), result.get("action"))
        return False
    if result.get("action") != expected_action:
        _tlog.warning("turnstile FAIL action mismatch got=%s want=%s", result.get("action"), expected_action)
        return False
    if hostnames and result.get("hostname") not in hostnames:
        _tlog.warning("turnstile FAIL hostname mismatch got=%s allow=%s", result.get("hostname"), hostnames)
        return False
    return True


def _otp_required(user):
    """Every account logs in with the SMS second factor, so every account needs
    a phone on file. The admin who owns a seat is the one who sets it: the root
    admin fills in the admins below them, and each admin fills in their own
    seats. Kept as a function so the login gate and the admin UI can never
    disagree about who needs a number."""
    return True


def _issue_session(user):
    """Mint the portal session for an authenticated user (shared by the direct
    login path and the post-OTP path)."""
    user.last_login_at = timezone.now()
    user.save(update_fields=['last_login_at'])
    token = AuthToken.issue(user)
    ActivityLog.objects.create(user=user, action='login', detail='ورود به سامانه')
    try:
        events.emit_company('activity', user.company_id, {
            'user_id': user.id, 'user_name': user.display_name or user.username,
            'action': 'login', 'category': '', 'car': None,
            'detail': 'ورود به سامانه'}, user_id=user.id)
    except Exception:
        pass
    resp = JsonResponse({'token': token.key, 'user': _user_dict(user, with_access=True)})
    return _set_portal_cookie(resp, token.key)


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
    if not _verify_turnstile(request, b.get("turnstile_token") or "", "login"):
        return JsonResponse({"error": "تأیید امنیتی ناموفق بود. دوباره تلاش کنید."}, status=403)
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
    phone = (user.phone or '').strip()
    if not phone:
        return JsonResponse({'error': 'شماره موبایل برای این حساب ثبت نشده است. با پشتیبانی تماس بگیرید.'}, status=403)
    # Per-user SMS throttle: a live challenge sent < RESEND_INTERVAL ago blocks a
    # fresh send, so re-submitting the login form cannot spam a user with codes.
    _wait = OtpChallenge.recent_send_wait(user)
    if _wait:
        resp = JsonResponse({'error': f'کد تأیید به‌تازگی ارسال شده است. لطفاً {_wait} ثانیه صبر کنید.'}, status=429)
        resp['Retry-After'] = str(_wait)
        return resp
    code = secrets.randbelow(900000) + 100000
    sent = _send_sms_otp(phone, code)
    if not sent:
        from django.conf import settings as _s
        if not getattr(_s, 'DEBUG', False):
            return JsonResponse({'error': 'ارسال کد تأیید ناموفق بود. لطفاً دوباره تلاش کنید.'}, status=503)
        _logger_sms.warning("DEBUG OTP for %s: %s", user.username, code)
    _challenge, otp_session = OtpChallenge.issue(user, phone, code)
    return JsonResponse({'otp_session': otp_session, 'phone_hint': _otp_phone_hint(phone)})


@csrf_exempt
def logout_view(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)
    key = _portal_token(request)
    if key:
        AuthToken.objects.filter(key_hash=AuthToken._hash(key)).delete()
    return _clear_portal_cookie(JsonResponse({'ok': True}))


@csrf_exempt
@rate_limited('verify_otp', 10, 60)
def verify_otp_view(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)
    b = _body(request)
    session_id = (b.get('otp_session') or '').strip()
    code = (b.get('code') or '').strip()
    if not session_id or not code:
        return JsonResponse({'error': 'اطلاعات ناقص است.'}, status=400)
    challenge = OtpChallenge.resolve(session_id)
    if challenge is None or not challenge.check_code(code):
        return JsonResponse({'error': 'کد وارد شده اشتباه یا منقضی شده است.'}, status=401)
    user = challenge.user
    if not user.active or not user.company.active or user.locked:
        return JsonResponse({'error': 'این حساب غیرفعال شده است.'}, status=403)
    if user.access_expires_at and user.access_expires_at <= timezone.now():
        return JsonResponse({'error': 'دسترسی این حساب منقضی شده است.'}, status=403)
    return _issue_session(user)


@csrf_exempt
@rate_limited('resend_otp', 3, 60)
def resend_otp_view(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)
    b = _body(request)
    session_id = (b.get('otp_session') or '').strip()
    challenge = OtpChallenge.resolve(session_id)
    if challenge is None:
        return JsonResponse({'error': 'جلسه منقضی شده است. دوباره وارد شوید.'}, status=400)
    wait_secs = challenge.resend_wait()
    if wait_secs:
        return JsonResponse({'error': f'لطفاً {wait_secs} ثانیه صبر کنید.'}, status=429)
    code = secrets.randbelow(900000) + 100000
    challenge.rotate(code)
    sent = _send_sms_otp(challenge.phone, code)
    if not sent:
        from django.conf import settings as _s
        if not getattr(_s, 'DEBUG', False):
            return JsonResponse({'error': 'ارسال کد تأیید ناموفق بود.'}, status=503)
        _logger_sms.warning("DEBUG resend OTP: %s", code)
    return JsonResponse({'ok': True})


def me_view(request):
    """GET /api/auth/me -> the logged-in user + their granted cars/docs.

    Also performs the localStorage -> HttpOnly cookie upgrade: a client that
    authenticated with a bearer header and has no session cookie yet gets one
    issued here. That covers every session created before the cookie existed,
    on the first page load, without asking the user to log in again.
    """
    user = portal_user(request)
    if not user:
        return JsonResponse({'error': 'unauthorized'}, status=401)
    resp = JsonResponse({'user': _user_dict(user, with_access=True)})
    try:
        if _bearer(request) and not (request.COOKIES.get(PORTAL_COOKIE) or '').strip():
            _set_portal_cookie(resp, _bearer(request))
    except Exception:
        pass          # upgrade is best-effort; never break /me over it
    return resp


@csrf_exempt
def me_prefs_view(request):
    """POST /api/auth/me/prefs/ {browse_mode} -> update the caller's own
    preferences. Only self-editable, low-risk display prefs live here."""
    user = portal_user(request)
    if not user:
        return JsonResponse({'error': 'unauthorized'}, status=401)
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)
    b = _body(request)
    if 'browse_mode' in b:
        mode = str(b.get('browse_mode') or '').strip()
        if mode not in ('modern', 'classic'):
            return JsonResponse({'error': 'invalid browse_mode'}, status=400)
        user.browse_mode = mode
        user.save(update_fields=['browse_mode'])
    return JsonResponse({'user': _user_dict(user, with_access=True)})


def fleet_view(request):
    """GET /api/auth/fleet/ -> catalog rows for cars this user may open.

    A car is servable when it has a manual DB, a parts DB, or both; the
    additive has_manual/has_parts flags let the frontend route the tile
    (parts-only vehicles have no manual tree to open). Old clients that only
    read brand/name/year keep working unchanged.
    """
    from .access import user_car_documents
    from .parts import parts_db_ready  # lazy: parts imports portal (cycle)
    user = portal_user(request)
    if not user:
        return JsonResponse({'error': 'unauthorized'}, status=401)
    car_ids = list(user.car_accesses.values_list('car_id', flat=True))
    if not car_ids:
        return JsonResponse({'items': []})
    items = []
    for c in Car.objects.filter(id__in=car_ids).order_by('brand_name', 'car_name', 'year'):
        has_manual = car_db_ready(c)
        # Advertise Parts only when the seat actually holds that layer —
        # parts_view enforces it, so a chip without the grant would be a
        # dead end (403 on click).
        has_parts = parts_db_ready(c) and 'parts' in (user_car_documents(user, c) or set())
        if not (has_manual or has_parts):
            continue
        items.append({
            'brand_name': c.brand_name,
            'car_name': c.car_name,
            'year': c.year,
            'has_manual': has_manual,
            'has_parts': has_parts,
        })
    return JsonResponse({'items': items})


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
    elif b.get('brand') and b.get('model'):
        # Content pages send brand/model names, not the catalog id; resolve so
        # the activity (and the recommendations built from it) attach to a car.
        cq = Car.objects.filter(brand_name__iexact=str(b['brand']),
                                car_name__iexact=str(b['model']))
        if b.get('year'):
            try:
                cq = cq.filter(year=int(b['year']))
            except (TypeError, ValueError):
                pass
        car = cq.first()
    node_title = (str(b.get('node_title') or '')).strip()[:300]
    app_url = (str(b.get('app_url') or '')).strip()[:600]
    if action:
        log = ActivityLog.objects.create(
            user=user, action=action, detail=detail,
            category=category, car=car, node_title=node_title, app_url=app_url)
        # Live company activity feed (managers/analytics viewers) + the user's
        # own stream (drives "continue where you left off" and recommendations).
        try:
            from . import events
            payload = {
                'activity_id': log.id, 'user_id': user.id,
                'user_name': user.display_name or user.username,
                'action': action, 'category': category,
                'car': ({'id': car.id, 'label': f'{car.brand_name} {car.car_name}'}
                        if car else None),
                'node_title': node_title, 'detail': detail,
            }
            events.emit_company('activity', user.company_id, payload, user_id=user.id)
        except Exception:
            pass
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
    """GET /api/admin/cars/ — the FULL catalog (admin sees everything).

    Every row carries its health indicators (data completeness, missing or
    empty sections, indexing state, outstanding processing) so the admin can
    filter the fleet by quality without opening the data-quality report, and
    so an access grant shows whether the car it grants is actually servable.
    """
    from .dataquality import latest_health_by_car
    from .models import VehicleSpec

    health, audited_at = latest_health_by_car()
    spec_fields = {
        car_id: len([k for k in (data or {}) if not str(k).startswith('@')])
        for car_id, data in VehicleSpec.objects.values_list('car_id', 'data')
    }

    from .parts import parts_db_ready  # lazy: parts imports portal (cycle)
    items = []
    for c in Car.objects.order_by('brand_name', 'car_name'):
        row = _car_dict(c)
        row['ready'] = car_db_ready(c)
        row['has_parts'] = parts_db_ready(c)
        row['health'] = health.get(c.id)
        row['has_spec'] = c.id in spec_fields
        row['spec_fields'] = spec_fields.get(c.id, 0)
        items.append(row)
    return JsonResponse({
        'items': items,
        'audited_at': audited_at.isoformat() if audited_at else None,
    })


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
        events.emit('admin_changed', {'entity': 'company', 'id': c.id, 'action': 'create'})
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
        # Clamp to the same lengths the create path enforces — SQLite does not
        # honour VARCHAR limits, so an unclamped update could store a huge blob.
        _limits = {'name': 200, 'reg_no': 60, 'landline': 40, 'mobile': 40,
                   'note': 2000, 'department_label': 80}
        for f, lim in _limits.items():
            if f in b:
                setattr(c, f, (str(b[f] or '')).strip()[:lim])
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
        events.emit('admin_changed', {'entity': 'company', 'id': c.id, 'action': 'update'})
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
    events.emit('admin_changed', {'entity': 'company', 'id': c.id, 'action': 'access'})
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
        events.emit('admin_changed', {'entity': 'user', 'id': u.id, 'action': 'create', 'company_id': u.company_id})
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
            uid, cid = u.id, u.company_id
            u.tokens.all().delete()
            u.delete()
            events.emit('admin_changed', {'entity': 'user', 'id': uid, 'action': 'delete', 'company_id': cid})
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
        if b.get('role') or 'reports_to_id' in b:
            # Admin edits obey the same org-chart invariant as the team module:
            # reporting edges must point strictly upward in rank.
            from .access import enforce_org_consistency
            enforce_org_consistency(u.company_id)
            u.refresh_from_db()
        if 'ai_assistant_enabled' in b:
            # Mirror the AI toggle onto the user's seat (see orggraph.sync_user_to_node).
            from .orggraph import sync_user_to_node  # lazy: avoids import cycle
            sync_user_to_node(u)
        events.emit('admin_changed', {'entity': 'user', 'id': u.id, 'action': 'update', 'company_id': u.company_id})
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
    # Keep the org-graph seat in step so /admin and /team never disagree.
    from .orggraph import sync_user_to_node  # lazy: avoids import cycle
    sync_user_to_node(u)
    events.emit('admin_changed', {'entity': 'user', 'id': u.id, 'action': 'access', 'company_id': u.company_id})
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
