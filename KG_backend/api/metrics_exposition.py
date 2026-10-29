"""Prometheus exposition for the application's own state.

Why this exists: Prometheus could already see the host, the containers and the
HTTP probes, but nothing inside the application — request rates, error ratios,
index health, open alerts. Those lived only in Django's own tables and admin
panel, which means no Prometheus rule and no Grafana panel could reach them.

Why it reads the database instead of in-process counters: gunicorn runs
several worker processes and a scrape lands on whichever one answers. Counters
kept in a worker's memory would expose one worker's slice of the truth, which
is worse than useless for alerting. api/monitoring.py already flushes the
in-memory aggregates into TrafficStat every KG_METRICS_FLUSH_S seconds, and
that table is shared by every worker — so the scrape reads what all workers
have written. The cost is up to one flush interval of staleness, which is well
inside the resolution any of these alerts act on.

The window is the current UTC hour, deliberately: TrafficStat buckets are
hourly, and a window that trails across buckets would keep a cleared condition
alive. Rules guard the ratio with a minimum request count, because a partial
hour starts small.

Access: KG_METRICS_TOKEN, separate from KG_ADMIN_TOKEN so that handing a
credential to Prometheus does not hand it the admin surface. Unset means the
endpoint returns 503 rather than serving internal state unauthenticated.
"""

import hmac
import os
import time

from django.http import HttpResponse, JsonResponse
from django.utils import timezone

CONTENT_TYPE = 'text/plain; version=0.0.4; charset=utf-8'

# Prometheus label values escape backslash, double quote and newline.
_ESCAPES = (('\\', '\\\\'), ('"', '\\"'), ('\n', '\\n'))

SEVERITIES = ('info', 'warning', 'critical')


def _escape(value):
    out = str(value)
    for raw, encoded in _ESCAPES:
        out = out.replace(raw, encoded)
    return out


class _Exposition:
    """Collects samples and renders them with HELP/TYPE for every metric.

    Keeping the rendering here (rather than reaching for prometheus_client)
    avoids a dependency whose multiprocess mode would need a shared state
    directory, gunicorn hooks and a cleanup story — all to re-derive numbers
    this application already aggregates in its database.
    """

    def __init__(self):
        self._metrics = []        # (name, type, help, [(labels, value)])
        self._index = {}

    def metric(self, name, kind, help_text):
        if name not in self._index:
            self._index[name] = (name, kind, help_text, [])
            self._metrics.append(self._index[name])
        return self

    def sample(self, name, value, labels=None, *, kind='gauge', help_text=''):
        self.metric(name, kind, help_text)
        self._index[name][3].append((labels or {}, value))
        return self

    def render(self):
        lines = []
        for name, kind, help_text, samples in self._metrics:
            lines.append(f'# HELP {name} {help_text}')
            lines.append(f'# TYPE {name} {kind}')
            for labels, value in samples:
                if labels:
                    rendered = ','.join(
                        f'{k}="{_escape(v)}"' for k, v in sorted(labels.items())
                    )
                    lines.append(f'{name}{{{rendered}}} {_fmt(value)}')
                else:
                    lines.append(f'{name} {_fmt(value)}')
        return '\n'.join(lines) + '\n'


def _fmt(value):
    if isinstance(value, bool):
        return '1' if value else '0'
    if isinstance(value, int):
        return str(value)
    return repr(round(float(value), 4))


# ---------------------------------------------------------------------------
# Collection. Each block is wrapped so that one unavailable subsystem degrades
# its own series instead of failing the whole scrape: a scrape that 500s tells
# Prometheus only that the scrape failed, which is the least useful moment to
# lose visibility.
# ---------------------------------------------------------------------------

def _traffic_rows(since):
    from .models import TrafficStat
    return list(
        TrafficStat.objects.filter(bucket__gte=since)
        .values_list('endpoint', 'method', 'requests',
                     'errors_4xx', 'errors_5xx', 'total_ms', 'max_ms')
    )


def _collect_traffic(exp):
    hour_start = timezone.now().replace(minute=0, second=0, microsecond=0)
    rows = _traffic_rows(hour_start)

    exp.metric('kgkg_http_requests_current_hour', 'gauge',
               'Requests served in the current UTC hour, by route group.')
    exp.metric('kgkg_http_errors_4xx_current_hour', 'gauge',
               'Responses with a 4xx status in the current UTC hour.')
    exp.metric('kgkg_http_errors_5xx_current_hour', 'gauge',
               'Responses with a 5xx status in the current UTC hour.')
    exp.metric('kgkg_http_latency_mean_ms_current_hour', 'gauge',
               'Mean server-side latency in ms over the current UTC hour.')
    exp.metric('kgkg_http_latency_max_ms_current_hour', 'gauge',
               'Worst server-side latency in ms seen in the current UTC hour.')

    for endpoint, method, requests, e4, e5, total_ms, max_ms in rows:
        labels = {'endpoint': endpoint, 'method': method}
        exp.sample('kgkg_http_requests_current_hour', requests, labels)
        exp.sample('kgkg_http_errors_4xx_current_hour', e4, labels)
        exp.sample('kgkg_http_errors_5xx_current_hour', e5, labels)
        exp.sample('kgkg_http_latency_mean_ms_current_hour',
                   (total_ms / requests) if requests else 0, labels)
        exp.sample('kgkg_http_latency_max_ms_current_hour', max_ms, labels)


def _collect_alerts(exp):
    from .models import SystemAlert
    counts = dict.fromkeys(SEVERITIES, 0)
    for row in (SystemAlert.objects.filter(is_open=True)
                .values_list('severity', flat=True)):
        if row in counts:
            counts[row] += 1
    # Every severity is always emitted: a rule must not break because the
    # series vanished when the condition cleared.
    for severity in SEVERITIES:
        exp.sample('kgkg_open_alerts', counts[severity], {'severity': severity},
                   help_text='Open (unresolved) SystemAlert rows by severity.')


def _collect_snapshot(exp):
    from .monitoring import system_snapshot
    snap = system_snapshot(deep=False)

    exp.sample('kgkg_uptime_seconds', snap.get('uptime_s') or 0,
               help_text='Seconds since this worker process started.')
    disk = snap.get('disk') or {}
    exp.sample('kgkg_disk_used_percent', disk.get('used_pct') or 0,
               help_text='Disk usage of the filesystem holding the application.')
    exp.sample('kgkg_disk_free_bytes', (disk.get('free_gb') or 0) * 1e9,
               help_text='Free bytes on the filesystem holding the application.')

    mem = snap.get('memory') or {}
    used_pct = mem.get('used_pct')
    if used_pct is None and mem.get('total_mb'):
        used_pct = 100 * (1 - (mem.get('available_mb') or 0) / mem['total_mb'])
    exp.sample('kgkg_memory_used_percent', used_pct or 0,
               help_text='Host memory in use, percent.')

    load = snap.get('load_avg') or []
    if load:
        exp.sample('kgkg_load1', load[0],
                   help_text='Host 1-minute load average.')
        exp.sample('kgkg_load1_per_core',
                   load[0] / (snap.get('cpu_count') or 1),
                   help_text='1-minute load average divided by core count.')

    rag = snap.get('rag_index') or {}
    exp.sample('kgkg_rag_index_present', 1 if rag.get('present') else 0,
               help_text='1 when the RAG index database file exists.')
    exp.sample('kgkg_rag_index_bytes', (rag.get('size_mb') or 0) * 1e6,
               help_text='Size of the RAG index database in bytes.')
    if snap.get('main_db_mb') is not None:
        exp.sample('kgkg_main_db_bytes', snap['main_db_mb'] * 1e6,
                   help_text='Size of the main SQLite database in bytes.')

    exp.sample('kgkg_catalog_cars', snap.get('catalog_cars') or 0,
               help_text='Vehicles registered in the catalogue.')
    exp.sample('kgkg_portal_users', snap.get('portal_users') or 0,
               help_text='Portal user accounts.')

    dq = snap.get('data_quality') or {}
    for field in ('complete', 'incomplete', 'corrupt', 'duplicates'):
        exp.sample(f'kgkg_data_quality_{field}', dq.get(field) or 0,
                   help_text=f'Vehicles reported {field} by the last data-quality run.')
    return snap


def _collect_jobs(exp):
    from .models import ProcessingJob
    exp.metric('kgkg_processing_jobs', 'gauge',
               'Data-pipeline jobs by status.')
    seen = {}
    for status in (ProcessingJob.objects.values_list('status', flat=True)):
        seen[status] = seen.get(status, 0) + 1
    for status in ('pending', 'running', 'done', 'failed', 'cancelled'):
        exp.sample('kgkg_processing_jobs', seen.pop(status, 0), {'status': status})
    for status, count in sorted(seen.items()):
        exp.sample('kgkg_processing_jobs', count, {'status': status})


def render_metrics():
    """Build the exposition payload. Never raises for a partial failure."""
    started = time.monotonic()
    exp = _Exposition()

    exp.sample('kgkg_up', 1,
               help_text='Always 1; the scrape reached the application.')
    exp.sample('kgkg_build_info', 1,
               {'release': os.environ.get('KG_RELEASE', 'dev')},
               help_text='Deployed release (commit sha), as a label.')

    db_ok = 1
    for collector in (_collect_traffic, _collect_alerts, _collect_snapshot,
                      _collect_jobs):
        try:
            collector(exp)
        except Exception:
            # One failing collector must not cost the scrape its other series.
            db_ok = 0
    exp.sample('kgkg_db_up', db_ok,
               help_text='1 when every database-backed collector succeeded.')

    exp.sample('kgkg_scrape_duration_seconds', time.monotonic() - started,
               help_text='Time this exposition took to build.')
    return exp.render()


def metrics_view(request):
    configured = (os.environ.get('KG_METRICS_TOKEN') or '').strip()
    if not configured:
        return JsonResponse(
            {'error': 'metrics_disabled',
             'detail': 'KG_METRICS_TOKEN is not set on this instance.'},
            status=503,
        )

    auth = request.META.get('HTTP_AUTHORIZATION', '')
    presented = auth[7:].strip() if auth.lower().startswith('bearer ') else \
        (request.META.get('HTTP_X_METRICS_TOKEN', '') or '').strip()

    if not presented or not hmac.compare_digest(presented, configured):
        return JsonResponse({'error': 'unauthorized'}, status=401)

    return HttpResponse(render_metrics(), content_type=CONTENT_TYPE)
