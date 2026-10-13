"""Admin-only gate for the embedded Grafana log dashboards at /grafana/.

Same shape as vncauth: the admin UI holds a bearer token an <iframe> cannot
send, so the admin page first asks for a ticket (``POST
/api/admin/grafana-ticket/``) — a signed, short-lived, HttpOnly cookie scoped to
``/grafana/``. nginx checks every /grafana/ request against ``grafana_auth_view``
via auth_request and only then forwards it with Grafana's auth-proxy header, so
Grafana itself (loopback-only, ops/observability) never sees an unchecked user.
"""

from django.core import signing
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .admin_auth import require_admin_token
from .vncauth import _admin_from_request

COOKIE = 'kg_gf'
PATH = '/grafana/'
SALT = 'kg-grafana-ticket'
TTL = 8 * 60 * 60  # seconds


@csrf_exempt
@require_admin_token
def grafana_ticket_view(request):
    """POST -> sets the ticket cookie for /grafana/."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)
    admin = _admin_from_request(request)
    value = signing.dumps({'a': admin.pk if admin else 0}, salt=SALT)
    resp = JsonResponse({'ok': True, 'path': PATH})
    resp.set_cookie(COOKIE, value, max_age=TTL, path=PATH, secure=True,
                    httponly=True, samesite='Strict')
    return resp


def grafana_auth_view(request):
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
