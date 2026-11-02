"""The notification outbox.

Request code never talks to an SMS or email provider. It writes a row here in
the same transaction as the thing being announced, so a crash cannot lose a
notification and a rolled-back message cannot leave one behind. A worker
(api/notifications/worker.py) sends the rows, retries failures, and gives up
visibly. See docs/superpowers/specs/2026-11-02-customer-communication-design.md §6.

Every NOT NULL column carries a db_default so the previous release, which does
not know this table, is never affected by a rollback.
"""
from django.db import models
from django.db.models.functions import Now
from django.utils import timezone


class NotificationOutbox(models.Model):
    CHANNEL_CHOICES = [('sms', 'sms'), ('email', 'email')]
    KIND_CHOICES = [('staff', 'staff'), ('visitor', 'visitor'), ('customer', 'customer')]
    STATUS_CHOICES = [
        ('queued', 'queued'),
        ('sending', 'sending'),
        ('sent', 'sent'),            # accepted by the provider, NOT proof of handset delivery
        ('failed', 'failed'),        # will be retried at next_attempt_at
        ('dead', 'dead'),            # retries exhausted
        ('suppressed', 'suppressed'),  # channel mode was off when it was written
        ('dry_run', 'dry_run'),      # rendered and logged, never sent
    ]

    event_type = models.CharField(max_length=48, db_default='')
    channel = models.CharField(max_length=8, choices=CHANNEL_CHOICES, db_default='sms')
    recipient_kind = models.CharField(max_length=10, choices=KIND_CHOICES, db_default='staff')
    # The phone number or address itself, kept only as long as the row lives.
    recipient_ref = models.CharField(max_length=254, db_default='')
    # Unique when set; callers bucket it by time window to coalesce bursts.
    dedupe_key = models.CharField(max_length=200, null=True, blank=True, unique=True)
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='queued',
                              db_default='queued')
    attempts = models.PositiveSmallIntegerField(default=0, db_default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now, db_default=Now())
    claimed_at = models.DateTimeField(null=True, blank=True)
    provider_ref = models.CharField(max_length=100, blank=True, default='', db_default='')
    last_error = models.CharField(max_length=300, blank=True, default='', db_default='')
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['id']
        indexes = [models.Index(fields=['status', 'next_attempt_at'])]

    def __str__(self):
        return f'outbox #{self.id} {self.channel}/{self.event_type} [{self.status}]'
