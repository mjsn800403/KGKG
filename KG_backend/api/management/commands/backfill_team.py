"""Backfill the team-management fields for existing companies.

For each company, promote the highest active role-level user to a company
manager (``can_manage_team`` + ``can_view_analytics``), and normalise the invite
lifecycle for everyone who already has a usable password. Idempotent.

    python manage.py backfill_team [--dry-run]
"""
from django.core.management.base import BaseCommand
from django.db.models import Q

from api.access import ROLE_LEVEL, normalize_role
from api.models import Company, PortalUser


class Command(BaseCommand):
    help = 'Backfill team-management capability + invite state for existing users.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='Report what would change without writing.')

    def handle(self, *args, **opts):
        dry = opts['dry_run']
        promoted = 0
        normalised = 0

        # Everyone who already has a password is an "active" account.
        existing = PortalUser.objects.filter(password_set=True).exclude(invite_status='active')
        for u in existing:
            normalised += 1
            if not dry:
                u.invite_status = 'active'
                u.save(update_fields=['invite_status'])

        for company in Company.objects.all():
            users = list(company.users.filter(active=True))
            if not users:
                continue
            if company.users.filter(can_manage_team=True).exists():
                continue  # already has a manager
            # Highest role in the org (lowest ROLE_LEVEL number wins).
            top = min(users, key=lambda u: ROLE_LEVEL.get(normalize_role(u.role), 99))
            promoted += 1
            self.stdout.write(
                f'  {company.name}: manager -> {top.display_name or top.username} '
                f'({top.role})')
            if not dry:
                top.can_manage_team = True
                top.can_view_analytics = True
                top.save(update_fields=['can_manage_team', 'can_view_analytics'])

        prefix = '[dry-run] ' if dry else ''
        self.stdout.write(self.style.SUCCESS(
            f'{prefix}Promoted {promoted} manager(s); normalised {normalised} invite state(s).'))
