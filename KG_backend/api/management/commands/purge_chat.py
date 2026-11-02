"""Delete idle anonymous chat threads.

    python manage.py purge_chat [--dry-run]

Threads with no contact details are removed after 30 idle days; threads that
left a phone or email after 365. A thread promoted to a ticket is never
removed (the ticket is the record). Run it from a daily timer.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from api.chat.models import ChatThread

ANONYMOUS_DAYS = 30
CONTACT_DAYS = 365


class Command(BaseCommand):
    help = 'Delete idle anonymous chat threads (30 d without contact, 365 d with).'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **opts):
        now = timezone.now()
        has_contact = ~Q(contact_phone='') | ~Q(contact_email='')
        stale = ChatThread.objects.filter(promoted_request__isnull=True).filter(
            (~has_contact & Q(last_activity_at__lt=now - timedelta(days=ANONYMOUS_DAYS)))
            | (has_contact & Q(last_activity_at__lt=now - timedelta(days=CONTACT_DAYS))))
        n = stale.count()
        if opts['dry_run']:
            self.stdout.write(f'would delete {n} thread(s)')
            return
        stale.delete()
        self.stdout.write(f'deleted {n} thread(s)')
