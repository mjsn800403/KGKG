"""Audit the vehicle warehouse: duplicates, completeness, pending processes.

    python manage.py audit_vehicles               # scan + persist report
    python manage.py audit_vehicles --fix         # also apply safe remediations
    python manage.py audit_vehicles --json        # dump full report to stdout

Fix mode is deliberately conservative: corrupt files and confirmed duplicate
copies are MOVED to Database_warehouse/_quarantine/ (never deleted), duplicate
catalog rows are merged with their grants and activity history repointed at
the surviving row, and stray WAL sidecars are checkpointed. Anything ambiguous
is only flagged.
"""
import json

from django.core.management.base import BaseCommand

from api import dataquality


class Command(BaseCommand):
    help = 'Audit (and optionally auto-fix) the per-vehicle databases.'

    def add_arguments(self, parser):
        parser.add_argument('--fix', action='store_true',
                            help='Apply safe automatic remediations.')
        parser.add_argument('--json', action='store_true',
                            help='Print the full report as JSON.')

    def handle(self, *args, **opts):
        run = None

        def log(msg):
            self.stdout.write(f'  {msg}')

        self.stdout.write(self.style.MIGRATE_HEADING('=== vehicle warehouse audit ==='))
        summary, vehicles, actions = dataquality.run_audit(fix=opts['fix'], log=log)

        # Persist so the admin panel shows this run.
        from api.models import DataQualityRun
        from django.utils import timezone
        run = DataQualityRun.objects.create(
            status='done', summary=summary, vehicles=vehicles, actions=actions,
            finished_at=timezone.now())

        if opts['json']:
            self.stdout.write(json.dumps(
                {'summary': summary, 'vehicles': vehicles, 'actions': actions},
                indent=1, ensure_ascii=False, default=str))
            return

        s = summary
        self.stdout.write('')
        self.stdout.write(f"vehicles on disk : {s['total_dbs']}  (catalog rows: {s['catalog_rows']})")
        self.stdout.write(f"complete         : {s['complete']}")
        self.stdout.write(f"incomplete       : {s['incomplete']}")
        self.stdout.write(f"corrupt          : {s['corrupt']}")
        self.stdout.write(f"duplicates       : {len(s['duplicates'])}")
        self.stdout.write(f"rag indexed      : {s['rag_indexed']}/{s['total_dbs']}")
        self.stdout.write(f"diag indexed     : {s['diag_indexed']}/{s['total_dbs']}")
        for v in vehicles:
            if v['status'] == 'complete':
                continue
            self.stdout.write(f"\n[{v['status'].upper()}] {v['stem']}")
            if v.get('error'):
                self.stdout.write(f"    error: {v['error']}")
            if v.get('missing_sections'):
                self.stdout.write(f"    missing sections: {', '.join(v['missing_sections'])}")
            if v.get('empty_sections'):
                self.stdout.write(f"    empty sections: {', '.join(v['empty_sections'])}")
            if v.get('pending_processes'):
                self.stdout.write(f"    pending: {', '.join(v['pending_processes'])}")
        if actions:
            self.stdout.write(self.style.MIGRATE_HEADING('\n=== fix actions ==='))
            for a in actions:
                self.stdout.write(f"  {a['action']}: {a.get('stem') or a.get('removed', '')}"
                                  f" {a.get('detail', '')}")
        self.stdout.write(self.style.SUCCESS(f'\nreport persisted (run #{run.id})'))
