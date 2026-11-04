"""Origin check for cookie-authenticated unsafe requests (#62, defence in depth).

51+ views are ``@csrf_exempt`` and some accept the ``kg_portal_token`` cookie.
That cookie is ``SameSite=Lax``, so browsers do not send it on a cross-site
POST/PUT/PATCH/DELETE; this middleware is a second, independent line: such a
request that carries the cookie (and no Authorization header) is refused when
its Origin - or, without one, its Referer - is not one of ours. A request with
neither header (server-to-server, e.g. Next.js forwarding the cookie) passes:
browsers always send Origin on a cross-site unsafe request.

Ours = settings.CSRF_TRUSTED_ORIGINS plus the request's own scheme+host.
KG_ORIGIN_GUARD=0 turns it off without a deploy.
"""
import os
from urllib.parse import urlsplit

from django.conf import settings
from django.http import JsonResponse

COOKIE = 'kg_portal_token'
UNSAFE = frozenset(('POST', 'PUT', 'PATCH', 'DELETE'))


def _origin_of(url):
    try:
        p = urlsplit(url)
    except ValueError:
        return None
    if not p.scheme or not p.netloc:
        return None
    return f'{p.scheme}://{p.netloc}'.lower()


def _ours(request, origin):
    trusted = {o.rstrip('/').lower() for o in getattr(settings, 'CSRF_TRUSTED_ORIGINS', [])}
    if origin in trusted:
        return True
    try:
        own = f'{request.scheme}://{request.get_host()}'.lower()
    except Exception:
        return False
    return origin == own


class OriginGuardMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (os.environ.get('KG_ORIGIN_GUARD', '1') != '0'
                and request.method in UNSAFE
                and request.COOKIES.get(COOKIE)
                and not request.META.get('HTTP_AUTHORIZATION')):
            raw = request.META.get('HTTP_ORIGIN')
            if raw is not None:
                origin = None if raw.strip().lower() == 'null' else _origin_of(raw)
            else:
                ref = request.META.get('HTTP_REFERER')
                origin = _origin_of(ref) if ref else ''
            if origin != '' and (origin is None or not _ours(request, origin)):
                return JsonResponse({'error': 'cross-origin request refused'}, status=403)
        return self.get_response(request)
