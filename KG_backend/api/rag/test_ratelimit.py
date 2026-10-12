"""Tests for the request guards (api.ratelimit): sliding-window rate limiter
and the shared-secret admin gate. Pure logic — no DB, no index needed.

Run: DJANGO_SETTINGS_MODULE=KG_backend.settings pytest api/rag/test_ratelimit.py
"""
from django.conf import settings
from django.http import JsonResponse

from api.ratelimit import _allow, rate_limited, require_admin_token


class _Req:
    def __init__(self, meta=None, method='POST'):
        self.META = meta or {'REMOTE_ADDR': '203.0.113.1'}
        self.method = method


# --- sliding window core ----------------------------------------------------
def test_allow_under_limit_then_blocks():
    ip = 'win-1'
    assert _allow(ip, 3, 60)[0] is True
    assert _allow(ip, 3, 60)[0] is True
    assert _allow(ip, 3, 60)[0] is True
    ok, retry = _allow(ip, 3, 60)
    assert ok is False
    assert retry >= 1            # caller is told when to retry


def test_allow_is_per_ip():
    assert _allow('win-a', 1, 60)[0] is True
    assert _allow('win-a', 1, 60)[0] is False
    assert _allow('win-b', 1, 60)[0] is True     # different IP, own bucket


# --- decorator --------------------------------------------------------------
def test_rate_limited_returns_429(monkeypatch):
    monkeypatch.delenv('KG_RL_DISABLE', raising=False)
    monkeypatch.delenv('KG_RL_UNIT', raising=False)

    @rate_limited('unit', 2, 60)
    def view(request):
        return JsonResponse({'ok': True})

    req = lambda: _Req({'REMOTE_ADDR': '198.51.100.7'})
    assert view(req()).status_code == 200
    assert view(req()).status_code == 200
    blocked = view(req())
    assert blocked.status_code == 429
    assert blocked['Retry-After']


def test_rate_limit_disabled(monkeypatch):
    monkeypatch.setenv('KG_RL_DISABLE', '1')

    @rate_limited('unit2', 1, 60)
    def view(request):
        return JsonResponse({'ok': True})

    req = lambda: _Req({'REMOTE_ADDR': '198.51.100.8'})
    assert view(req()).status_code == 200
    assert view(req()).status_code == 200     # still allowed — guard disabled


def test_rate_limit_env_override(monkeypatch):
    monkeypatch.delenv('KG_RL_DISABLE', raising=False)
    monkeypatch.setenv('KG_RL_UNIT3', '1/60')   # override the 5 in code to 1

    @rate_limited('unit3', 5, 60)
    def view(request):
        return JsonResponse({'ok': True})

    req = lambda: _Req({'REMOTE_ADDR': '198.51.100.9'})
    assert view(req()).status_code == 200
    assert view(req()).status_code == 429


# --- admin gate -------------------------------------------------------------
def test_admin_allows_in_debug_without_token(monkeypatch):
    monkeypatch.delenv('KG_ADMIN_TOKEN', raising=False)
    monkeypatch.setattr(settings, 'DEBUG', True, raising=False)

    @require_admin_token
    def view(request):
        return JsonResponse({'ok': True})

    assert view(_Req()).status_code == 200


def test_admin_denies_unconfigured_in_prod(monkeypatch):
    monkeypatch.delenv('KG_ADMIN_TOKEN', raising=False)
    monkeypatch.setattr(settings, 'DEBUG', False, raising=False)

    @require_admin_token
    def view(request):
        return JsonResponse({'ok': True})

    assert view(_Req()).status_code == 503      # fail closed


def test_admin_checks_token(monkeypatch):
    monkeypatch.setenv('KG_ADMIN_TOKEN', 'secret123')
    monkeypatch.setattr(settings, 'DEBUG', False, raising=False)

    @require_admin_token
    def view(request):
        return JsonResponse({'ok': True})

    bearer = _Req({'REMOTE_ADDR': '1', 'HTTP_AUTHORIZATION': 'Bearer secret123'})
    header = _Req({'REMOTE_ADDR': '1', 'HTTP_X_ADMIN_TOKEN': 'secret123'})
    wrong = _Req({'REMOTE_ADDR': '1', 'HTTP_AUTHORIZATION': 'Bearer nope'})
    assert view(bearer).status_code == 200
    assert view(header).status_code == 200
    assert view(wrong).status_code == 401
    assert view(_Req()).status_code == 401      # no token presented
