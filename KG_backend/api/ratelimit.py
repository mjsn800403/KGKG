"""Dependency-free request guards: a per-IP sliding-window rate limiter and a
shared-secret admin gate.

Why hand-rolled (no DRF / django-ratelimit / redis):
  * the rest of this project deliberately stays dependency-light and runs from a
    single local process, so an in-process limiter is both sufficient and the
    least-surprising fit;
  * the two things we actually need to protect are cheap to express: cap how
    often any one client can hit the cost/abuse-sensitive endpoints, and refuse
    write/admin endpoints to anyone without the configured secret.

Scope / honesty about limits:
  * counters live in this process's memory. With one worker (the documented dev
    setup) that is exactly right. Under multiple workers each worker keeps its
    own window, so the effective limit is N x the configured value — fine as an
    abuse backstop, not a billing-grade quota. Swap in a shared store if you
    scale out.
  * the limiter is fail-OPEN (a bug in the guard never blocks a real answer);
    the admin gate is fail-CLOSED in production (no token configured => deny).
"""
import hmac
import os
import threading
import time
from collections import defaultdict, deque
from functools import wraps

from django.conf import settings
from django.http import JsonResponse

# ---------------------------------------------------------------------------
# Per-IP sliding-window limiter
# ---------------------------------------------------------------------------
_LOCK = threading.Lock()
_HITS = defaultdict(deque)        # ip -> deque[monotonic timestamps]
_LAST_SWEEP = 0.0

# Trust X-Forwarded-For only when explicitly told to (i.e. you actually run
# behind a proxy that sets it). Off by default: otherwise any client can spoof
# the header and rotate IPs to dodge the limit.
_TRUST_XFF = os.environ.get('KG_TRUST_XFF', '0') == '1'


def _client_ip(request):
    if _TRUST_XFF:
        xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
        if xff:
            return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '') or 'unknown'


def _parse_rule(raw, default):
    """'30/60' -> (30 requests, 60 seconds). Falls back to `default` on garbage."""
    try:
        n, win = raw.split('/')
        n, win = int(n), float(win)
        if n > 0 and win > 0:
            return n, win
    except (ValueError, AttributeError):
        pass
    return default


def _sweep(now):
    """Drop empty/stale buckets occasionally so memory can't grow unbounded
    from one-off IPs. Cheap: runs at most once a minute."""
    global _LAST_SWEEP
    if now - _LAST_SWEEP < 60.0:
        return
    _LAST_SWEEP = now
    for ip in list(_HITS.keys()):
        dq = _HITS[ip]
        while dq and dq[0] < now - 3600.0:
            dq.popleft()
        if not dq:
            _HITS.pop(ip, None)


def _allow(ip, limit, window):
    now = time.monotonic()
    with _LOCK:
        _sweep(now)
        dq = _HITS[ip]
        cutoff = now - window
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= limit:
            retry = max(1, int(dq[0] + window - now) + 1)
            return False, retry
        dq.append(now)
        return True, 0


def rate_limited(name, default_limit, default_window):
    """Decorator: cap a view at `default_limit` requests / `default_window`s per
    client IP. Override per-endpoint at runtime with env KG_RL_<NAME>="N/seconds"
    (e.g. KG_RL_ASSIST="60/60"); set "0/0" or KG_RL_DISABLE=1 to turn off."""
    default = (default_limit, float(default_window))

    def deco(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if os.environ.get('KG_RL_DISABLE') == '1':
                return view(request, *args, **kwargs)
            raw = os.environ.get(f'KG_RL_{name.upper()}')
            limit, window = _parse_rule(raw, default) if raw else default
            if limit <= 0:
                return view(request, *args, **kwargs)
            try:
                ok, retry = _allow(_client_ip(request), limit, window)
            except Exception:
                ok, retry = True, 0     # fail open — never block on a guard bug
            if not ok:
                resp = JsonResponse(
                    {'error': 'rate_limited',
                     'detail': 'تعداد درخواست‌ها زیاد است؛ کمی بعد دوباره تلاش کن.'},
                    status=429)
                resp['Retry-After'] = str(retry)
                return resp
            return view(request, *args, **kwargs)
        return wrapped
    return deco


# ---------------------------------------------------------------------------
# Admin gate — see admin_auth.py (env secret OR platform-admin session token)
# ---------------------------------------------------------------------------
from .admin_auth import require_admin_token  # noqa: F401 — re-exported for callers
