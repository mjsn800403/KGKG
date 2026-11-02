"""Admin gate: env secret OR platform-admin session token."""

import hmac
import os
from functools import wraps

from django.conf import settings
from django.http import JsonResponse


def _configured_token():
    return (os.environ.get('KG_ADMIN_TOKEN') or '').strip()


def _presented_token(request):
    auth = request.META.get('HTTP_AUTHORIZATION', '')
    if auth.lower().startswith('bearer '):
        return auth[7:].strip()
    return (request.META.get('HTTP_X_ADMIN_TOKEN', '') or '').strip()


_PROXY_HEADERS = ('HTTP_CF_CONNECTING_IP', 'HTTP_X_FORWARDED_FOR', 'HTTP_X_REAL_IP')


def _from_server_itself(request):
    """True only for a direct loopback call (server scripts, cron), never for
    traffic relayed by Cloudflare/nginx/Next, which always carries a proxy
    header. The static KG_ADMIN_TOKEN has no 2FA, so it must not work from
    the internet; people sign in for an admin session instead."""
    if request.META.get('REMOTE_ADDR') not in ('127.0.0.1', '::1'):
        return False
    return not any(request.META.get(h) for h in _PROXY_HEADERS)


def _admin_session(token):
    """The live session's PlatformAdmin, or None.

    Resolution is by sha256 (the raw key is never stored) and rejects anything
    past ``expires_at``; a hit slides the idle window forward.
    """
    if not token:
        return None
    from .models import AdminAuthToken
    obj = AdminAuthToken.resolve(token, select_related=('admin',))
    if not obj or not obj.admin.active:
        return None
    obj.touch()
    return obj.admin


def _admin_session_valid(token):
    """Boolean form of :func:`_admin_session`, kept because api/events.py
    resolves a viewer without needing the admin row itself."""
    return _admin_session(token) is not None


def acting_admin(request):
    """The PlatformAdmin behind this request, or None for a loopback call made
    with the static KG_ADMIN_TOKEN (a server script or cron, which is not a
    person). Views that record ownership use this instead of inventing the
    literal string 'admin'."""
    return getattr(request, 'platform_admin', None)


def require_admin_token(view):
    """Gate admin views behind KG_ADMIN_TOKEN or a platform-admin session."""
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        configured = _configured_token()
        presented = _presented_token(request)

        if not configured and not getattr(settings, 'DEBUG', False):
            return JsonResponse(
                {'error': 'admin_disabled',
                 'detail': 'KG_ADMIN_TOKEN is not configured on the server.'},
                status=503)

        if (configured and presented and hmac.compare_digest(presented, configured)
                and _from_server_itself(request)):
            return view(request, *args, **kwargs)
        admin = _admin_session(presented)
        if admin is not None:
            request.platform_admin = admin
            return view(request, *args, **kwargs)
        return JsonResponse({'error': 'unauthorized'}, status=401)
    return wrapped
