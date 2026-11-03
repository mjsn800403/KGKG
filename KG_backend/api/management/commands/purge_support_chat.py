"""Report, and when explicitly enabled delete, support chat threads past retention.

    python manage.py purge_support_chat                 # report only (default)
    python manage.py purge_support_chat --apply         # refused unless enabled

Deletion happens ONLY when the owner has approved a retention policy and set
KG_SUPPORT_RETENTION_ENABLED=1 AND the operator passes --apply. Until then this
command only counts what the proposed periods would remove. The periods
(api/support_chat/config.py) are proposals pending approval; see the corrections plan.

A thread's messages and ratings are deleted with it. Backups are not touched:
deleted data persists in them until their own retention expires.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from api.support_chat import config
from api.support_chat.models import SupportThread


def candidates(now=None):
    """{category: queryset} of threads past each proposed period."""
    now = now or timezone.now()
    days = config.retention()
    idle = lambda d: Q(last_activity_at__lt=now - timedelta(days=d))   # noqa: E731
    has_contact = ~Q(contact_phone='') | ~Q(contact_email='')
    promoted = Q(promoted_request__isnull=False)
    spam = Q(status='spam')
    return {
        'spam': SupportThread.objects.filter(spam & idle(days['spam'])),
        'promoted': SupportThread.objects.filter(promoted & ~spam & idle(days['promoted'])),
        'contact': SupportThread.objects.filter(
            has_contact & ~promoted & ~spam & idle(days['contact'])),
        'no_contact': SupportThread.objects.filter(
            ~has_contact & ~promoted & ~spam & idle(days['no_contact'])),
    }


class Command(BaseCommand):
    help = 'Report (and, only when enabled, delete) support threads past retention.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true',
                            help='Delete. Refused unless KG_SUPPORT_RETENTION_ENABLED=1.')

    def handle(self, *args, **opts):
        groups = candidates()
        total = sum(q.count() for q in groups.values())
        for name, qs in groups.items():
            self.stdout.write(f'{name}: {qs.count()}')
        if not config.retention_enabled():
            self.stdout.write('retention is DISABLED (no approved policy): nothing is deleted')
        if not opts['apply'] or not config.retention_enabled():
            if opts['apply']:
                raise CommandError('--apply refused: KG_SUPPORT_RETENTION_ENABLED is not 1')
            self.stdout.write(f'would delete {total} thread(s)')
            return
        deleted = 0
        for qs in groups.values():
            deleted += qs.count()
            qs.delete()
        self.stdout.write(f'deleted {deleted} thread(s)')
