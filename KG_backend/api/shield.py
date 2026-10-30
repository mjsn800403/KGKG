"""Content shield: encrypted document payloads + signed, single-use requests.

A signed-in session could otherwise be scripted to pull every content API as
plain JSON. With the shield on (KG_SHIELD=1 and KG_SHIELD_SECRET set):

  * Keys are per session and rotate every EPOCH seconds:
      enc = HMAC(secret, "enc|<sha256(token)>|<epoch>")   AES-256-GCM key
      sig = HMAC(secret, "sig|<sha256(token)>|<epoch>")   HMAC-SHA256 key
    The browser gets them from /api/shield/key/ (session cookie auth); the
    Next.js server derives the same keys itself to seal SSR content
    (utils/shieldServer.js), so the two must share KG_SHIELD_SECRET.
  * Browser calls to the content APIs must carry X-KG-E / X-KG-N / X-KG-S:
    HMAC(sig, "METHOD\\npath\\nquery\\nepoch\\nnonce"), epoch current or the
    previous one, nonce never seen before. Anything else gets 403 shield.
  * Their JSON answers are sealed: {"_kg":1,"e":epoch,"iv":..,"ct":..}.

Only requests that came through nginx (X-Real-IP set) are shielded. Server-side
callers on loopback -- SSR, the assistant's /api/chat route, the RAG retriever
-- hit Django directly and are unaffected. This is obfuscation, not DRM: a
determined user can still drive a real browser; contentguard caps that.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import time

from django.http import JsonResponse

EPOCH = 600
AAD = b'kg1'
_PROTECTED = re.compile(
    r'^/(api/(parts|frm|search)/|(?!api/|admin/|media/|static/|health)[^/]+/[^/]+/[^/]+/)')
_BAD_WARN = 30          # bad signatures per user per hour before an alert


def secret():
    return os.environ.get('KG_SHIELD_SECRET', '')


def enabled():
    return os.environ.get('KG_SHIELD', '0') == '1' and bool(secret())


def epoch(now=None):
    return int((now if now is not None else time.time()) // EPOCH)


def _b64(b):
    return base64.b64encode(b).decode()


def keys(raw_token, e):
    th = hashlib.sha256(raw_token.encode()).hexdigest()
    s = secret().encode()
    return (hmac.new(s, f'enc|{th}|{e}'.encode(), hashlib.sha256).digest(),
            hmac.new(s, f'sig|{th}|{e}'.encode(), hashlib.sha256).digest())


def seal(obj, raw_token, e=None):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    e = epoch() if e is None else e
    iv = os.urandom(12)
    ct = AESGCM(keys(raw_token, e)[0]).encrypt(iv, json.dumps(obj, ensure_ascii=False).encode(), AAD)
    return {'_kg': 1, 'e': e, 'iv': _b64(iv), 'ct': _b64(ct)}


def unseal(blob, raw_token):
    """Test/debug helper: the inverse of seal()."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    pt = AESGCM(keys(raw_token, blob['e'])[0]).decrypt(
        base64.b64decode(blob['iv']), base64.b64decode(blob['ct']), AAD)
    return json.loads(pt)


def signature(raw_token, e, method, path, query, nonce):
    msg = f'{method}\n{path}\n{query}\n{e}\n{nonce}'.encode()
    return _b64(hmac.new(keys(raw_token, e)[1], msg, hashlib.sha256).digest())


def _token(request):
    from .portal import _portal_token
    return _portal_token(request) or ''


def key_view(request):
    """GET /api/shield/key/[?e=<epoch>] -> this session's keys for an epoch.

    Default is the current epoch (signing). An older `e` (up to 2 back) is
    allowed so a page sealed a few minutes ago can still be opened."""
    if not enabled():
        return JsonResponse({'on': False})
    from .portal import portal_user
    raw = _token(request)
    if not raw or not portal_user(request):
        return JsonResponse({'error': 'unauthorized'}, status=401)
    now = time.time()
    cur = epoch(now)
    try:
        e = int(request.GET.get('e', cur))
    except ValueError:
        e = cur
    if not cur - 2 <= e <= cur:
        return JsonResponse({'error': 'epoch'}, status=400)
    enc, sig = keys(raw, e)
    # Whole seconds left in this epoch, never 0. `int(EPOCH - now % EPOCH)`
    # truncated a float: in the last second of every epoch the subtraction
    # lands below 1 and the client was told its key had already expired, once
    # per 600 calls on average. Doing the modulo on int(now) keeps the whole
    # expression in integers, so the result is 1..EPOCH by construction.
    resp = JsonResponse({'on': True, 'e': e, 'enc': _b64(enc), 'sig': _b64(sig),
                         'ttl': EPOCH - int(now) % EPOCH})
    resp['Cache-Control'] = 'no-store'
    return resp


def _bad(request, why):
    try:
        from . import contentguard
        from .portal import portal_user
        user = portal_user(request)
        if user:
            n = contentguard._count_and_add(f'sh:bad:{user.id}') + 1
            if n == _BAD_WARN:
                from . import monitoring
                monitoring._raise_alert(
                    f'sec:shield:{user.id}', 'warning',
                    f'درخواست‌های امضانشده به API مستندات: کاربر {user.username} {n} بار در یک ساعت',
                    {'user_id': user.id, 'username': user.username, 'why': why})
    except Exception:
        pass
    return JsonResponse({'error': 'shield', 'why': why}, status=403)


def verify(request, raw, now=None):
    """None if the request is correctly signed, else the reason string."""
    try:
        e = int(request.headers.get('X-KG-E', ''))
    except ValueError:
        return 'missing'
    nonce = request.headers.get('X-KG-N', '')
    sig = request.headers.get('X-KG-S', '')
    if not sig or not re.fullmatch(r'[A-Za-z0-9_-]{16,64}', nonce):
        return 'missing'
    cur = epoch(now)
    if e not in (cur, cur - 1):
        return 'expired'
    want = signature(raw, e, request.method, request.path, request.META.get('QUERY_STRING', ''), nonce)
    if not hmac.compare_digest(want, sig):
        return 'signature'
    from . import contentguard
    if contentguard._count_and_add(f'sn:{nonce}') > 0:
        return 'replay'
    return None


def shielded(request):
    return (enabled() and request.META.get('HTTP_X_REAL_IP')
            and request.method == 'GET' and _PROTECTED.match(request.path))


class ShieldMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        raw = ''
        try:
            if shielded(request):
                raw = _token(request)
        except Exception:      # fail-open, like contentguard
            raw = ''
        if not raw:            # anonymous: the view itself answers 401
            return self.get_response(request)
        try:
            why = verify(request, raw)
        except Exception:
            why = None
        if why:
            return _bad(request, why)
        resp = self.get_response(request)
        if resp.status_code == 200 and resp.get('Content-Type', '').startswith('application/json') \
                and not getattr(resp, 'streaming', False):
            try:
                out = JsonResponse(seal(json.loads(resp.content), raw))
            except Exception:
                return resp
            out['Cache-Control'] = 'no-store'
            return out
        return resp
