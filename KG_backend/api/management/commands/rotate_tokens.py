"""Prune expired session tokens, and revoke live ones on demand.

Two jobs, one command:

  * `--prune` (the systemd timer's job) deletes rows whose `expires_at` has
    passed. Expiry is already enforced at lookup time, so this is hygiene
    rather than security — but without it the table grows forever and every
    stale row is one more hashed credential sitting in a backup.

  * `--revoke ...` is the incident-response path: kill one user's sessions, one
    admin's sessions, or everything, right now.

Usage:
    manage.py rotate_tokens --prune
    manage.py rotate_tokens --revoke-user ahmadi
    manage.py rotate_tokens --revoke-admin           # all platform admins
    manage.py rotate_tokens --revoke-all --yes
    manage.py rotate_tokens                          # report only
"""
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from api.models import AdminAuthToken, AuthToken, PortalUser


class Command(BaseCommand):
    help = 'Prune expired session tokens or revoke live ones.'

    def add_arguments(self, parser):
        parser.add_argument('--prune', action='store_true',
                            help='Delete tokens whose expiry has passed.')
        parser.add_argument('--revoke-user', metavar='USERNAME',
                            help='Revoke every session for one portal user.')
        parser.add_argument('--revoke-admin', action='store_true',
                            help='Revoke every platform-admin session.')
        parser.add_argument('--revoke-all', action='store_true',
                            help='Revoke every session, user and admin.')
        parser.add_argument('--yes', action='store_true',
                            help='Required confirmation for --revoke-all.')

    def handle(self, *args, **opts):
        did_something = False

        if opts['prune']:
            did_something = True
            users = AuthToken.prune()
            admins = AdminAuthToken.prune()
            self.stdout.write(
                f'pruned {users} expired user token(s), {admins} admin token(s)')

        if opts['revoke_user']:
            did_something = True
            user = PortalUser.objects.filter(
                username__iexact=opts['revoke_user']).first()
            if not user:
                raise CommandError(f'no such portal user: {opts["revoke_user"]}')
            count = AuthToken.objects.filter(user=user).delete()[0]
            self.stdout.write(self.style.SUCCESS(
                f'revoked {count} session(s) for {user.username}'))

        if opts['revoke_admin']:
            did_something = True
            count = AdminAuthToken.objects.all().delete()[0]
            self.stdout.write(self.style.SUCCESS(
                f'revoked {count} platform-admin session(s)'))

        if opts['revoke_all']:
            if not opts['yes']:
                raise CommandError(
                    '--revoke-all signs out every user and admin. '
                    'Re-run with --yes if that is what you want.')
            did_something = True
            users = AuthToken.objects.all().delete()[0]
            admins = AdminAuthToken.objects.all().delete()[0]
            self.stdout.write(self.style.SUCCESS(
                f'revoked {users} user + {admins} admin session(s)'))

        if not did_something:
            self._report()

    def _report(self):
        now = timezone.now()
        for label, model in (('user', AuthToken), ('admin', AdminAuthToken)):
            total = model.objects.count()
            expired = model.objects.filter(expires_at__lte=now).count()
            idle, absolute = model._ttls()
            self.stdout.write(
                f'{label:<6}: {total - expired} live, {expired} expired '
                f'(idle {idle}, max {absolute})')
        self.stdout.write('run with --prune to delete the expired rows.')
