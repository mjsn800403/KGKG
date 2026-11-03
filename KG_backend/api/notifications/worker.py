"""Sends outbox rows: claim, deliver, retry, give up visibly.

Safe to run from several processes at once (the timer and the opportunistic
kick): a row is claimed with a conditional UPDATE, and only the caller whose
UPDATE matched sends it. A row left in ``sending`` by a crashed worker is
reclaimed after ``STUCK_AFTER``.

Nothing is dropped. Over the SMS cap a row is deferred, not discarded; in
``off`` mode rows are not touched at all.
"""
import logging
import os
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from . import config, providers
from .models import NotificationOutbox

log = logging.getLogger('kgkg.notify')

BACKOFF_MINUTES = (1, 5, 15, 60, 240)
STUCK_AFTER = timedelta(minutes=10)
CAP_DEFER = timedelta(minutes=10)
DEAD_ALERT_KEY = 'notify:dead'
DEAD_ALERT_WINDOW = timedelta(hours=24)


def sms_cap_per_hour():
    try:
        return int(os.environ.get('KG_NOTIFY_SMS_MAX_PER_HOUR', '10'))
    except ValueError:
        return 10


def _claim(pk, now):
    """True only for the single caller that moved the row into ``sending``."""
    stuck_before = now - STUCK_AFTER
    won = NotificationOutbox.objects.filter(pk=pk).filter(
        Q(status__in=('queued', 'failed'), next_attempt_at__lte=now)
        | Q(status='sending', claimed_at__lt=stuck_before)
    ).update(status='sending', claimed_at=now)
    return won == 1


def _due_ids(now, limit):
    stuck_before = now - STUCK_AFTER
    return list(NotificationOutbox.objects.filter(
        Q(status__in=('queued', 'failed'), next_attempt_at__lte=now)
        | Q(status='sending', claimed_at__lt=stuck_before)
    ).order_by('next_attempt_at', 'id').values_list('pk', flat=True)[:limit])


def _scrub(row):
    """Drop the text of a message addressed to a visitor or customer once it is
    final (sent, dry-run, dead). The row keeps who/what/when/outcome for
    investigations; a customer's words are not kept in a delivery log."""
    if row.recipient_kind in ('visitor', 'customer'):
        row.payload = {'scrubbed': True}


def _fail(row, error, now, counts, *, permanent=False):
    row.attempts += 1
    row.last_error = (error or 'unknown error')[:300]
    row.claimed_at = None
    if permanent or row.attempts >= len(BACKOFF_MINUTES):
        row.status = 'dead'
        _scrub(row)
        counts['dead'] += 1
        log.warning('notify %s dead after %s attempt(s): %s', row.pk, row.attempts, row.last_error)
    else:
        row.status = 'failed'
        row.next_attempt_at = now + timedelta(minutes=BACKOFF_MINUTES[row.attempts - 1])
        counts['retried'] += 1
    row.save()


def _sync_dead_alert(now):
    """One open SystemAlert while anything went dead in the last day; resolved
    once nothing did. The monitoring sweep does not own this key."""
    from api.models import SystemAlert
    recent = NotificationOutbox.objects.filter(
        status='dead', created_at__gte=now - DEAD_ALERT_WINDOW).count()
    if recent:
        from api.monitoring import _raise_alert
        _raise_alert(DEAD_ALERT_KEY, 'warning',
                     f'{recent} notification(s) could not be delivered in the last 24 h',
                     {'dead': recent})
    else:
        SystemAlert.objects.filter(key=DEAD_ALERT_KEY, is_open=True).update(
            is_open=False, resolved_at=now)


def process_due(now=None, limit=50):
    """Send what is due. Returns counts: sent, retried, dead, deferred, skipped."""
    now = now or timezone.now()
    counts = dict(sent=0, retried=0, dead=0, deferred=0, skipped=0)
    sms_sent_this_hour = None
    for pk in _due_ids(now, limit):
        row = NotificationOutbox.objects.get(pk=pk)
        mode = config.mode(row.channel)
        if mode == 'off':
            counts['skipped'] += 1
            continue
        if mode == 'live' and row.channel == 'sms':
            if sms_sent_this_hour is None:
                sms_sent_this_hour = NotificationOutbox.objects.filter(
                    channel='sms', status='sent',
                    sent_at__gte=now - timedelta(hours=1)).count()
            if sms_sent_this_hour >= sms_cap_per_hour():
                if _claim(pk, now):
                    NotificationOutbox.objects.filter(pk=pk).update(
                        status='queued', claimed_at=None, next_attempt_at=now + CAP_DEFER)
                    counts['deferred'] += 1
                continue
        if not _claim(pk, now):
            continue
        row.refresh_from_db()
        payload = row.payload or {}
        subject, body = payload.get('subject', ''), payload.get('body', '')
        if row.channel == 'sms':
            problem = providers.check_sms_body(body)
            if problem:
                _fail(row, problem, now, counts, permanent=True)
                continue
        provider = providers.DryRunProvider() if mode == 'dry_run' \
            else providers.get_provider(row.channel)
        try:
            result = provider.send(row.recipient_ref, subject, body)
        except Exception as exc:
            result = providers.SendResult(False, error=f'provider raised: {exc}')
        if not result.accepted:
            _fail(row, result.error, now, counts)
            continue
        row.attempts += 1
        row.provider_ref = result.provider_ref[:100]
        row.claimed_at = None
        row.last_error = ''
        _scrub(row)
        if mode == 'dry_run':
            row.status = 'dry_run'
        else:
            row.status = 'sent'
            row.sent_at = now
            counts['sent'] += 1
            if row.channel == 'sms':
                sms_sent_this_hour += 1
        row.save()
    _sync_dead_alert(now)
    return counts
