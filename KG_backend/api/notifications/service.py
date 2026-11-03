"""Writing to the outbox. Request code calls ``enqueue`` and nothing else."""
from django.db import IntegrityError, transaction
from django.utils import timezone

from api.models import normalize_phone

from . import config
from .models import NotificationOutbox

CHANNELS = ('sms', 'email')


def window_key(prefix, minutes, now=None):
    """``prefix`` bucketed into ``minutes``-wide windows, so a burst of events
    inside one window shares a dedupe key and produces a single notification."""
    now = now or timezone.now()
    bucket = int(now.timestamp() // (minutes * 60))
    return f'{prefix}:{bucket}'


def enqueue(*, event_type, channel, recipient_kind, recipient_ref, subject, body,
            dedupe_key=None):
    """Record a notification. Returns the row, or None if ``dedupe_key`` was
    already used. With the channel mode ``off`` the row is written as
    ``suppressed`` so the intent is visible but nothing can be sent."""
    if channel not in CHANNELS:
        raise ValueError(f'unknown channel {channel!r}')
    ref = normalize_phone(recipient_ref) if channel == 'sms' else (recipient_ref or '').strip()
    status = 'suppressed' if config.mode(channel) == 'off' else 'queued'
    try:
        with transaction.atomic():
            return NotificationOutbox.objects.create(
                event_type=event_type, channel=channel, recipient_kind=recipient_kind,
                recipient_ref=ref, dedupe_key=dedupe_key, status=status,
                payload={'subject': subject, 'body': body})
    except IntegrityError:
        if dedupe_key is None:
            raise
        return None
