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


def _admin_session_valid(token):
    if not token:
        return False
    from .models import AdminAuthToken
    return AdminAuthToken.objects.filter(
        key=token, admin__active=True,
    ).exists()


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

        if configured and presented and hmac.compare_digest(presented, configured):
            return view(request, *args, **kwargs)
        if _admin_session_valid(presented):
            return view(request, *args, **kwargs)
        return JsonResponse({'error': 'unauthorized'}, status=401)
    return wrapped
