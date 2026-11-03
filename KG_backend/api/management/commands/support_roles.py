"""Read-only support-role tooling (the owner-approved safety gate for RBAC).

    python manage.py support_roles report                 # who is who; no secrets
    python manage.py support_roles check                  # findings; always exits 0
    python manage.py support_roles check --for-enforce    # exits 1 if enforcing now would lock support out

Nothing here writes to the database, sends anything or changes a setting. Exit codes:
0 = fine (or only reporting), 1 = a blocking problem under --for-enforce, 2 = the check
itself failed (never to be read as a pass). Run ``check --for-enforce`` and get 0 BEFORE
setting KG_SUPPORT_RBAC=enforce. It is not part of any deployment step and does not touch
ordinary administrator access. Granting and revoking roles needs the role table
(migration B) and arrives with it.
Design: docs/superpowers/specs/2026-11-03-phase3-migration-and-rbac-design.md section 3.3.
"""
import json

from django.core.management.base import BaseCommand

from api.support_chat import rbac_check

SYMBOL = {'block': 'BLOCK', 'warn': 'warn ', 'info': 'info '}


class Command(BaseCommand):
    help = 'Report support roles and check readiness for KG_SUPPORT_RBAC=enforce (read-only).'

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest='action', required=True)
        sub.add_parser('report', help='list administrators and their support roles')
        chk = sub.add_parser('check', help='check readiness for enforcement')
        chk.add_argument('--for-enforce', action='store_true',
                         help='exit 1 when a blocking problem would lock support out')
        chk.add_argument('--json', action='store_true', help='machine-readable output')

    def handle(self, *args, action, **opts):
        try:
            if action == 'report':
                return self._report()
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
