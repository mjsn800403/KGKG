"""Backfill ``PortalUser.reports_to`` from the org-graph canvas.

The canvas became the live org structure but never wrote the legacy reporting
field, so companies seeded before that fix carry stale/NULL pointers. Team and
analytics scoping now reads the canvas directly; this command repairs the legacy
field for everything else that still consumes it (analytics ordering,
enforce_org_consistency).

    manage.py sync_org_reports [--company-id N] [--dry-run]
"""
from django.core.management.base import BaseCommand

from api.models import Company, PortalUser
from api import orggraph as og


class Command(BaseCommand):
    help = 'Mirror org-graph parent edges onto PortalUser.reports_to.'

    def add_arguments(self, parser):
        parser.add_argument('--company-id', type=int, default=None,
                            help='Only this company (default: every company).')
        parser.add_argument('--dry-run', action='store_true',
                            help='Report what would change without writing.')

    def handle(self, *args, **opts):
        qs = Company.objects.all()
        if opts['company_id']:
            qs = qs.filter(id=opts['company_id'])
        total = 0
        for company in qs:
            if opts['dry_run']:
                changed = self._preview(company)
            else:
                changed = og.sync_reports_to_from_graph(company)
            total += changed
            if changed:
                self.stdout.write(f'{company.name}: {changed} user(s) re-pointed')
        verb = 'would change' if opts['dry_run'] else 'updated'
        self.stdout.write(self.style.SUCCESS(f'{verb} {total} row(s)'))

    def _preview(self, company):
        """Count rows sync_reports_to_from_graph would rewrite, writing nothing."""
        from django.db import transaction
        count = 0
        try:
            with transaction.atomic():
                before = dict(PortalUser.objects.filter(company=company)
                              .values_list('id', 'reports_to_id'))
                og.sync_reports_to_from_graph(company)
                after = dict(PortalUser.objects.filter(company=company)
                             .values_list('id', 'reports_to_id'))
                count = sum(1 for k, v in after.items() if before.get(k) != v)
                raise _Rollback()
        except _Rollback:
            pass
        return count


class _Rollback(Exception):
    """Internal sentinel: unwinds the preview transaction."""
