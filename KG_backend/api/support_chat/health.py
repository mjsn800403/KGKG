"""Read-only health of the support queue: who is waiting for a human reply, and for how long.

Nothing here writes, sends or alerts. ``manage.py support_health`` prints it and can exit
non-zero for a monitor to act on; wiring it into the alert sweep is a separate decision
because that would start delivering real alerts. A visitor is "waiting" when their latest
visitor message has no later public staff reply (internal notes do not count) on a thread that
is open or waiting for staff. The wait is measured from the oldest visitor message after the
last public reply.
"""
import os

from django.db.models import F, Max, Q
from django.utils import timezone

from .models import SupportMessage, SupportThread

LIVE_STATUSES = ('open', 'waiting_staff')
SCAN_LIMIT = 500
DEFAULT_WARN_S = 300
DEFAULT_CRIT_S = 900


def _seconds(name, default):
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def thresholds():
    warn = _seconds('KG_SUPPORT_WAIT_WARN_S', DEFAULT_WARN_S)
    return warn, max(warn, _seconds('KG_SUPPORT_WAIT_CRIT_S', DEFAULT_CRIT_S))


def waiting_threads():
    """[(thread, waiting_since)] for live threads whose visitor has no public staff reply yet."""
    rows = (SupportThread.objects.filter(status__in=LIVE_STATUSES)
            .annotate(last_staff=Max('messages__created_at',
                                     filter=Q(messages__author_kind='admin', messages__internal=False)),
                      last_visitor=Max('messages__created_at', filter=Q(messages__author_kind='visitor')))
            .filter(last_visitor__isnull=False)
            .filter(Q(last_staff__isnull=True) | Q(last_visitor__gt=F('last_staff')))
            .order_by('last_activity_at')[:SCAN_LIMIT])
    out = []
    for t in rows:
        since = SupportMessage.objects.filter(thread=t, author_kind='visitor')
        if t.last_staff:
            since = since.filter(created_at__gt=t.last_staff)
        first = since.order_by('created_at').values_list('created_at', flat=True).first()
        out.append((t, first or t.last_visitor))
    return out


def report(now=None):
    now = now or timezone.now()
    warn, crit = thresholds()
    waits = [(t, max(0, (now - since).total_seconds())) for t, since in waiting_threads()]
    by_intent = {}
    for t, _ in waits:
        by_intent[t.intent] = by_intent.get(t.intent, 0) + 1
    oldest = max((w for _, w in waits), default=0)
    level = 'crit' if oldest >= crit else 'warn' if oldest >= warn else 'ok'
    return {
        'level': level, 'waiting': len(waits), 'waiting_by_intent': by_intent,
        'oldest_wait_s': int(oldest), 'over_warn': sum(1 for _, w in waits if w >= warn),
        'over_crit': sum(1 for _, w in waits if w >= crit),
        'warn_after_s': warn, 'crit_after_s': crit, 'truncated': len(waits) >= SCAN_LIMIT,
        'checked_at': now.isoformat(),
    }
