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

from . import feedback, knowledge, onboarding, sla
from .admin_auth import require_admin_token
from .models import CompanyRequest, KbSearchLog

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
    # The rate's numerator has to live inside its denominator. A ticket rated
    # and then reopened keeps its score but is no longer closed, so counting it
    # against `closed` alone produced rates above 100 % — and a null rate beside
    # recorded responses when every rated ticket had been reopened. `responses`
    # still counts every score; only the ratio is restricted.
    rated_closed = [r for r in rated if r.status in CompanyRequest.CLOSED_STATUSES]
    distribution = {str(i): 0 for i in range(1, 6)}
    for r in rated:
        distribution[str(r.csat_score)] += 1

    by_source = {}
    by_kind = {}
    by_topic = {}
    for r in window:
        by_source[r.source] = by_source.get(r.source, 0) + 1
        by_kind[r.kind] = by_kind.get(r.kind, 0) + 1
        # 'uncategorised' rather than '' so the gap is legible in a dashboard
        # and cannot be mistaken for a topic nobody has named yet.
        by_topic[r.topic or 'uncategorised'] = by_topic.get(r.topic or 'uncategorised', 0) + 1

    topic_labels = dict(CompanyRequest.TOPIC_CHOICES)
    by_topic_labelled = [{'id': t, 'label': topic_labels.get(t, 'دسته‌بندی‌نشده'),
                          'count': n}
                         for t, n in sorted(by_topic.items(), key=lambda kv: -kv[1])]

    # Tickets per vehicle: only those that named one, so this never implies a
    # vehicle is trouble-free when nobody said which vehicle they meant.
    by_vehicle = [
        {'car_id': row['car_id'],
         'name': f"{row['car__brand_name']} {row['car__car_name']} "
                 f"{row['car__year']}".strip(),
         'count': row['n']}
        for row in (CompanyRequest.objects.filter(created_at__gte=since,
                                                  car__isnull=False)
                    .values('car_id', 'car__brand_name', 'car__car_name', 'car__year')
                    .annotate(n=Count('id')).order_by('-n')[:10])]

    # Did the knowledge base answer anything before it became a ticket? Only
    # an explicit "this answered it" counts; see api/knowledge.deflect_view.
    compose = KbSearchLog.objects.filter(created_at__gte=since, context='compose')
    suggested = compose.count()
    deflected = compose.filter(deflected_article__isnull=False).count()
    zero_results = compose.filter(results=0).count()

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
            # Of the tickets that are closed at the end of the window, how
            # many carry a score. Same cohort both sides.
            'response_rate': (round(len(rated_closed) / len(closed), 4) if closed else None),
        },
        'by_source': by_source,
        'by_kind': by_kind,
        'by_topic': by_topic,
        'by_topic_labelled': by_topic_labelled,
        'by_vehicle': by_vehicle,
        'deflections': {'suggested': suggested, 'deflected': deflected,
                        'rate': (deflected / suggested) if suggested else None},
        'search': {'compose_searches': suggested,
                   'zero_result_share': ((zero_results / suggested)
                                         if suggested else None)},
        'backlog': {'open': backlog_agg['open'],
                    'unassigned': backlog_agg['unassigned'],
                    'breaching_now': backlog_agg['breaching'],
                    'oldest_days': oldest_days},
        'feedback': {'submissions': fb['submissions'], 'avg_rating': fb['avg_rating'],
                     'with_comment': fb['with_comment']},
        'knowledge': knowledge.metrics(since),
        # Current state, not windowed: "of the people who could use this, how
        # many ever have". Computed by the same function that builds each
        # seat's own checklist, so the figure here and the item they see
        # cannot drift apart.
        'feature_discovery': onboarding.discovery_counts(
            onboarding.measurable_seats()),
    })
