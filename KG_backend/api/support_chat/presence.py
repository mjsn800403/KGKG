"""Who is genuinely able to answer right now.

Three separate facts per staff member, never collapsed into one flag:

* **connected**: their console pinged within the presence window;
* **declared**: they set themselves ``available``;
* **eligible**: active account AND connected AND declared.

The public widget says "live" only when at least one person is eligible. A
closed tab stops being connected within the window, and going ``offline`` or
``away`` takes effect immediately regardless of the last ping. The window is
configurable (KG_SUPPORT_PRESENCE_WINDOW_S, default 60 s, three missed
20-25 s pings). A false "async" is the safe failure; a false "live" needs a
fresh ping AND an explicit declaration.
"""
from datetime import timedelta

from django.utils import timezone

from . import config, rbac
from .models import SupportPresence

STATUSES = ('available', 'away', 'offline')


def set_status(admin, status):
    if status not in STATUSES:
        raise ValueError(f'unknown status {status!r}')
    SupportPresence.objects.update_or_create(admin=admin, defaults={'manual_status': status})


def heartbeat(admin, now=None):
    SupportPresence.objects.update_or_create(
        admin=admin, defaults={'last_heartbeat_at': now or timezone.now()})


def _connected(row, now):
    beat = row.last_heartbeat_at
    window = timedelta(seconds=config.presence_window_seconds())
    return beat is not None and now - window < beat <= now


def snapshot(now=None):
    """Per active staff member with a presence row: the three facts."""
    now = now or timezone.now()
    out = []
    for row in SupportPresence.objects.select_related('admin').order_by('admin__username'):
        if not row.admin.active:
            continue
        connected = _connected(row, now)
        declared = row.manual_status == 'available'
        # Eligible also needs a role that can answer something (enforce only; off and
        # audit keep today's rule).
        eligible = connected and declared and rbac.can_reply_intent(row.admin, None)
        out.append({'username': row.admin.username, 'connected': connected,
                    'declared': declared, 'eligible': eligible,
                    'status': row.manual_status})
    return out


def current_mode(now=None, intent=None):
    """``live`` when someone connected AND declared available can answer ``intent``
    (any intent when None); otherwise ``async``. A sales agent makes «قیمت و خرید»
    live without making «مشکل فنی» live."""
    now = now or timezone.now()
    for row in SupportPresence.objects.select_related('admin').order_by('admin__username'):
        if (row.admin.active and _connected(row, now) and row.manual_status == 'available'
                and rbac.can_reply_intent(row.admin, intent)):
            return 'live'
    return 'async'
