import os
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
    ActivityLog, Car, DataQualityRun, DownloadRequest, PipelineSettings,
    ProcessingJob, SystemAlert, TrafficStat, VehicleSpec, VisitorSeen,
    ZipPackage,
)
from . import dataquality, monitoring, pipeline


def _json_body(request):
    """Parsed JSON body, always a dict (non-object JSON collapses to {})."""
    try:
        data = json.loads(request.body or '{}')
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


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
        body = _json_body(request)
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
        body = _json_body(request)
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


# ---------------------------------------------------------------------------
# Data-processing pipeline (admin-triggered background workflow)
# ---------------------------------------------------------------------------

_SOURCE_BASE = os.environ.get('KGTV_SOURCE_URL', 'https://source-manuals.example.com')


def _source_url(body):
    """Brand/Year page URL from {url} or {brand, year}. None when invalid.
    Only the upstream source host is accepted."""
    url = (body.get('url') or '').strip()
    if not url:
        brand = (body.get('brand') or '').strip()
        year = str(body.get('year') or '').strip()
        if not (brand and year.isdigit()):
            return None
        url = f'{_SOURCE_BASE}/{brand}/{year}/'
    if _SOURCE_BASE.split('//')[1].split('/')[0] not in url:
        return None
    return url


def _brand_year_from_url(url):
    from urllib.parse import unquote, urlparse
    parts = [unquote(p) for p in urlparse(url).path.strip('/').split('/') if p]
    brand = parts[0] if parts else ''
    year = None
    if len(parts) > 1 and parts[1].isdigit():
        year = int(parts[1])
    return brand, year


def _download_dict(r):
    return {'id': r.id, 'url': r.url, 'brand': r.brand, 'year': r.year,
            'name_filter': r.name_filter, 'status': r.status,
            'vehicles_total': r.vehicles_total, 'vehicles_done': r.vehicles_done,
            'listing': r.listing, 'error': r.error,
            'created_at': r.created_at.isoformat(),
            'finished_at': r.finished_at.isoformat() if r.finished_at else None}


def _zip_dict(p):
    return {'id': p.id, 'zip_name': p.zip_name, 'brand': p.brand,
            'year': p.year, 'car_name': p.car_name, 'stem': p.stem,
            'status': p.status, 'size_mb': round((p.size or 0) / 1048576, 1),
            'pages_processed': p.pages_processed, 'error': p.error,
            'updated_at': p.updated_at.isoformat()}


@csrf_exempt
@require_admin_token
def admin_pipeline_view(request):
    """GET  /api/admin/pipeline/ -> pending work + load + recommendation +
         active/last job (live progress) + history + settings.
       POST {action: start | schedule {at} | resume {job_id} | cancel {job_id}
             | settings {auto_enabled?, load_threshold?, auto_resume?}}
    """
    if request.method == 'POST':
        body = _json_body(request)
        action = body.get('action')

        if action == 'start':
            job, err = pipeline.start_job(trigger='manual')
            if err:
                return JsonResponse({'error': err}, status=409)
            _emit_pipeline('pipeline.started', job)
            return JsonResponse({'ok': True, 'job': pipeline.job_dict(job)})

        if action == 'schedule':
            raw = str(body.get('at') or '')
            try:
                at = timezone.datetime.fromisoformat(raw.replace('Z', '+00:00'))
                if timezone.is_naive(at):
                    at = timezone.make_aware(at)
            except (ValueError, TypeError):
                return JsonResponse({'error': 'زمان نامعتبر است.'}, status=400)
            if at <= timezone.now():
                job, err = pipeline.start_job(trigger='manual')
            else:
                job, err = pipeline.start_job(trigger='schedule', scheduled_for=at)
            if err:
                return JsonResponse({'error': err}, status=409)
            return JsonResponse({'ok': True, 'job': pipeline.job_dict(job)})

        if action in ('resume', 'cancel'):
            job = ProcessingJob.objects.filter(id=body.get('job_id')).first()
            if job is None:
                return JsonResponse({'error': 'کار یافت نشد.'}, status=404)
            ok, err = (pipeline.resume_job(job) if action == 'resume'
                       else pipeline.cancel_job(job))
            if not ok:
                return JsonResponse({'error': err}, status=409)
            job.refresh_from_db()
            _emit_pipeline('pipeline.resumed' if action == 'resume' else 'pipeline.canceled', job)
            return JsonResponse({'ok': True, 'job': pipeline.job_dict(job)})

        if action == 'settings':
            st = PipelineSettings.get()
            if 'auto_enabled' in body:
                st.auto_enabled = bool(body['auto_enabled'])
            if 'auto_resume' in body:
                st.auto_resume = bool(body['auto_resume'])
            if 'max_power' in body:
                st.max_power = bool(body['max_power'])
            if 'load_threshold' in body:
                try:
                    st.load_threshold = min(1.5, max(0.1, float(body['load_threshold'])))
                except (TypeError, ValueError):
                    pass
            st.save()
            return JsonResponse({'ok': True, 'plan': pipeline.power_plan(st.max_power)})

        if action == 'apply_power':
            # Restart the active job so the new CPU budget (max-power toggle)
            # takes effect now. No active job => the setting applies to the next
            # run. Parsing is incremental/resumable, so nothing is lost.
            import time as _time
            job = pipeline.active_job()
            if job is None:
                return JsonResponse({'ok': True, 'restarted': False,
                                     'detail': 'کار در حال اجرایی نیست؛ تنظیم برای اجرای بعدی اعمال می‌شود.'})
            ok, err = pipeline.cancel_job(job)
            if not ok:
                return JsonResponse({'error': err}, status=409)
            for _ in range(20):
                job.refresh_from_db()
                if job.status in ('paused', 'canceled', 'failed', 'done'):
                    break
                _time.sleep(0.5)
            ok2, err2 = pipeline.resume_job(job)
            if not ok2:
                return JsonResponse({'error': err2 or 'ازسرگیری ناموفق بود'}, status=409)
            job.refresh_from_db()
            _emit_pipeline('pipeline.resumed', job)
            return JsonResponse({'ok': True, 'restarted': True,
                                 'job': pipeline.job_dict(job)})

        if action == 'list_source':
            # Synchronous dry-run listing of an upstream Brand/Year page, annotated
            # with what we already have locally (downloaded / ingested).
            from . import ingest
            url = _source_url(body)
            if url is None:
                return JsonResponse({'error': 'آدرس منبع یا برند/سال لازم است.'}, status=400)
            try:
                listing = ingest.list_source(url, body.get('filter') or '')
            except Exception as e:
                return JsonResponse(
                    {'error': f'دریافت فهرست از منبع ممکن نشد: {e}'}, status=502)
            return JsonResponse({'ok': True, **listing})

        if action == 'download':
            # Queue a DownloadRequest; the pipeline's download stage executes it.
            url = _source_url(body)
            if url is None:
                return JsonResponse({'error': 'آدرس منبع یا برند/سال لازم است.'}, status=400)
            brand, year = _brand_year_from_url(url)
            req = DownloadRequest.objects.create(
                url=url, brand=brand or '', year=year,
                name_filter=(body.get('filter') or '').strip())
            return JsonResponse({'ok': True, 'request': _download_dict(req)})

        if action == 'cancel_download':
            req = DownloadRequest.objects.filter(id=body.get('request_id')).first()
            if req is None:
                return JsonResponse({'error': 'درخواست یافت نشد.'}, status=404)
            if req.status in DownloadRequest.ACTIVE:
                req.status = 'canceled'
                req.finished_at = timezone.now()
                req.save(update_fields=['status', 'finished_at', 'updated_at'])
            return JsonResponse({'ok': True, 'request': _download_dict(req)})

        if action == 'scan_zips':
            from . import ingest
            try:
                summary = ingest.scan_inbox(
                    normalize=bool(body.get('normalize', True)),
                    dry_run=bool(body.get('dry_run')))
            except Exception as e:
                return JsonResponse({'error': str(e)}, status=500)
            return JsonResponse({'ok': True, 'summary': summary})

        if action in ('skip_zip', 'requeue_zip'):
            pkg = ZipPackage.objects.filter(id=body.get('zip_id')).first()
            if pkg is None:
                return JsonResponse({'error': 'بسته یافت نشد.'}, status=404)
            if action == 'skip_zip' and pkg.status in ('pending', 'failed'):
                pkg.status = 'skipped_duplicate'
                pkg.error = 'skipped by admin'
                pkg.save(update_fields=['status', 'error', 'updated_at'])
            elif action == 'requeue_zip' and pkg.status in ('failed', 'skipped_duplicate'):
                pkg.status = 'pending'
                pkg.error = ''
                pkg.save(update_fields=['status', 'error', 'updated_at'])
            return JsonResponse({'ok': True, 'zip': _zip_dict(pkg)})

        return JsonResponse({'error': 'unknown action'}, status=400)

    st = PipelineSettings.get()
    work = pipeline.pending_work()
    load = pipeline.load_snapshot()
    est = pipeline.estimate_duration_s(work, st)

    current = pipeline.active_job()
    if current is None:
        current = (ProcessingJob.objects.filter(status='scheduled')
                   .order_by('scheduled_for').first())
    if current is None:
        current = (ProcessingJob.objects
                   .filter(status__in=ProcessingJob.RESUMABLE)
                   .order_by('-created_at').first())
    last_done = (ProcessingJob.objects
                 .filter(status__in=['done', 'failed', 'canceled'])
                 .order_by('-created_at').first())

    zip_counts = {}
    for status in ZipPackage.objects.values_list('status', flat=True):
        zip_counts[status] = zip_counts.get(status, 0) + 1

    return JsonResponse({
        'pending': work,
        'load': load,
        'estimate_s': est,
        'recommendation': pipeline.recommendation(work, load, est),
        'job': pipeline.job_dict(current),
        'last_job': pipeline.job_dict(last_done),
        'history': [
            {'id': j.id, 'status': j.status, 'trigger': j.trigger,
             'created_at': j.created_at.isoformat(),
             'finished_at': j.finished_at.isoformat() if j.finished_at else None,
             'overall_pct': (j.progress or {}).get('overall_pct'),
             'error': j.error}
            for j in ProcessingJob.objects.all()[:12]
        ],
        'download_requests': [_download_dict(r) for r in
                              DownloadRequest.objects.all()[:10]],
        'zip_queue': {
            'counts': zip_counts,
            'rows': [_zip_dict(p) for p in
                     ZipPackage.objects.order_by('-updated_at')[:200]],
        },
        'settings': {'auto_enabled': st.auto_enabled,
                     'auto_resume': st.auto_resume,
                     'max_power': getattr(st, 'max_power', False),
                     'load_threshold': st.load_threshold,
                     'embed_rate_pps': st.embed_rate_pps,
                     'diag_secs_per_car': st.diag_secs_per_car,
                     'parse_secs_per_zip': getattr(st, 'parse_secs_per_zip', None),
                     'download_secs_per_vehicle': getattr(st, 'download_secs_per_vehicle', None)},
        'power_plan': pipeline.power_plan(getattr(st, 'max_power', False)),
    })


# ---------------------------------------------------------------------------
# Structured vehicle specs (schema.org) — read-only admin visibility
# ---------------------------------------------------------------------------

@require_admin_token
def admin_vehicle_specs_view(request):
    """GET /api/admin/vehicle-specs/            -> coverage list (no bodies)
       GET /api/admin/vehicle-specs/?car_id=N   -> one car's full spec+provenance
    """
    from . import vehicleschema
    from .rag import config as ragconfig

    car_id = request.GET.get('car_id')
    if car_id:
        car = Car.objects.filter(id=car_id).first()
        if car is None:
            return JsonResponse({'error': 'خودرو یافت نشد.'}, status=404)
        sp = VehicleSpec.objects.filter(car=car).first()
        return JsonResponse({
            'car_id': car.id, 'brand': car.brand_name, 'car_name': car.car_name,
            'display_name': ragconfig.display_name(car.car_name),
            'year': car.year,
            'spec': None if sp is None else {
                'data': sp.data, 'jsonld': vehicleschema.jsonld(sp.data),
                'provenance': sp.provenance, 'sections_used': sp.sections_used,
                'builder_version': sp.builder_version,
                'built_at': sp.built_at.isoformat(),
            },
        })

    specs = {s.car_id: s for s in VehicleSpec.objects.all()}
    field_coverage = {}
    vehicles = []
    for car in Car.objects.order_by('brand_name', 'car_name'):
        sp = specs.get(car.id)
        fields = (sorted(k for k in sp.data if not k.startswith('@'))
                  if sp else [])
        for f in fields:
            field_coverage[f] = field_coverage.get(f, 0) + 1
        vehicles.append({
            'car_id': car.id, 'brand': car.brand_name,
            'car_name': car.car_name,
            'display_name': ragconfig.display_name(car.car_name),
            'year': car.year, 'has_spec': sp is not None,
            'field_count': len(fields), 'fields': fields,
            'built_at': sp.built_at.isoformat() if sp else None,
        })
    return JsonResponse({
        'total': len(vehicles),
        'with_spec': sum(1 for v in vehicles if v['has_spec']),
        'stale': vehicleschema.stale_stems(),
        'field_coverage': field_coverage,
        'builder_version': vehicleschema.BUILDER_VERSION,
        'vehicles': vehicles,
    })


# ---------------------------------------------------------------------------
# Real-time: processing snapshot + a single comprehensive dashboard payload
# ---------------------------------------------------------------------------

def _emit_pipeline(etype, job):
    """Emit a pipeline lifecycle event to the admin audience, then refresh the
    'pending processing' fingerprint so the change is reflected immediately."""
    from . import events
    try:
        events.emit(etype, {'job': pipeline.job_dict(job)}, audience='admin')
        events.detect_and_emit()
    except Exception:
        pass


@require_admin_token
def admin_processing_snapshot_view(request):
    """GET /api/admin/processing-snapshot/ -> the live "what needs processing"
    picture (unprocessed / needs-RAG / needs-DIAG per vehicle + active job +
    load). This is the REST snapshot the admin dashboard loads before it
    switches to the SSE stream for deltas."""
    from . import events
    return JsonResponse(events.snapshot_pending())


@require_admin_token
def admin_dashboard_view(request):
    """GET /api/admin/dashboard/ -> one comprehensive payload for the modern
    admin dashboard's initial render: KPIs, processing picture, open alerts,
    open company requests, recent events, and a small traffic sparkline. After
    this, the dashboard stays current from the SSE stream alone."""
    from . import events as ev
    from .models import (
        ActivityLog, Car, Company, CompanyRequest, Event, PortalUser,
        PurchaseRequest,
    )

    now = timezone.now()
    today = now.date()

    # KPIs
    kpis = {
        'companies': Company.objects.filter(active=True).count(),
        'users': PortalUser.objects.filter(active=True).count(),
        'vehicles': Car.objects.count(),
        'activities_today': ActivityLog.objects.filter(created_at__date=today).count(),
        'open_company_requests': CompanyRequest.objects.filter(
            status__in=CompanyRequest.OPEN_STATUSES).count(),
        'open_purchase_requests': PurchaseRequest.objects.filter(status='new').count(),
        'open_alerts': SystemAlert.objects.filter(is_open=True).count(),
    }

    # Processing picture (reuses the same snapshot the SSE detector emits).
    snapshot = ev.snapshot_pending()

    # Open alerts (compact).
    alerts = [{'id': a.id, 'key': a.key, 'severity': a.severity,
               'message': a.message, 'last_seen': a.last_seen.isoformat()}
              for a in SystemAlert.objects.filter(is_open=True)[:20]]

    # Open company requests (most recent first).
    from .requests_api import _request_dict
    open_requests = [_request_dict(r, include_company=True) for r in
                     CompanyRequest.objects.filter(status__in=CompanyRequest.OPEN_STATUSES)
                     .select_related('company', 'created_by')[:15]]

    # Recent activity feed (cross-company, compact).
    recent_activity = [{
        'id': a.id,
        'user': (a.user.display_name or a.user.username) if a.user_id else '—',
        'company': a.user.company.name if a.user_id and a.user.company_id else '—',
        'action': a.action, 'detail': a.detail, 'category': a.category,
        'car': (f'{a.car.brand_name} {a.car.car_name}' if a.car_id else None),
        'created_at': a.created_at.isoformat(),
    } for a in ActivityLog.objects.select_related('user', 'user__company', 'car')
        .order_by('-id')[:20]]

    # Traffic sparkline (last 14 days of request counts).
    try:
        monitoring.flush_metrics()
    except Exception:
        pass
    since = now - timezone.timedelta(days=14)
    daily = {}
    for row in (TrafficStat.objects.filter(bucket__gte=since)
                .values('bucket__date').annotate(n=Sum('requests'))):
        daily[row['bucket__date'].isoformat()] = row['n']
    spark = [{'date': d, 'requests': n} for d, n in sorted(daily.items())]

    return JsonResponse({
        'kpis': kpis,
        'processing': snapshot,
        'alerts': alerts,
        'open_requests': open_requests,
        'recent_activity': recent_activity,
        'traffic_spark': spark,
        'cursor': Event.objects.order_by('-id').values_list('id', flat=True).first() or 0,
        'ts': now.isoformat(),
    })
