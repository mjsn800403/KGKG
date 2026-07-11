"""Observability: request metrics, system health, and intelligent alerting.

Three pieces, all dependency-free (matching the project's philosophy):

* ``RequestMetricsMiddleware`` — counts every request (per normalized endpoint
  group: count / 4xx / 5xx / latency) plus daily unique visitors, in memory,
  and flushes rollups to the DB in a background thread at most every
  ``FLUSH_INTERVAL`` seconds. Serving traffic therefore costs one dict update
  per request — no per-request DB writes, no external agent. Rollup rows grow
  with hours, not requests, so the analytics tables stay small at any volume.

* ``system_snapshot()`` — point-in-time health of the box and the app: disk,
  memory, load, service liveness signals (DB reachable, RAG index present),
  data-store sizes and the latest data-quality verdict.

* ``evaluate_alerts()`` — turns snapshots + rollups into de-duplicated
  ``SystemAlert`` rows with open/resolve lifecycle. Run from the
  ``check_alerts`` management command (cron/systemd timer) and surfaced in the
  admin panel; thresholds tunable via env.
"""
import hashlib
import os
import shutil
import sqlite3
import sys
import threading
import time

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

_START_TIME = time.time()

FLUSH_INTERVAL = float(os.environ.get('KG_METRICS_FLUSH_S', '30'))

# Under the test runner the periodic background flush must stay quiescent — a
# daemon thread writing to the shared in-memory test DB races the test
# transactions. Tests exercise flush_metrics() explicitly instead.
TESTING = 'test' in sys.argv

# ---------------------------------------------------------------------------
# Endpoint grouping — bounded cardinality no matter what URLs are requested.
# ---------------------------------------------------------------------------
_PREFIX_GROUPS = (
    ('/api/admin/', 'admin'),
    ('/api/assist/', 'assist'),
    ('/api/diagnose/', 'diagnose'),
    ('/api/search/', 'search'),
    ('/api/auth/', 'auth'),
    ('/api/team/', 'team'),
    ('/api/invite/', 'invite'),
    ('/api/activity/', 'activity'),
    ('/api/feedback/', 'feedback'),
    ('/api/purchase-request/', 'purchase'),
    ('/api/eval/', 'eval'),
    ('/api/health/', 'health'),
    ('/media/', 'media'),
    ('/admin/', 'django-admin'),
)


def endpoint_group(path):
    for prefix, group in _PREFIX_GROUPS:
        if path.startswith(prefix):
            return group
    if path == '/':
        return 'brands'
    # Everything else with 1-3 segments is the public/manual catalog tree
    # (/<brand>/, /<brand>/<year>/, /<brand>/<year>/<model>/).
    depth = len([s for s in path.split('/') if s])
    if depth <= 3:
        return 'catalog'
    return 'other'


def _ip_hash(request):
    """Salted, truncated hash of the client IP — enough to count uniques,
    impossible to reverse. Uses the same proxy-aware IP the rate limiter does."""
    from .ratelimit import _client_ip
    raw = f'{settings.SECRET_KEY[:16]}|{_client_ip(request)}'
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


# ---------------------------------------------------------------------------
# In-memory aggregation + periodic flush
# ---------------------------------------------------------------------------
_LOCK = threading.Lock()
_AGG = {}            # (hour_iso, endpoint, method) -> [requests, e4, e5, total_ms, max_ms]
_VISITORS = set()    # (day_iso, ip_hash)
_LAST_FLUSH = time.time()
_FLUSHING = False


def record_request(request, status, dur_ms):
    global _LAST_FLUSH, _FLUSHING
    now = timezone.now()
    key = (now.replace(minute=0, second=0, microsecond=0).isoformat(),
           endpoint_group(request.path),
           request.method[:8])
    with _LOCK:
        row = _AGG.setdefault(key, [0, 0, 0, 0, 0])
        row[0] += 1
        if 400 <= status < 500:
            row[1] += 1
        elif status >= 500:
            row[2] += 1
        row[3] += int(dur_ms)
        row[4] = max(row[4], int(dur_ms))
        if len(_VISITORS) < 200_000:      # hard memory bound
            _VISITORS.add((now.date().isoformat(), _ip_hash(request)))
        due = (not TESTING and (time.time() - _LAST_FLUSH) >= FLUSH_INTERVAL
               and not _FLUSHING)
        if due:
            _FLUSHING = True
            _LAST_FLUSH = time.time()
    if due:
        threading.Thread(target=_flush_worker, name='kg-metrics-flush',
                         daemon=True).start()


def _flush_worker():
    global _FLUSHING
    try:
        flush_metrics()
    finally:
        _FLUSHING = False
        close_old_connections()


def flush_metrics():
    """Push the in-memory aggregates into TrafficStat / VisitorSeen."""
    from django.db import transaction
    from .models import TrafficStat, VisitorSeen

    with _LOCK:
        agg, visitors = dict(_AGG), set(_VISITORS)
        _AGG.clear()
        _VISITORS.clear()
    if not agg and not visitors:
        return

    with transaction.atomic():
        for (bucket_iso, endpoint, method), (n, e4, e5, total, mx) in agg.items():
            obj, created = TrafficStat.objects.get_or_create(
                bucket=bucket_iso, endpoint=endpoint, method=method,
                defaults={'requests': n, 'errors_4xx': e4, 'errors_5xx': e5,
                          'total_ms': total, 'max_ms': mx})
            if not created:
                obj.requests += n
                obj.errors_4xx += e4
                obj.errors_5xx += e5
                obj.total_ms += total
                obj.max_ms = max(obj.max_ms, mx)
                obj.save(update_fields=['requests', 'errors_4xx', 'errors_5xx',
                                        'total_ms', 'max_ms'])
        VisitorSeen.objects.bulk_create(
            [VisitorSeen(day=d, ip_hash=h) for d, h in visitors],
            ignore_conflicts=True)


class RequestMetricsMiddleware:
    """Times every request and feeds the in-memory aggregator. Never raises —
    a metrics bug must not take down serving."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        t0 = time.perf_counter()
        response = self.get_response(request)
        try:
            record_request(request, response.status_code,
                           (time.perf_counter() - t0) * 1000)
        except Exception:
            pass
        return response


# ---------------------------------------------------------------------------
# System health snapshot
# ---------------------------------------------------------------------------

def _dir_size_mb(path):
    total = 0
    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    if e.is_file():
                        total += e.stat().st_size
                    elif e.is_dir():
                        total += _dir_size_mb(e.path) * 1e6
                except OSError:
                    pass
    except OSError:
        return 0.0
    return round(total / 1e6, 1)


def _meminfo():
    try:
        info = {}
        with open('/proc/meminfo') as f:
            for line in f:
                k, v = line.split(':', 1)
                info[k] = int(v.strip().split()[0])   # kB
        total = info.get('MemTotal', 0)
        avail = info.get('MemAvailable', 0)
        return {'total_mb': total // 1024, 'available_mb': avail // 1024,
                'used_pct': round(100 * (1 - avail / total), 1) if total else None}
    except (OSError, ValueError):
        return {'total_mb': None, 'available_mb': None, 'used_pct': None}


def system_snapshot(deep=False):
    """Point-in-time operational picture (admin system panel + alerting)."""
    from .rag import config
    from .models import Car, DataQualityRun, PortalUser, SystemAlert

    base = settings.BASE_DIR
    du = shutil.disk_usage(str(base))
    snap = {
        'time': timezone.now().isoformat(),
        'uptime_s': int(time.time() - _START_TIME),
        'disk': {'total_gb': round(du.total / 1e9, 1),
                 'free_gb': round(du.free / 1e9, 1),
                 'used_pct': round(100 * du.used / du.total, 1)},
        'memory': _meminfo(),
        'load_avg': list(os.getloadavg()) if hasattr(os, 'getloadavg') else None,
        'cpu_count': os.cpu_count(),
    }

    # App-level liveness.
    try:
        snap['catalog_cars'] = Car.objects.count()
        snap['portal_users'] = PortalUser.objects.count()
        snap['db_ok'] = True
    except Exception as e:
        snap['db_ok'] = False
        snap['db_error'] = str(e)

    snap['rag_index'] = {
        'present': config.INDEX_DB.exists(),
        'size_mb': round(config.INDEX_DB.stat().st_size / 1e6, 1)
        if config.INDEX_DB.exists() else 0,
    }
    try:
        main_db = settings.DATABASES['default']['NAME']
        snap['main_db_mb'] = round(os.path.getsize(main_db) / 1e6, 1)
    except OSError:
        snap['main_db_mb'] = None

    latest = DataQualityRun.objects.filter(status='done').first()
    snap['data_quality'] = ({
        'run_at': latest.finished_at.isoformat() if latest.finished_at else None,
        'complete': latest.summary.get('complete'),
        'incomplete': latest.summary.get('incomplete'),
        'corrupt': latest.summary.get('corrupt'),
        'duplicates': len(latest.summary.get('duplicates') or []),
    } if latest else None)

    snap['open_alerts'] = SystemAlert.objects.filter(is_open=True).count()

    if deep:
        snap['warehouse_mb'] = _dir_size_mb(str(config.WAREHOUSE_DIR))
        snap['media_mb'] = _dir_size_mb(str(settings.MEDIA_ROOT))
    return snap


# ---------------------------------------------------------------------------
# Alerting
# ---------------------------------------------------------------------------
# Thresholds (env-tunable so ops can adjust without a deploy).
DISK_WARN_PCT = float(os.environ.get('KG_ALERT_DISK_WARN', '85'))
DISK_CRIT_PCT = float(os.environ.get('KG_ALERT_DISK_CRIT', '93'))
MEM_WARN_PCT = float(os.environ.get('KG_ALERT_MEM_WARN', '92'))
ERR_RATE_WARN = float(os.environ.get('KG_ALERT_ERR_RATE', '0.05'))
ERR_MIN_REQUESTS = int(os.environ.get('KG_ALERT_ERR_MIN_N', '50'))
LATENCY_WARN_MS = float(os.environ.get('KG_ALERT_LATENCY_MS', '5000'))


def _raise_alert(key, severity, message, context=None):
    from .models import SystemAlert
    alert = SystemAlert.objects.filter(key=key, is_open=True).first()
    if alert:
        alert.severity = severity
        alert.message = message
        alert.context = context or {}
        alert.save(update_fields=['severity', 'message', 'context', 'last_seen'])
    else:
        SystemAlert.objects.create(key=key, severity=severity,
                                   message=message, context=context or {})
    return key


def evaluate_alerts():
    """Evaluate every alert condition; open new alerts, auto-resolve cleared
    ones. Returns {'open': [...keys], 'resolved': [...keys]}."""
    from django.db.models import Sum, Max
    from .models import SystemAlert, TrafficStat

    snap = system_snapshot()
    firing = {}

    disk_pct = snap['disk']['used_pct']
    if disk_pct >= DISK_CRIT_PCT:
        firing['disk_high'] = ('critical',
                               f'دیسک سرور {disk_pct}% پر است (بحرانی).',
                               {'used_pct': disk_pct})
    elif disk_pct >= DISK_WARN_PCT:
        firing['disk_high'] = ('warning',
                               f'دیسک سرور {disk_pct}% پر است.',
                               {'used_pct': disk_pct})

    mem_pct = snap['memory'].get('used_pct')
    if mem_pct is not None and mem_pct >= MEM_WARN_PCT:
        firing['memory_high'] = ('warning',
                                 f'مصرف حافظه {mem_pct}% است.',
                                 {'used_pct': mem_pct})

    if not snap.get('db_ok'):
        firing['db_down'] = ('critical', 'پایگاه‌داده اصلی در دسترس نیست.',
                             {'error': snap.get('db_error', '')})

    if not snap['rag_index']['present']:
        firing['rag_index_missing'] = (
            'warning', 'ایندکس معنایی (RAG) روی دیسک نیست — جستجو و دستیار هوشمند از کار می‌افتد.', {})

    # Per-endpoint error rate + latency over the last hour of rollups.
    since = timezone.now() - timezone.timedelta(hours=1)
    rows = (TrafficStat.objects.filter(bucket__gte=since)
            .values('endpoint')
            .annotate(n=Sum('requests'), e5=Sum('errors_5xx'),
                      total=Sum('total_ms'), mx=Max('max_ms')))
    for r in rows:
        n = r['n'] or 0
        if n >= ERR_MIN_REQUESTS and (r['e5'] or 0) / n >= ERR_RATE_WARN:
            firing[f"error_rate:{r['endpoint']}"] = (
                'critical',
                f"نرخ خطای ۵xx در «{r['endpoint']}» به {round(100 * r['e5'] / n, 1)}% رسیده است.",
                {'requests': n, 'errors_5xx': r['e5']})
        if n >= 10 and (r['total'] or 0) / n >= LATENCY_WARN_MS:
            firing[f"latency:{r['endpoint']}"] = (
                'warning',
                f"میانگین تاخیر «{r['endpoint']}» {round((r['total'] or 0) / n)}ms است.",
                {'avg_ms': round((r['total'] or 0) / n), 'max_ms': r['mx']})

    # Data-quality regressions (from the latest audit).
    dq = snap.get('data_quality')
    if dq:
        if (dq.get('corrupt') or 0) > 0:
            firing['dq_corrupt'] = ('warning',
                                    f"{dq['corrupt']} فایل خودرو خراب در انبار داده وجود دارد.", dq)
        if (dq.get('duplicates') or 0) > 0:
            firing['dq_duplicates'] = ('warning',
                                       f"{dq['duplicates']} خودروی تکراری شناسایی شده است.", dq)

    opened = [_raise_alert(k, sev, msg, ctx) for k, (sev, msg, ctx) in firing.items()]

    # Auto-resolve ONLY the alert keys this evaluator owns. Other subsystems
    # (e.g. the processing pipeline) manage their own alerts' lifecycles —
    # closing them here just because this function didn't raise them would
    # hide real conditions.
    OWNED_KEYS = ('disk_high', 'memory_high', 'db_down', 'rag_index_missing')
    OWNED_PREFIXES = ('error_rate:', 'latency:', 'dq_')
    resolved = []
    for alert in SystemAlert.objects.filter(is_open=True):
        owned = alert.key in OWNED_KEYS or alert.key.startswith(OWNED_PREFIXES)
        if owned and alert.key not in firing:
            alert.is_open = False
            alert.resolved_at = timezone.now()
            alert.save(update_fields=['is_open', 'resolved_at'])
            resolved.append(alert.key)

    return {'open': opened, 'resolved': resolved}


def prune_old_data(days=90):
    """Retention: drop rollups/visitor rows/closed alerts older than ``days``.
    Keeps the observability tables O(bounded) forever."""
    from .models import SystemAlert, TrafficStat, VisitorSeen
    cutoff = timezone.now() - timezone.timedelta(days=days)
    a = TrafficStat.objects.filter(bucket__lt=cutoff).delete()[0]
    b = VisitorSeen.objects.filter(day__lt=cutoff.date()).delete()[0]
    c = SystemAlert.objects.filter(is_open=False, last_seen__lt=cutoff).delete()[0]
    return {'traffic_rows': a, 'visitor_rows': b, 'alerts': c}
