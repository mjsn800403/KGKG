"""Reject request text containing NUL characters with a 400.

PostgreSQL text columns cannot store U+0000 (psycopg raises DataError), while
SQLite silently accepted it. No legitimate form field, query parameter or JSON
string here contains a NUL, so it is refused at the edge instead of surfacing
as a 500 from whichever query first touches the value.

Only text payloads are inspected: query string, path, form-encoded and JSON
bodies. Binary uploads (multipart ZIP/CSV) legitimately contain NUL bytes and
are left alone.
"""
from django.http import JsonResponse

_TEXT_TYPES = ('application/json', 'application/x-www-form-urlencoded', 'text/')


def _has_nul(request):
    if '\x00' in request.path or '%00' in request.META.get('QUERY_STRING', ''):
        return True
    if any('\x00' in v for vs in request.GET.lists() for v in vs[1]):
        return True
    ctype = (request.content_type or '').lower()
    if request.method in ('POST', 'PUT', 'PATCH') and ctype.startswith(_TEXT_TYPES):
        body = request.body
        # raw NUL, or JSON's escaped form of it
        if b'\x00' in body or b'\\u0000' in body.lower():
            return True
    return False


class NulGuardMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if _has_nul(request):
            return JsonResponse({'error': 'درخواست نامعتبر است.'}, status=400)
        return self.get_response(request)
