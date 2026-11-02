"""Who is genuinely available to answer right now.

The public widget says "online" only if ``current_mode`` says ``live``: an
active agent has set themselves available AND their console has pinged within
``LIVE_WINDOW``. Closing the tab ends it within a minute with no cleanup job.
"""
from datetime import timedelta

from django.utils import timezone

from .models import AgentPresence

LIVE_WINDOW = timedelta(seconds=60)
STATUSES = ('available', 'away', 'offline')


def set_status(admin, status):
    if status not in STATUSES:
        raise ValueError(f'unknown status {status!r}')
    AgentPresence.objects.update_or_create(admin=admin, defaults={'manual_status': status})


def heartbeat(admin, now=None):
    AgentPresence.objects.update_or_create(
        admin=admin, defaults={'last_heartbeat_at': now or timezone.now()})


def current_mode(now=None):
    now = now or timezone.now()
    live = AgentPresence.objects.filter(
        manual_status='available', admin__active=True,
        last_heartbeat_at__gt=now - LIVE_WINDOW, last_heartbeat_at__lte=now).exists()
    return 'live' if live else 'async'
