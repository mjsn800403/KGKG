"""Rate limiting for the support chat.

Two mechanisms, chosen by cost:

* ``poll_ok`` is an in-process sliding window keyed by thread. A poll is the
  hottest request and must stay cheap, and the shared store does a write
  transaction per call. The window is per gunicorn worker, so the effective
  allowance is up to the worker count times the configured value: this
  contains abuse, it does not meter usage.
* ``shared_ok`` uses ``api.ratelimit``'s store (visible to every worker) for
  the low-rate endpoints where exactness matters.

Limits are keyed by thread (the visitor's own token), not by IP, so visitors
sharing an office or mobile NAT do not eat each other's allowance. The only
per-IP counters are creation, and FAILED token checks: a valid visitor never
touches the second, so a neighbour's bad requests cannot block them.
"""
import os
import threading
import time
from collections import OrderedDict, deque

from django.http import JsonResponse

from api import ratelimit

from . import config

MAX_BUCKETS = 5000
_lock = threading.Lock()
_buckets = OrderedDict()


def _now():
    return time.monotonic()


def reset():
    with _lock:
        _buckets.clear()


def client_ip(request):
    return ratelimit._client_ip(request)


def poll_ok(thread_id):
    """(allowed, retry_after_seconds) for one poll of ``thread_id``."""
    count, window = config.limit('poll')
    if count == 0 or os.environ.get('KG_RL_DISABLE') == '1':
        return True, 0
    now = _now()
    with _lock:
        hits = _buckets.get(thread_id)
        if hits is None:
            hits = _buckets[thread_id] = deque()
            while len(_buckets) > MAX_BUCKETS:
                _buckets.popitem(last=False)
        else:
            _buckets.move_to_end(thread_id)
        while hits and hits[0] <= now - window:
            hits.popleft()
        if len(hits) >= count:
            return False, max(1, int(hits[0] + window - now) + 1)
        hits.append(now)
    return True, 0


def shared_ok(name, key):
    """(allowed, retry_after_seconds) against the shared store."""
    count, window = config.limit(name)
    if count == 0 or os.environ.get('KG_RL_DISABLE') == '1':
        return True, 0
    try:
        return ratelimit._allow(f'sc_{name}:{key}', count, window)
    except Exception:
        return True, 0        # a limiter fault must not take the chat down


def too_many(retry):
    resp = JsonResponse({'error': 'تعداد درخواست‌ها زیاد است. کمی بعد دوباره تلاش کنید.',
                         'code': 'rate_limited'}, status=429)
    resp['Retry-After'] = str(max(1, int(retry or 1)))
    return resp
