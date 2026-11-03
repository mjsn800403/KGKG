"""Close and reopen a support thread.

Every transition is explicit and leaves a visible, clearly system-authored
line in the conversation, so history never silently changes state. Callers hold
the thread's row lock (``select_for_update``) and have checked preconditions.
"""
from datetime import timedelta

from django.utils import timezone

from . import config
from .models import SupportMessage

CLOSED_TEXT = 'گفتگو بسته شد.'
REOPENED_TEXT = 'گفتگو دوباره باز شد.'


def reopen_deadline(thread):
    """When a visitor can no longer reopen this closed thread."""
    since = thread.closed_at or thread.last_activity_at
    return since + timedelta(days=config.reopen_days())


def can_reopen(thread, now=None):
    return thread.status == 'closed' and (now or timezone.now()) <= reopen_deadline(thread)


def _system(thread, text):
    SupportMessage.objects.create(thread=thread, author_kind='system', body=text)


def close(thread):
    now = timezone.now()
    thread.status, thread.closed_at, thread.last_activity_at = 'closed', now, now
    thread.save(update_fields=['status', 'closed_at', 'last_activity_at'])
    _system(thread, CLOSED_TEXT)


def reopen(thread, *, by_staff):
    """Staff reopen to ``open`` (staff will speak next); a visitor reopen goes
    straight to ``waiting_staff`` because the visitor is the one asking."""
    thread.status = 'open' if by_staff else 'waiting_staff'
    thread.closed_at = None
    thread.reopen_count += 1
    thread.last_activity_at = timezone.now()
    thread.save(update_fields=['status', 'closed_at', 'reopen_count', 'last_activity_at'])
    _system(thread, REOPENED_TEXT)
