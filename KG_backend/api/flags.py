"""Feature flags and A/B experiments.

A ``FeatureFlag`` splits signed-in users into two arms. A user is in the "on"
arm when the flag is enabled and a stable hash of (flag key, user id) falls
under ``rollout_pct``, so the same person always lands in the same arm and arms
of different flags are independent. ``force_on`` / ``force_off`` pin individual
user ids (staff testing, a customer who must not see an experiment).

The chat route reads the user's arms from ``GET /api/auth/ai-usage/`` (one
round trip it already makes), stores them on every ``ChatLog`` row, and the
results endpoint compares the arms on the behaviour signals ChatLog already
carries (grounded, degraded, 👍/👎, rephrase, copy, latency, cost).

GET  /api/auth/flags/                       — the signed-in user's arms
GET  /api/admin/flags/                      — every flag + arm sizes
POST /api/admin/flags/  {key, description?, enabled?, rollout_pct?,
                         force_on?, force_off?, delete?}  — create/update/delete
GET  /api/admin/flags/<key>/results/?days=30[&exclude_companies=1,8]
"""
import hashlib
import math
import re
from datetime import timedelta

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .admin_auth import require_admin_token
from .models import ChatLog, FeatureFlag, PortalUser

KEY_RE = re.compile(r'^[a-z][a-z0-9_]{1,59}$')


def bucket(key, user_id):
    """0..99, stable for a (flag, user) pair."""
    h = hashlib.sha256(f'{key}:{user_id}'.encode()).hexdigest()
    return int(h[:8], 16) % 100


def arm(flag, user_id):
    """True when ``user_id`` is in the flag's "on" arm."""
    if user_id in (flag.force_off or []):
        return False
    if user_id in (flag.force_on or []):
        return True
    if not flag.enabled:
        return False
    return bucket(flag.key, user_id) < max(0, min(100, flag.rollout_pct))


def flags_for(user):
    """{key: bool} for every defined flag (a missing key means "not defined")."""
    if not user:
        return {}
    return {f.key: arm(f, user.id) for f in FeatureFlag.objects.all()}


def clean_flags(raw):
    """A client-reported {key: bool} map, bounded, for storing on ChatLog."""
    if not isinstance(raw, dict):
        return {}
    out = {}
    for k, v in list(raw.items())[:20]:
        if isinstance(k, str) and KEY_RE.match(k):
            out[k] = bool(v)
    return out


def flags_view(request):
    from .portal import portal_user
    user = portal_user(request)
    if not user:
        return JsonResponse({'error': 'unauthorized'}, status=401)
    return JsonResponse({'flags': flags_for(user)})


def _flag_dict(f, users=None):
    d = {'key': f.key, 'description': f.description, 'enabled': f.enabled,
         'rollout_pct': f.rollout_pct, 'force_on': f.force_on, 'force_off': f.force_off,
         'updated_at': f.updated_at.isoformat() if f.updated_at else None}
    if users is not None:
        on = sum(1 for uid in users if arm(f, uid))
        d['arm_sizes'] = {'on': on, 'off': len(users) - on}
    return d


def _int_list(v):
    if not isinstance(v, list):
        return None
    try:
        return sorted({int(x) for x in v})[:500]
    except (TypeError, ValueError):
        return None


@csrf_exempt
@require_admin_token
def admin_flags_view(request):
    if request.method == 'POST':
        from .views import _post_body
        b = _post_body(request)
        key = str(b.get('key') or '').strip()
        if not KEY_RE.match(key):
            return JsonResponse({'error': 'کلید باید با حرف کوچک انگلیسی شروع شود و فقط a-z، 0-9 و _ داشته باشد.'},
                                status=400)
        if b.get('delete'):
            FeatureFlag.objects.filter(key=key).delete()
            return JsonResponse({'ok': True, 'deleted': key})
        flag, _ = FeatureFlag.objects.get_or_create(key=key)
        if 'description' in b:
            flag.description = str(b.get('description') or '')[:300]
        if 'enabled' in b:
            flag.enabled = bool(b.get('enabled'))
        if 'rollout_pct' in b:
            try:
                pct = int(b.get('rollout_pct'))
            except (TypeError, ValueError):
                return JsonResponse({'error': 'درصد باید عدد صحیح ۰ تا ۱۰۰ باشد.'}, status=400)
            if not 0 <= pct <= 100:
                return JsonResponse({'error': 'درصد باید عدد صحیح ۰ تا ۱۰۰ باشد.'}, status=400)
            flag.rollout_pct = pct
        for field in ('force_on', 'force_off'):
            if field in b:
                ids = _int_list(b.get(field))
                if ids is None:
                    return JsonResponse({'error': f'{field} باید فهرست شناسهٔ کاربر باشد.'}, status=400)
                setattr(flag, field, ids)
        flag.save()
        return JsonResponse({'ok': True, 'flag': _flag_dict(flag)})
    users = list(PortalUser.objects.filter(active=True).values_list('id', flat=True))
    return JsonResponse({'flags': [_flag_dict(f, users) for f in FeatureFlag.objects.order_by('key')]})


def _two_prop_p(x1, n1, x2, n2):
    """Two-sided p-value of a two-proportion z-test; None if not computable."""
    if min(n1, n2) == 0:
        return None
    p = (x1 + x2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    if se == 0:
        return None
    z = (x1 / n1 - x2 / n2) / se
    return math.erfc(abs(z) / math.sqrt(2))


def _arm_stats(rows):
    n = len(rows)
    rated = [r for r in rows if r['feedback'] in (1, -1)]
    lat = sorted(r['latency_ms'] for r in rows if r['latency_ms'] is not None)
    cost = [r['llm_cost'] for r in rows if r['llm_cost'] is not None]
    count = lambda pred: sum(1 for r in rows if pred(r))  # noqa: E731
    return {
        'answers': n,
        'users': len({r['user_id'] for r in rows}),
        'grounded': count(lambda r: r['grounded']),
        'degraded': count(lambda r: r['degraded']),
        'rephrased': count(lambda r: r['rephrased']),
        'copied': count(lambda r: r['copied']),
        'with_source_click': count(lambda r: (r['source_clicks'] or 0) > 0),
        'up': count(lambda r: r['feedback'] == 1),
        'down': count(lambda r: r['feedback'] == -1),
        'rated': len(rated),
        'p50_latency_ms': lat[len(lat) // 2] if lat else None,
        'avg_cost': (sum(cost) / len(cost)) if cost else None,
    }


@require_admin_token
def admin_flag_results_view(request, key):
    try:
        days = max(1, min(int(request.GET.get('days') or 30), 365))
    except ValueError:
        days = 30
    since = timezone.now() - timedelta(days=days)
    qs = ChatLog.objects.filter(created_at__gte=since).exclude(mode='backfill')
    excl = [int(x) for x in re.findall(r'\d+', request.GET.get('exclude_companies') or '')]
    if excl:
        qs = qs.exclude(company_id__in=excl)
    rows = list(qs.values('user_id', 'flags', 'grounded', 'degraded', 'rephrased', 'copied',
                          'source_clicks', 'feedback', 'latency_ms', 'llm_cost'))
    on = [r for r in rows if (r['flags'] or {}).get(key) is True]
    off = [r for r in rows if (r['flags'] or {}).get(key) is False]
    a, b = _arm_stats(on), _arm_stats(off)
    tests = {}
    for metric, denom in (('grounded', 'answers'), ('degraded', 'answers'),
                          ('rephrased', 'answers'), ('copied', 'answers'),
                          ('with_source_click', 'answers'), ('up', 'rated')):
        tests[metric] = {
            'on_rate': (a[metric] / a[denom]) if a[denom] else None,
            'off_rate': (b[metric] / b[denom]) if b[denom] else None,
            'p_value': _two_prop_p(a[metric], a[denom], b[metric], b[denom]),
        }
    flag = FeatureFlag.objects.filter(key=key).first()
    return JsonResponse({
        'key': key, 'days': days, 'flag': _flag_dict(flag) if flag else None,
        'arms': {'on': a, 'off': b}, 'tests': tests,
        'untagged_answers': len(rows) - len(on) - len(off),
        # Rule of thumb for the UI: below ~100 answers per arm a p-value means little.
        'enough_data': min(a['answers'], b['answers']) >= 100,
    })
