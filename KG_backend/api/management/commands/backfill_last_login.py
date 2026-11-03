"""Fill a null ``PortalUser.last_login_at`` from the newest ``login`` row in
``ActivityLog`` (#49).

    python manage.py backfill_last_login            # write
    python manage.py backfill_last_login --dry-run  # count only

Every login path sets the column today (``portal._issue_session`` and invite
acceptance in ``team.py``); accounts that last signed in before it existed
kept a null, so ``insights.admin_funnel_view`` counted them as dormant. Only
null values are written, so a real login is never overwritten. Idempotent.
"""
from django.core.management.base import BaseCommand
from django.db.models import Max

from api.models import ActivityLog, PortalUser


class Command(BaseCommand):
    help = 'Backfill a null last_login_at from the newest ActivityLog login row.'

    def add_arguments(self, p):
        p.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **opts):
        latest = dict(ActivityLog.objects.filter(
            action='login', user__last_login_at__isnull=True,
        ).values('user_id').annotate(at=Max('created_at')).values_list('user_id', 'at'))
        if opts['dry_run']:
            self.stdout.write(f'would backfill {len(latest)} account(s)')
            return
        n = 0
        for uid, at in latest.items():
            n += PortalUser.objects.filter(pk=uid, last_login_at__isnull=True).update(last_login_at=at)
        self.stdout.write(f'backfilled {n} account(s)')
