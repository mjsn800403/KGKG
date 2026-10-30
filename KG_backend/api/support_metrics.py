"""Support-desk metrics: the first slice of the BI programme, built to the
discipline the evaluation's BI finding asks for — every number has a stated
definition, a named source column and a test that pins it.

Definitions are documented once, in
audit-evidence/16-improvement-programme/METRIC_DEFINITIONS.md, and the code
here is the single implementation of each. Where a figure cannot be computed
honestly it is reported as null rather than zero: an average of nothing is not
nought.

    GET /api/admin/support/metrics/?days=30     admin only
"""
from datetime import timedelta

from django.db.models import Avg, Count, Max, Min, Q
from django.http import JsonResponse
from django.utils import timezone

from . import feedback, knowledge, sla
from .admin_auth import require_admin_token
from .models import CompanyRequest

DEFAULT_DAYS = 30


def _days(request):
    try:
        return max(1, min(int(request.GET.get('days') or DEFAULT_DAYS), 365))
    except (TypeError, ValueError):
        return DEFAULT_DAYS


def _p90(values):
    """The 90th percentile by nearest-rank: the smallest observation at or
    above which 90 % of the sample lies. Stated because "p90" alone is
    ambiguous between interpolation methods."""
    if not values:
        return None
    ordered = sorted(values)
    import math
    idx = max(0, math.ceil(0.9 * len(ordered)) - 1)
    return ordered[idx]


def _avg(values):
    return (sum(values) / len(values)) if values else None


def _sla_block(rows, due_attr, happened_attr, now):
    counts = {'met': 0, 'breached': 0, 'pending': 0, 'untracked': 0}
    for r in rows:
        st = sla.state(getattr(r, due_attr), getattr(r, happened_attr), now)
        counts[st if st else 'untracked'] += 1
    decided = counts['met'] + counts['breached']
    counts['compliance'] = round(counts['met'] / decided, 4) if decided else None
    return counts


@require_admin_token
def admin_support_metrics_view(request):
    days = _days(request)
    now = timezone.now()
    since = now - timedelta(days=days)

    window = list(CompanyRequest.objects.filter(created_at__gte=since))
    created = len(window)
    closed = [r for r in window if r.status in CompanyRequest.CLOSED_STATUSES]
    openish = [r for r in window if r.status in CompanyRequest.OPEN_STATUSES]

    # First response: minutes from created_at to the first PUBLIC reply.
    fr = [(r.first_response_at - r.created_at).total_seconds() / 60
          for r in window if r.first_response_at]
    # Resolution: hours from created_at to resolved_at. A reopened ticket's
    # resolved_at is the latest closure, so the figure covers the whole life of
    # the problem rather than its first attempt.
    res = [(r.resolved_at - r.created_at).total_seconds() / 3600
           for r in window if r.resolved_at]

    rated = [r for r in window if r.csat_score is not None]
    distribution = {str(i): 0 for i in range(1, 6)}
    for r in rated:
        distribution[str(r.csat_score)] += 1

    by_source = {}
    by_kind = {}
    for r in window:
        by_source[r.source] = by_source.get(r.source, 0) + 1
        by_kind[r.kind] = by_kind.get(r.kind, 0) + 1

    # Backlog is current state, not a window: what is open right now.
    backlog_qs = CompanyRequest.objects.filter(status__in=CompanyRequest.OPEN_STATUSES)
    backlog_agg = backlog_qs.aggregate(
        open=Count('id'), oldest=Min('created_at'),
        unassigned=Count('id', filter=Q(assignee__isnull=True)),
        breaching=Count('id', filter=Q(sla_resolve_due_at__lt=now)))
    oldest_days = (((now - backlog_agg['oldest']).total_seconds() / 86400)
                   if backlog_agg['oldest'] else None)

    _, fb = feedback.summary(since)

    return JsonResponse({
        'days': days,
        'generated_at': now.isoformat(),
        'totals': {
            'created': created,
            'open': len(openish),
            'closed': len(closed),
            'reopened': sum(1 for r in window if r.reopen_count),
            'escalated': sum(1 for r in window if r.escalated_at),
        },
        'first_response': {'measured': len(fr), 'unmeasured': created - len(fr),
                           'avg_minutes': _avg(fr), 'p90_minutes': _p90(fr)},
        'resolution': {'measured': len(res), 'avg_hours': _avg(res),
                       'p90_hours': _p90(res)},
        'sla': {
            'policy_hours': {p: {'response': t[0].total_seconds() / 3600,
                                 'resolve': t[1].total_seconds() / 3600}
                             for p, t in sla.POLICY.items()},
            'response': _sla_block(window, 'sla_response_due_at', 'first_response_at', now),
            'resolution': _sla_block(window, 'sla_resolve_due_at', 'resolved_at', now),
        },
        'csat': {
            'responses': len(rated),
            'avg': _avg([r.csat_score for r in rated]),
            'distribution': distribution,
            # Of the tickets that closed in the window, how many were rated.
            'response_rate': (round(len(rated) / len(closed), 4) if closed else None),
        },
        'by_source': by_source,
        'by_kind': by_kind,
        'backlog': {'open': backlog_agg['open'],
                    'unassigned': backlog_agg['unassigned'],
                    'breaching_now': backlog_agg['breaching'],
                    'oldest_days': oldest_days},
        'feedback': {'submissions': fb['submissions'], 'avg_rating': fb['avg_rating'],
                     'with_comment': fb['with_comment']},
        'knowledge': knowledge.metrics(since),
    })
