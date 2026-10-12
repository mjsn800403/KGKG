"""Evaluate monitoring alert conditions and prune old observability data.

Intended to run on a timer (systemd/cron, e.g. every 5 minutes):

    python manage.py check_alerts

Opens/updates/auto-resolves SystemAlert rows (disk, memory, DB liveness,
error rates, latency, data-quality regressions) and, once a day's worth of
calls has passed, prunes rollup rows older than the retention window.
"""
from django.core.management.base import BaseCommand

from api import monitoring


class Command(BaseCommand):
    help = 'Evaluate system alert conditions; prune old metric rollups.'

    def add_arguments(self, parser):
        parser.add_argument('--prune-days', type=int, default=90,
                            help='Retention window for metric rollups (days).')
        parser.add_argument('--no-prune', action='store_true')

    def handle(self, *args, **opts):
        result = monitoring.evaluate_alerts()
        self.stdout.write(f"open: {result['open'] or '-'}")
        self.stdout.write(f"resolved: {result['resolved'] or '-'}")
        if not opts['no_prune']:
            pruned = monitoring.prune_old_data(days=opts['prune_days'])
            if any(pruned.values()):
                self.stdout.write(f'pruned: {pruned}')
        self.stdout.write(self.style.SUCCESS('alert check complete'))
