"""Append-only audit trail: who did what, to what, from where, and did it work.

Unlike ``Event`` (a bounded live feed) and ``ActivityLog`` (usage analytics),
``AuditLog`` rows are never trimmed and carry no foreign keys, so the record
survives the deletion of the user/company/car it describes.

Two ways in:
  * ``AuditMiddleware`` — records every authentication attempt and every
    mutating (non-GET) API call, with actor, outcome and a redacted body. For
    car-access endpoints it also snapshots the grants before and after, so a
    revoke is visible as a diff rather than just "PUT …/access/".
  * ``audit(...)`` — for code that wants to record a semantic action itself
    (management commands, background jobs).

Both are best-effort: auditing must never break the request it observes.
"""
import json
import logging
import re

from django.http import JsonResponse

from .admin_auth import require_admin_token
from .models import AuditLog

logger = logging.getLogger('kgkg.audit')

# Never stored, at any depth of the body.
_SECRET_KEYS = re.compile(
    r'pass(word)?|secret|token|code|otp|captcha|turnstile|key|authorization', re.I)
_MAX_BODY = 64 * 1024          # don't buffer large JSON bodies
_MAX_STR = 500                 # per-value truncation inside stored detail

# Authentication endpoints: audited on every method (they are all POST anyway)
# with an action name instead of the raw path.
_AUTH_ACTIONS = {
    '/api/auth/login/': 'auth.login',
    '/api/auth/verify-otp/': 'auth.verify_otp',
    '/api/auth/resend-otp/': 'auth.resend_otp',
    '/api/auth/logout/': 'auth.logout',
    '/api/auth/recover/start/': 'auth.recover_start',
    '/api/auth/recover/reset/': 'auth.recover_reset',
    '/api/admin/login/': 'admin.login',
    '/api/admin/verify-otp/': 'admin.verify_otp',
}

# High-volume or telemetry writes that are not business actions.
_SKIP_PREFIXES = (
    '/api/activity/', '/api/auth/ai-usage/', '/api/auth/chat-log/',
    '/api/auth/me/prefs/', '/api/assist/', '/api/feedback/', '/api/diagnose/',
    '/api/search/', '/api/media-auth/', '/api/vnc-auth/', '/api/events/',
    '/api/health/',
)

_USER_ACCESS = re.compile(r'^/api/admin/users/(\d+)/access/$')
_COMPANY_ACCESS = re.compile(r'^/api/admin/companies/(\d+)/access/$')


def client_ip(request):
    ip = request.META.get('HTTP_CF_CONNECTING_IP')
    if ip:
        return ip.strip()
    xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')


def redact(value, depth=0):
    if depth > 6:
        return '…'
    if isinstance(value, dict):
        return {k: ('[redacted]' if _SECRET_KEYS.search(str(k)) else redact(v, depth + 1))
                for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, depth + 1) for v in value[:200]]
    if isinstance(value, str) and len(value) > _MAX_STR:
        return value[:_MAX_STR] + '…'
    return value


def _outcome(status):
    if status < 400:
        return AuditLog.SUCCESS
    if status in (401, 403, 429):
        return AuditLog.DENIED
    return AuditLog.FAILURE


def audit(action, *, request=None, actor_type=AuditLog.SYSTEM, actor_id=None,
          actor_label='', company_id=None, target_type='', target_id='',
          outcome=AuditLog.SUCCESS, status_code=None, detail=None):
    """Write one audit row. Returns it, or None if the write failed."""
    try:
        return AuditLog.objects.create(
            action=action[:80], actor_type=actor_type, actor_id=actor_id,
            actor_label=(actor_label or '')[:150], company_id=company_id,
            target_type=target_type[:40], target_id=str(target_id or '')[:64],
            outcome=outcome, status_code=status_code,
            ip=client_ip(request) if request is not None else '',
            user_agent=(request.META.get('HTTP_USER_AGENT', '')[:300]
                        if request is not None else ''),
            method=request.method if request is not None else '',
            path=request.path[:300] if request is not None else '',
            detail=redact(detail or {}),
        )
    except Exception:
        logger.exception('audit write failed for %s', action)
        return None


# ---------------------------------------------------------------------------
# Actor resolution
# ---------------------------------------------------------------------------

def _resolve_actor(request):
    """(actor_type, actor_id, label, company_id) for whoever sent the request.

    Read-only: unlike the auth gates this never slides a session's expiry."""
    from .admin_auth import _configured_token, _presented_token
    from .models import AdminAuthToken, AuthToken
    import hmac

    presented = _presented_token(request)
    if presented:
        configured = _configured_token()
        if configured and hmac.compare_digest(presented, configured):
            return AuditLog.ADMIN, None, 'KG_ADMIN_TOKEN', None
        tok = AdminAuthToken.resolve(presented, select_related=('admin',))
        if tok:
            return AuditLog.ADMIN, tok.admin_id, tok.admin.username, None
    from .portal import _portal_token
    key = _portal_token(request)
    if key:
        tok = AuthToken.resolve(key, select_related=('user',))
        if tok:
            u = tok.user
            return AuditLog.USER, u.id, u.username, u.company_id
    return AuditLog.ANONYMOUS, None, '', None


# ---------------------------------------------------------------------------
# Access snapshots (before/after diff for grant changes)
# ---------------------------------------------------------------------------

def _access_snapshot(kind, obj_id):
    from .models import CompanyCarAccess, UserCarAccess
    if kind == 'user':
        rows = UserCarAccess.objects.filter(user_id=obj_id).values_list(
            'car_id', 'documents', 'admin_granted')
        return {str(c): {'documents': d or [], 'admin_granted': a} for c, d, a in rows}
    rows = CompanyCarAccess.objects.filter(company_id=obj_id).values_list('car_id', 'documents')
    return {str(c): {'documents': d or []} for c, d in rows}


def _diff(before, after):
    added = sorted(set(after) - set(before), key=int)
    removed = sorted(set(before) - set(after), key=int)
    changed = sorted((c for c in set(before) & set(after) if before[c] != after[c]), key=int)
    return {'added': {c: after[c] for c in added},
            'removed': {c: before[c] for c in removed},
            'changed': {c: {'before': before[c], 'after': after[c]} for c in changed}}


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

def _request_body(request):
    ctype = request.META.get('CONTENT_TYPE', '')
    if 'application/json' not in ctype:
        return None
    try:
        if int(request.META.get('CONTENT_LENGTH') or 0) > _MAX_BODY:
            return {'_note': 'body too large to record'}
        return json.loads(request.body or b'{}')
    except Exception:
        return None


def _form_body(request):
    """Multipart/form posts, read only if the view already parsed them (never
    force-buffer an upload here)."""
    if not hasattr(request, '_post'):
        return None
    out = {'fields': request.POST.dict()}
    files = getattr(request, '_files', None)
    if files:
        out['files'] = [{'name': f.name, 'size': f.size} for f in files.values()]
    return out


def _response_json(response):
    if getattr(response, 'streaming', False):
        return {}
    if 'application/json' not in response.get('Content-Type', ''):
        return {}
    try:
        data = json.loads(response.content or b'{}')
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


class AuditMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        auth_action = _AUTH_ACTIONS.get(path)
        if not auth_action and (
                request.method in ('GET', 'HEAD', 'OPTIONS')
                or not path.startswith('/api/')
                or path.startswith(_SKIP_PREFIXES)):
            return self.get_response(request)

        body = _request_body(request)
        snap = None
        try:
            m = _USER_ACCESS.match(path) or _COMPANY_ACCESS.match(path)
            if m:
                kind = 'user' if m.re is _USER_ACCESS else 'company'
                snap = (kind, int(m.group(1)), _access_snapshot(kind, int(m.group(1))))
            # Resolve before the view runs: logout deletes the token.
            actor = _resolve_actor(request) if not auth_action or auth_action == 'auth.logout' \
                else (AuditLog.ANONYMOUS, None, '', None)
        except Exception:
            logger.exception('audit pre-request failed')
            actor = (AuditLog.ANONYMOUS, None, '', None)

        response = self.get_response(request)

        try:
            self._record(request, response, path, auth_action, body, snap, actor)
        except Exception:
            logger.exception('audit record failed for %s', path)
        return response

    def _record(self, request, response, path, auth_action, body, snap, actor):
        status = response.status_code
        if status == 405:
            return
        actor_type, actor_id, label, company_id = actor
        detail = {}
        payload = body if body is not None else _form_body(request)
        if payload:
            detail['request'] = payload
        resp = _response_json(response)
        if status >= 400 and resp.get('error'):
            detail['error'] = str(resp['error'])[:300]

        target_type, target_id = '', ''
        if auth_action:
            action = auth_action
            # Who was trying to log in — from the response on success, else
            # the identifier they typed (never the password).
            who = resp.get('user') or resp.get('admin') or {}
            if isinstance(who, dict) and who.get('username'):
                label = who['username']
                actor_id = who.get('id', actor_id)
                actor_type = AuditLog.ADMIN if auth_action.startswith('admin.') else AuditLog.USER
            elif isinstance(body, dict):
                label = label or str(body.get('username') or body.get('identifier') or '')[:150]
            if auth_action == 'admin.login' and status == 200 and resp.get('token'):
                detail['no_2fa'] = True
            if resp.get('otp_required') or resp.get('otp_session'):
                detail['otp_sent'] = True
            target_type, target_id = 'account', label
        else:
            action = f'{request.method.lower()} {_route_name(request, path)}'
            kwargs = getattr(getattr(request, 'resolver_match', None), 'kwargs', {}) or {}
            for k in ('user_id', 'company_id', 'req_id', 'node_id'):
                if k in kwargs:
                    target_type, target_id = k[:-3] if k.endswith('_id') else k, kwargs[k]
                    break

        if snap and status < 400:
            kind, obj_id, before = snap
            diff = _diff(before, _access_snapshot(kind, obj_id))
            detail['access_diff'] = diff
            action = f'access.{kind}.update'

        audit(action, request=request, actor_type=actor_type, actor_id=actor_id,
              actor_label=label, company_id=company_id, target_type=target_type,
              target_id=target_id, outcome=_outcome(status), status_code=status,
              detail=detail)


def _route_name(request, path):
    match = getattr(request, 'resolver_match', None)
    route = getattr(match, 'route', '') if match else ''
    return (route or path.lstrip('/'))[:70]


# ---------------------------------------------------------------------------
# Admin read API
# ---------------------------------------------------------------------------

@require_admin_token
def admin_audit_view(request):
    """GET /api/admin/audit/?action=&actor=&outcome=&company_id=&target_id=&before_id=&limit=

    Newest first, keyset-paginated by ``before_id``."""
    qs = AuditLog.objects.all()
    g = request.GET
    if g.get('action'):
        qs = qs.filter(action__icontains=g['action'])
    if g.get('actor'):
        qs = qs.filter(actor_label__icontains=g['actor'])
    if g.get('outcome'):
        qs = qs.filter(outcome=g['outcome'])
    if g.get('company_id'):
        qs = qs.filter(company_id=g['company_id'])
    if g.get('target_id'):
        qs = qs.filter(target_id=g['target_id'])
    if g.get('ip'):
        qs = qs.filter(ip=g['ip'])
    if g.get('before_id'):
        qs = qs.filter(id__lt=g['before_id'])
    try:
        limit = max(1, min(int(g.get('limit') or 100), 500))
    except ValueError:
        limit = 100
    rows = list(qs.order_by('-id')[:limit])
    return JsonResponse({
        'items': [{
            'id': r.id, 'at': r.created_at.isoformat(), 'action': r.action,
            'actor_type': r.actor_type, 'actor_id': r.actor_id, 'actor': r.actor_label,
            'company_id': r.company_id, 'target_type': r.target_type,
            'target_id': r.target_id, 'outcome': r.outcome, 'status': r.status_code,
            'ip': r.ip, 'user_agent': r.user_agent, 'method': r.method,
            'path': r.path, 'detail': r.detail,
        } for r in rows],
        'next_before_id': rows[-1].id if len(rows) == limit else None,
    })
