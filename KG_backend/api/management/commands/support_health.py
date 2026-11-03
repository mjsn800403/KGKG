"""Read-only: how long visitors have waited for a human reply.

    python manage.py support_health [--json] [--fail-on warn|crit]

Never writes, sends or alerts. Exit 0 = fine (or no --fail-on), 1 = the queue is at or past
the --fail-on level, 2 = the command itself failed (never to be read as a pass). Thresholds:
KG_SUPPORT_WAIT_WARN_S (default 300) and KG_SUPPORT_WAIT_CRIT_S (default 900).
"""
import json

from django.core.management.base import BaseCommand

from api.support_chat import health

RANK = {'ok': 0, 'warn': 1, 'crit': 2}


class Command(BaseCommand):
    help = 'Report visitors waiting for a human reply (read-only).'

    def add_arguments(self, parser):
        parser.add_argument('--json', action='store_true')
        parser.add_argument('--fail-on', choices=('warn', 'crit'))

    def handle(self, *args, **opts):
        try:
            data = health.report()
        except Exception as exc:                                  # never mistaken for a pass
            self.stderr.write(f'support_health failed: {type(exc).__name__}: {exc}')
            raise SystemExit(2)
        if opts['json']:
            self.stdout.write(json.dumps(data, ensure_ascii=False))
        else:
            self.stdout.write(f'[{data["level"]}] {data["waiting"]} waiting, oldest {data["oldest_wait_s"]}s '
                              f'(warn {data["warn_after_s"]}s, crit {data["crit_after_s"]}s) '
                              f'by intent {data["waiting_by_intent"] or "-"}. Nothing was changed.')
        if opts['fail_on'] and RANK[data['level']] >= RANK[opts['fail_on']]:
            raise SystemExit(1)
