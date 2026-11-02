"""Anonymous-visitor chat and agent presence.

Logged-in customers keep using CompanyRequest/TicketMessage; these tables hold
only conversations that start before anyone has an account, so a bug in the
anonymous endpoints can never expose company-scoped ticket data. A visitor
proves ownership of a thread with a bearer token stored here only as a hash.
See docs/superpowers/specs/2026-11-02-customer-communication-design.md §5.

Every NOT NULL column carries a db_default (rollback safety).
"""
import uuid

from django.db import models
from django.db.models.functions import Now
from django.utils import timezone


class ChatThread(models.Model):
    INTENT_CHOICES = [('sales', 'sales'), ('demo', 'demo'),
                      ('technical', 'technical'), ('other', 'other')]
    STATUS_CHOICES = [('open', 'open'), ('waiting_staff', 'waiting_staff'),
                      ('waiting_customer', 'waiting_customer'),
                      ('closed', 'closed'), ('spam', 'spam')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    token_hash = models.CharField(max_length=64, unique=True)   # sha256 hex of the bearer token
    intent = models.CharField(max_length=10, choices=INTENT_CHOICES, default='other',
                              db_default='other')
    status = models.CharField(max_length=18, choices=STATUS_CHOICES, default='open',
                              db_default='open', db_index=True)
    contact_name = models.CharField(max_length=120, blank=True, default='', db_default='')
    contact_phone = models.CharField(max_length=40, blank=True, default='', db_default='')
    contact_email = models.CharField(max_length=254, blank=True, default='', db_default='')
    source_page = models.CharField(max_length=200, blank=True, default='', db_default='')
    referrer = models.CharField(max_length=200, blank=True, default='', db_default='')
    ua_hash = models.CharField(max_length=64, blank=True, default='', db_default='')
    assignee = models.ForeignKey('api.PlatformAdmin', null=True, blank=True,
                                 on_delete=models.SET_NULL, related_name='chat_threads')
    priority = models.CharField(max_length=8, default='normal', db_default='normal')
    last_activity_at = models.DateTimeField(default=timezone.now, db_default=Now(), db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())
    closed_at = models.DateTimeField(null=True, blank=True)
    # Set when the visitor signs in (or staff decide) and the thread is copied
    # into a ticket. Points outward only; the ticket tables know nothing of it.
    promoted_request = models.ForeignKey('api.CompanyRequest', null=True, blank=True,
                                         on_delete=models.SET_NULL, related_name='chat_origin')
    csat_score = models.PositiveSmallIntegerField(null=True, blank=True)
    csat_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-last_activity_at']

    def __str__(self):
        return f'chat {self.id} [{self.status}]'


class ChatMessage(models.Model):
    AUTHOR_CHOICES = [('visitor', 'visitor'), ('admin', 'admin'), ('system', 'system')]

    thread = models.ForeignKey(ChatThread, on_delete=models.CASCADE, related_name='messages')
    author_kind = models.CharField(max_length=8, choices=AUTHOR_CHOICES, db_default='visitor')
    author_admin = models.ForeignKey('api.PlatformAdmin', null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name='chat_messages')
    body = models.TextField(db_default='')
    # Staff-only note: never serialised to the visitor.
    internal = models.BooleanField(default=False, db_default=False)
    # Client-generated id so a network retry cannot store the message twice.
    client_id = models.CharField(max_length=40, blank=True, default='', db_default='')
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())

    class Meta:
        ordering = ['id']
        indexes = [models.Index(fields=['thread', 'id'])]
        constraints = [models.UniqueConstraint(
            fields=['thread', 'client_id'], condition=~models.Q(client_id=''),
            name='chatmessage_client_id_once_per_thread')]


class AgentPresence(models.Model):
    STATUS_CHOICES = [('available', 'available'), ('away', 'away'), ('offline', 'offline')]

    admin = models.OneToOneField('api.PlatformAdmin', on_delete=models.CASCADE,
                                 related_name='chat_presence')
    manual_status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='offline',
                                     db_default='offline')
    last_heartbeat_at = models.DateTimeField(null=True, blank=True)
