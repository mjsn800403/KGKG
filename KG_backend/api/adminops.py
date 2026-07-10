"""Operational admin API: data quality, system health, traffic analytics.

Everything here is read-mostly and served from persisted rollups / audit runs,
so the admin panel stays instant regardless of warehouse size or traffic.
"""
import json

from django.db.models import Count, Max, Sum
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .admin_auth import require_admin_token
from .models import (
    ActivityLog, Car, DataQualityRun, SystemAlert, TrafficStat, VisitorSeen,
)
from . import dataquality, monitoring


# ---------------------------------------------------------------------------
# Public liveness probe (load balancers / uptime monitors; no secrets, cheap)
# ---------------------------------------------------------------------------

def health_view(request):
    """GET /api/health/ -> {ok, db, rag_index, uptime_s}"""
    import time
    ok = True
    db_ok = True
    try:
        Car.objects.exists()
    except Exception:
        ok = db_ok = False
    from .rag import config
    return JsonResponse({
        'ok': ok,
        'db': db_ok,
        'rag_index': config.INDEX_DB.exists(),
        'uptime_s': int(time.time() - monitoring._START_TIME),
    }, status=200 if ok else 503)


# ---------------------------------------------------------------------------
# Data quality
# ---------------------------------------------------------------------------

@csrf_exempt
@require_admin_token
def admin_data_quality_view(request):
    """GET  /api/admin/data-quality/          -> latest audit report
       POST /api/admin/data-quality/ {refresh: true, fix?: false}
            -> start a background re-scan (returns {started})
    """
    if request.method == 'POST':
        try:
            body = json.loads(request.body or '{}')
        except (ValueError, TypeError):
            body = {}
        if body.get('refresh'):
            started = dataquality.run_audit_async(fix=bool(body.get('fix')))
            return JsonResponse({'started': started,
                                 'detail': '' if started else 'an audit is already running'})
        return JsonResponse({'error': 'unknown action'}, status=400)

    latest = DataQualityRun.objects.exclude(status='running').first()
    running = DataQualityRun.objects.filter(status='running').first()
    if latest is None and running is None:
        return JsonResponse({'report': None, 'running': False,
                             'detail': 'no audit has been run yet'})
    return JsonResponse({
        'running': running is not None,
        'report': None if latest is None else {
            'status': latest.status,
            'started_at': latest.started_at.isoformat(),
            'finished_at': latest.finished_at.isoformat() if latest.finished_at else None,
            'summary': latest.summary,
            'vehicles': latest.vehicles,
            'actions': latest.actions,
            'error': latest.error,
        },
    })


# ---------------------------------------------------------------------------
# System health + alerts
# ---------------------------------------------------------------------------

@csrf_exempt
@require_admin_token
def admin_system_view(request):
    """GET /api/admin/system/ -> live snapshot + open alerts + recent resolved.
       POST {action: 'check_alerts'} -> evaluate alert conditions now."""
    if request.method == 'POST':
        try:
            body = json.loads(request.body or '{}')
        except (ValueError, TypeError):
            body = {}
        if body.get('action') == 'check_alerts':
            result = monitoring.evaluate_alerts()
            return JsonResponse({'ok': True, **result})
        return JsonResponse({'error': 'unknown action'}, status=400)

    def _alert(a):
        return {'id': a.id, 'key': a.key, 'severity': a.severity,
                'message': a.message, 'context': a.context,
                'is_open': a.is_open,
                'first_seen': a.first_seen.isoformat(),
                'last_seen': a.last_seen.isoformat(),
                'resolved_at': a.resolved_at.isoformat() if a.resolved_at else None}

    return JsonResponse({
        'snapshot': monitoring.system_snapshot(),
        'alerts_open': [_alert(a) for a in
                        SystemAlert.objects.filter(is_open=True)[:50]],
        'alerts_recent': [_alert(a) for a in
                          SystemAlert.objects.filter(is_open=False)[:20]],
    })


# ---------------------------------------------------------------------------
# Traffic / visitor analytics
# ---------------------------------------------------------------------------

@require_admin_token
def admin_traffic_view(request):
    """GET /api/admin/traffic/?range=7 — website usage from the metric rollups:
    daily requests + unique visitors, per-endpoint volumes / latency / errors,
    and feature-usage counts (portal activity actions)."""
    try:
        days = max(1, min(int(request.GET.get('range', 7) or 7), 90))
    except (TypeError, ValueError):
        days = 7
    since = timezone.now() - timezone.timedelta(days=days)

    # Force any in-memory aggregates out so "today" is fresh.
    try:
        monitoring.flush_metrics()
    except Exception:
        pass

    stats = TrafficStat.objects.filter(bucket__gte=since)

    daily = {}
    for row in (stats.values('bucket__date')
                .annotate(n=Sum('requests'), e4=Sum('errors_4xx'), e5=Sum('errors_5xx'))):
        daily[row['bucket__date'].isoformat()] = {
            'requests': row['n'], 'errors_4xx': row['e4'], 'errors_5xx': row['e5'],
            'unique_visitors': 0}
    for row in (VisitorSeen.objects.filter(day__gte=since.date())
                .values('day').annotate(n=Count('id'))):
        daily.setdefault(row['day'].isoformat(), {
            'requests': 0, 'errors_4xx': 0, 'errors_5xx': 0, 'unique_visitors': 0,
        })['unique_visitors'] = row['n']
    series = [{'date': d, **v} for d, v in sorted(daily.items())]

    endpoints = []
    for row in (stats.values('endpoint')
                .annotate(n=Sum('requests'), e4=Sum('errors_4xx'), e5=Sum('errors_5xx'),
                          total=Sum('total_ms'), mx=Max('max_ms'))
                .order_by('-n')):
        n = row['n'] or 0
        endpoints.append({
            'endpoint': row['endpoint'], 'requests': n,
            'errors_4xx': row['e4'], 'errors_5xx': row['e5'],
            'avg_ms': round((row['total'] or 0) / n) if n else 0,
            'max_ms': row['mx'],
        })

    # Feature usage from portal activity (logged-in feature events).
    feature_usage = {row['action']: row['n'] for row in
                     ActivityLog.objects.filter(created_at__gte=since)
                     .values('action').annotate(n=Count('id')).order_by('-n')}

    totals = stats.aggregate(n=Sum('requests'), e4=Sum('errors_4xx'),
                             e5=Sum('errors_5xx'), total=Sum('total_ms'))
    n_total = totals['n'] or 0
    return JsonResponse({
        'range_days': days,
        'totals': {
            'requests': n_total,
            'errors_4xx': totals['e4'] or 0,
            'errors_5xx': totals['e5'] or 0,
            'avg_ms': round((totals['total'] or 0) / n_total) if n_total else 0,
            'unique_visitors': VisitorSeen.objects.filter(
                day__gte=since.date()).values('ip_hash').distinct().count(),
        },
        'series': series,
        'endpoints': endpoints,
        'feature_usage': feature_usage,
    })
