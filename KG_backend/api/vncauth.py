"""Admin-only gate for the TIS browser screen (noVNC) at /kg-vnc/.

The admin UI authenticates with a bearer token, which an <iframe> and the noVNC
WebSocket cannot send. So an authenticated admin first asks for a ticket
(``POST /api/admin/pipeline/ {action: vnc_ticket}``): a signed, short-lived,
HttpOnly cookie scoped to ``/kg-vnc/``. nginx then checks every /kg-vnc/
request (page, assets, WebSocket upgrade) against ``vnc_auth_view`` via
auth_request. The VNC server itself has no password and listens on localhost
only, so this cookie is the whole gate.
"""

from django.core import signing
from django.http import HttpResponse

COOKIE = 'kg_vnc'
PATH = '/kg-vnc/'
SALT = 'kg-vnc-ticket'
TTL = 2 * 60 * 60  # seconds; the WebSocket is only checked when it opens


def _admin_from_request(request):
    """The PlatformAdmin behind the request's bearer token, or None (env token)."""
    from .admin_auth import _presented_token
    from .models import AdminAuthToken
    obj = AdminAuthToken.resolve(_presented_token(request), select_related=('admin',))
    return obj.admin if obj else None


def issue_ticket(request, response):
    """Attach a fresh ticket cookie to ``response`` (caller is already admin-gated)."""
    admin = _admin_from_request(request)
    value = signing.dumps({'a': admin.pk if admin else 0}, salt=SALT)
    response.set_cookie(COOKIE, value, max_age=TTL, path=PATH, secure=True,
                        httponly=True, samesite='Strict')
    return response


def vnc_auth_view(request):
    """nginx auth_request target: 204 = let through, 401 = refuse."""
    from .models import PlatformAdmin
    raw = request.COOKIES.get(COOKIE)
    if not raw:
        return HttpResponse(status=401)
    try:
        data = signing.loads(raw, salt=SALT, max_age=TTL)
    except signing.BadSignature:
        return HttpResponse(status=401)
    aid = data.get('a')
    if aid and not PlatformAdmin.objects.filter(pk=aid, active=True).exists():
        return HttpResponse(status=401)
    return HttpResponse(status=204)
