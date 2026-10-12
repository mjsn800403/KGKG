"""Alert when server secrets are overdue for rotation.

    python manage.py check_secret_age [--max-age-days 90]

Phase 6 Task 3. Deliberately does NOT rotate anything on a timer:
`rotate_secrets` takes effect only after a service restart, and rotating
KG_ADMIN_TOKEN unattended would silently break operator access. Rotation stays
a human decision; this makes *forgetting* it visible, which is the actual
failure mode (both secrets had been unchanged since first deploy).

Age is read from the newest timestamped backup `.env.prod.bak.<YYYYMMDDHHMMSS>`,
which only `rotate_secrets` writes — so hand edits to the env file (which touch
its mtime) cannot make secrets look freshly rotated.
"""
import datetime
import glob
import os
import re

from django.core.management.base import BaseCommand

from api import monitoring

ENV = '/opt/KGKG/KG_backend/.env.prod'
STAMP_RE = re.compile(r'\.env\.prod\.bak\.(\d{14})$')
ALERT_KEY = 'secrets_rotation_overdue'


def last_rotation():
    """(datetime, source) of the most recent rotate_secrets run, or (None, why)."""
    best = None
    for p in glob.glob(ENV + '.bak.*'):
        m = STAMP_RE.search(p)
        if not m:
            continue
        try:
            ts = datetime.datetime.strptime(m.group(1), '%Y%m%d%H%M%S')
        except ValueError:
            continue
        if best is None or ts > best:
            best = ts
    return best


def _close_alert():
    from django.utils import timezone
    from api.models import SystemAlert
    SystemAlert.objects.filter(key=ALERT_KEY, is_open=True).update(
        is_open=False, resolved_at=timezone.now())


class Command(BaseCommand):
    help = 'Alert when DJANGO_SECRET_KEY / KG_ADMIN_TOKEN are overdue for rotation.'

    def add_arguments(self, parser):
        parser.add_argument('--max-age-days', type=int, default=90)

    def handle(self, *args, **opts):
        limit = opts['max_age_days']
        ts = last_rotation()

        # Also check the env file is not group/world readable.
        perm_bad = ''
        try:
            mode = os.stat(ENV).st_mode & 0o777
            if mode & 0o077:
                perm_bad = ' env file mode is %o (expected 0600)' % mode
        except OSError:
            pass

        if ts is None:
            age = None
            msg = ('No rotate_secrets run on record (no timestamped env backup found).'
                   + perm_bad)
            overdue = True
        else:
            age = (datetime.datetime.now() - ts).days
            overdue = age > limit or bool(perm_bad)
            msg = ('Secrets last rotated %d days ago (limit %d).%s'
                   % (age, limit, perm_bad))

        if overdue:
            monitoring._raise_alert(
                ALERT_KEY,
                'critical' if perm_bad else 'warning',
                msg,
                {'age_days': age, 'limit_days': limit,
                 'last_rotation': ts.isoformat() if ts else None,
                 'remedy': 'manage.py rotate_secrets --what all, then restart kgkg-backend'})
            self.stdout.write(self.style.ERROR('OVERDUE: ' + msg))
        else:
            _close_alert()
            self.stdout.write(self.style.SUCCESS('secrets ok: ' + msg))
