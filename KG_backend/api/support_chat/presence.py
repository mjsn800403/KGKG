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

from . import config
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
        out.append({'username': row.admin.username, 'connected': connected,
                    'declared': declared, 'eligible': connected and declared,
                    'status': row.manual_status})
    return out


def current_mode(now=None):
    return 'live' if any(r['eligible'] for r in snapshot(now)) else 'async'
