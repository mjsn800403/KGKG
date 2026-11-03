"""Support-role tooling (the owner-approved safety gate and recovery path for RBAC).

    python manage.py support_roles report                 # who is who; read-only, no secrets
    python manage.py support_roles check                  # findings; read-only, always exits 0
    python manage.py support_roles check --for-enforce    # read-only; exits 1 if enforcing now would lock support out
    python manage.py support_roles grant  --admin USER --role ROLE [--apply]
    python manage.py support_roles revoke --admin USER --role ROLE [--apply]

``report`` and ``check`` never write, send anything or change a setting. ``grant`` and
``revoke`` are a DRY RUN unless ``--apply`` is given, change only the role table, write an
id-only audit row, and refuse to remove the last active support owner. They need the role
table (migration B) and refuse with a clear message until it exists. Exit codes: 0 = fine
(or only reporting, or a dry run), 1 = a blocking problem under --for-enforce or a refused
change, 2 = the command itself failed (never to be read as a pass). Run ``check
--for-enforce`` and get 0 BEFORE setting KG_SUPPORT_RBAC=enforce. None of this is part of a
deployment step, and it never touches ordinary administrator access; because it is a server
command it also works when every role is misconfigured (the recovery path).
Design: docs/superpowers/specs/2026-11-03-phase3-migration-and-rbac-design.md section 3.3.
"""
import json

from django.core.management.base import BaseCommand

from api.support_chat import rbac, rbac_admin, rbac_check

SYMBOL = {'block': 'BLOCK', 'warn': 'warn ', 'info': 'info '}


class Command(BaseCommand):
    help = ('Report support roles, check readiness for KG_SUPPORT_RBAC=enforce (both read-only), '
            'and grant or revoke roles (dry run unless --apply).')

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest='action', required=True)
        sub.add_parser('report', help='list administrators and their support roles')
        chk = sub.add_parser('check', help='check readiness for enforcement')
        chk.add_argument('--for-enforce', action='store_true',
                         help='exit 1 when a blocking problem would lock support out')
        chk.add_argument('--json', action='store_true', help='machine-readable output')
        for name, text in (('grant', 'give an administrator a support role'),
                           ('revoke', 'remove a support role from an administrator')):
            change = sub.add_parser(name, help=text + ' (dry run unless --apply)')
            change.add_argument('--admin', required=True, help='administrator username')
            change.add_argument('--role', required=True, help='one of: ' + ', '.join(rbac.ROLE_NAMES))
            change.add_argument('--apply', action='store_true', help='make the change (default is a dry run)')

    def handle(self, *args, action, **opts):
        try:
            if action == 'report':
                return self._report()
            if action in ('grant', 'revoke'):
                return self._change(action, opts)
            return self._check(opts['for_enforce'], opts['json'])
        except SystemExit:
            raise
        except Exception as exc:                                  # never mistaken for a pass
            self.stderr.write(f'support_roles failed: {type(exc).__name__}: {exc}')
            raise SystemExit(2)

    def _report(self):
        rows = rbac_check.report_rows()
        self.stdout.write(f'{"id":>4}  {"username":<20} {"active":<6} {"env owner":<9} '
                          f'{"table roles":<28} {"last token use":<26} phone  support actions')
        for r in rows:
            self.stdout.write(
                f'{r["id"]:>4}  {r["username"]:<20} {str(r["active"]):<6} {str(r["env_owner"]):<9} '
                f'{",".join(r["table_roles"]) or "-":<28} {r["last_token_use"] or "never":<26} '
                f'{"yes" if r["phone_on_file"] else "no":<6} {r["support_actions"]}')
        self.stdout.write(f'{len(rows)} administrator(s). Nothing was changed.')

    def _change(self, action, opts):
        run = rbac_admin.grant if action == 'grant' else rbac_admin.revoke
        result = run(rbac_admin.get_store(), opts['admin'], opts['role'], apply=opts['apply'])
        if not result.ok:
            self.stderr.write(f'refused ({result.code}): {result.message}')
            raise SystemExit(1)
        self.stdout.write(result.message)
        if result.code.startswith('would_'):
            self.stdout.write('dry run: nothing was changed. Add --apply to make the change.')

    def _check(self, for_enforce, as_json):
        findings = rbac_check.run()
        blocks = rbac_check.blocking(findings)
        if as_json:
            self.stdout.write(json.dumps({
                'for_enforce': for_enforce, 'ready': not blocks,
                'findings': [f._asdict() for f in findings]}, ensure_ascii=False))
        else:
            for f in findings:
                self.stdout.write(f'[{SYMBOL[f.level]}] {f.message}')
            verdict = 'READY' if not blocks else f'NOT READY ({len(blocks)} blocking)'
            self.stdout.write(f'enforce readiness: {verdict}. Nothing was changed.')
        if for_enforce and blocks:
            raise SystemExit(1)
