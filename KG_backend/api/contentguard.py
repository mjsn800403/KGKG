"""Per-user caps on document reads: catch and stop bulk copying (scraping).

Every document request from a signed-in portal user is counted per user per
hour, in two buckets:
  * page  -- manual pages (car_view), parts catalogs, labor times, FRM tables;
  * media -- every image/file behind /media (nginx asks /api/media-auth/).
Crossing the WARN level raises a `sec:scrape:<user>` alert (alert_rules SMSes
the admins for every sec: alert); crossing BLOCK answers 429 until the hour
window slides. Defaults are far above what a person reading reaches; tune
with KG_CG_PAGE_WARN / KG_CG_PAGE_BLOCK / KG_CG_MEDIA_WARN / KG_CG_MEDIA_BLOCK.

Counters use the shared ratelimit store (one SQLite file for all workers), so
the cap is per user, not per worker. Fail-open: a broken counter never blocks.
"""
import os
import re
import threading
import time
from collections import defaultdict, deque

from django.http import JsonResponse

from . import ratelimit

WINDOW = 3600
_LIMITS = {
    'page': (int(os.environ.get('KG_CG_PAGE_WARN', 300)), int(os.environ.get('KG_CG_PAGE_BLOCK', 900))),
    'media': (int(os.environ.get('KG_CG_MEDIA_WARN', 2000)), int(os.environ.get('KG_CG_MEDIA_BLOCK', 6000))),
}
_PAGE = re.compile(r'^/(api/(parts|labor-times|frm)/.+|(?!api/|admin/|media/|static/|health)[^/]+/[^/]+/.+)')
_MEDIA = re.compile(r'^/api/media-auth/$')

_LOCK = threading.Lock()
_LOCAL = defaultdict(deque)      # fallback when the shared store is unusable (and in tests)


def bucket(path):
    if _MEDIA.match(path):
        return 'media'
    if _PAGE.match(path):
        return 'page'
    return None


def _count_and_add(key):
    """Hits for `key` in the last hour (before this one), then record this one."""
    now = time.time()
    try:
        if ratelimit._STORE:
            conn = ratelimit._store()
            conn.execute('BEGIN IMMEDIATE')
            try:
                n = conn.execute('SELECT COUNT(*) FROM hits WHERE k=? AND ts>=?',
                                 (key, now - WINDOW)).fetchone()[0]
                conn.execute('INSERT INTO hits VALUES (?, ?)', (key, now))
                conn.execute('COMMIT')
                return n
            except Exception:
                conn.execute('ROLLBACK')
                raise
    except Exception:
        pass
    with _LOCK:
        dq = _LOCAL[key]
        while dq and dq[0] < now - WINDOW:
            dq.popleft()
        n = len(dq)
        dq.append(now)
        return n


def _alert(user, kind, n, blocked):
    from . import monitoring
    try:
        monitoring._raise_alert(
            f'sec:scrape:{user.id}', 'critical' if blocked else 'warning',
            (f'برداشت انبوه مستندات: کاربر {user.username} در یک ساعت {n} '
             f'{"صفحه" if kind == "page" else "تصویر/فایل"} باز کرده'
             + (' و موقتاً مسدود شد.' if blocked else '.')),
            {'user_id': user.id, 'username': user.username, 'kind': kind, 'count': n, 'blocked': blocked})
    except Exception:
        pass


def check(request):
    """None to let the request through, or a 429 response."""
    kind = bucket(request.path)
    if not kind:
        return None
    from .portal import portal_user
    try:
        user = portal_user(request)
    except Exception:
        return None
    if not user:
        return None
    warn, block = _LIMITS[kind]
    n = _count_and_add(f'cg:{kind}:{user.id}') + 1
    if n == warn:
        _alert(user, kind, n, False)
    if n > block:
        if n == block + 1:
            _alert(user, kind, n, True)
        return JsonResponse({'error': 'تعداد درخواست‌های شما در یک ساعت از حد مجاز گذشته است. کمی بعد دوباره تلاش کنید.'},
                            status=429, headers={'Retry-After': '600'})
    return None


class ContentGuardMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            denied = check(request)
        except Exception:      # fail-open
            denied = None
        return denied or self.get_response(request)
