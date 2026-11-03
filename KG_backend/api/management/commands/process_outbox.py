"""Send due notifications from the outbox.

Intended to run on a timer (see ops/outbox/), e.g. every minute:

    python manage.py process_outbox

Does nothing for a channel whose mode (KG_NOTIFY_SMS / KG_NOTIFY_EMAIL) is
``off``, which is the default.
"""
from django.core.management.base import BaseCommand

from api.notifications import worker


class Command(BaseCommand):
    help = 'Send due outbox notifications (retries, caps and dead-lettering included).'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=50,
                            help='Maximum rows to process in this run.')

    def handle(self, *args, **opts):
        counts = worker.process_due(limit=opts['limit'])
        self.stdout.write(' '.join(f'{k}={v}' for k, v in counts.items()))
