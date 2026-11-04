"""Read-only health of the support queue: who is waiting for a human reply, and for how long.

Nothing here writes, sends or alerts. ``manage.py support_health`` prints it and can exit
non-zero for a monitor to act on; wiring it into the alert sweep is a separate decision
because that would start delivering real alerts. A visitor is "waiting" when their latest
visitor message has no later public staff reply (internal notes do not count) on a thread that
is open or waiting for staff. The wait is measured from the oldest visitor message after the
last public reply.
"""
import os
from datetime import datetime, timezone as dt_timezone

from django.db.models import DateTimeField, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from .models import SupportMessage, SupportThread

LIVE_STATUSES = ('open', 'waiting_staff')
SCAN_LIMIT = 20000          # a safety valve for a runaway queue, not a normal limit
_EPOCH = Value(datetime(1970, 1, 1, tzinfo=dt_timezone.utc), output_field=DateTimeField())
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
    """[(intent, waiting_since)] for live threads whose visitor has no public staff reply yet.

    One query: a correlated subquery finds the last public staff reply, a second the oldest
    visitor message after it. Only two columns come back per waiting thread.
    """
    last_staff = (SupportMessage.objects
                  .filter(thread=OuterRef('pk'), author_kind='admin', internal=False)
                  .order_by('-created_at').values('created_at')[:1])
    wait_start = (SupportMessage.objects
                  .filter(thread=OuterRef('pk'), author_kind='visitor',
                          created_at__gt=Coalesce(OuterRef('last_staff'), _EPOCH))
                  .order_by('created_at').values('created_at')[:1])
    return list(SupportThread.objects.filter(status__in=LIVE_STATUSES)
                .annotate(last_staff=Subquery(last_staff))
                .annotate(wait_start=Subquery(wait_start))
                .filter(wait_start__isnull=False)
                .order_by('last_activity_at')
                .values_list('intent', 'wait_start')[:SCAN_LIMIT])


def report(now=None):
    now = now or timezone.now()
    warn, crit = thresholds()
    waits = [(intent, max(0, (now - since).total_seconds())) for intent, since in waiting_threads()]
    by_intent = {}
    for intent, _ in waits:
        by_intent[intent] = by_intent.get(intent, 0) + 1
    oldest = max((w for _, w in waits), default=0)
    level = 'crit' if oldest >= crit else 'warn' if oldest >= warn else 'ok'
    return {
        'level': level, 'waiting': len(waits), 'waiting_by_intent': by_intent,
        'oldest_wait_s': int(oldest), 'over_warn': sum(1 for _, w in waits if w >= warn),
        'over_crit': sum(1 for _, w in waits if w >= crit),
        'warn_after_s': warn, 'crit_after_s': crit, 'truncated': len(waits) >= SCAN_LIMIT,
        'checked_at': now.isoformat(),
    }
