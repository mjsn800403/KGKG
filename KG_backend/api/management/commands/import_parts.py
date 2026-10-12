"""manage.py import_parts — PartSouq crawl -> parts warehouse pipeline.

Stages (run individually or 'all'): scan, parse, validate, build, catalog, audit.
Staging + reports live OUTSIDE the warehouse (default /root/parts_build/).
Idempotent + resumable: parse skips unchanged pages, build rewrites vehicle DBs
atomically, catalog is get_or_create.
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from pathlib import Path

from ... import partsingest

STAGES = ['scan', 'parse', 'validate', 'build', 'catalog', 'audit']


class Command(BaseCommand):
    help = 'Import the PartSouq parts crawl into per-vehicle parts DBs.'

    def add_arguments(self, parser):
        parser.add_argument('--stage', default='all',
                            choices=STAGES + ['all'])
        parser.add_argument('--src', default='/root/Desktop/partsouq2')
        parser.add_argument('--staging', default='/root/parts_build/staging.db')
        parser.add_argument('--report-dir', default='/root/parts_build/reports')
        parser.add_argument('--frames', default='',
                            help='comma-separated frame codes (parse only)')
        parser.add_argument('--vehicles', default='',
                            help='comma-separated vehicle names (build only)')
        parser.add_argument('--jobs', type=int, default=4)
        parser.add_argument('--force', action='store_true',
                            help='re-parse pages even if unchanged')
        parser.add_argument('--allow-hard-issues', action='store_true',
                            help='let build proceed despite hard validation issues '
                                 '(affected groups are pruned anyway)')

    def handle(self, *args, **opts):
        src = opts['src']
        if not (Path(src) / 'downloads').is_dir():
            raise CommandError(f'source not found: {src}/downloads')
        backend_dir = Path(settings.DATABASES['default']['NAME']).parent
        conn = partsingest.staging_conn(opts['staging'])
        report_dir = opts['report_dir']
        log = self.stdout.write
        stages = STAGES if opts['stage'] == 'all' else [opts['stage']]
        frames = [f for f in opts['frames'].split(',') if f.strip()] or None
        vehicles = [v for v in opts['vehicles'].split(',') if v.strip()] or None

        for stage in stages:
            log(f'=== stage: {stage} ===')
            if stage == 'scan':
                partsingest.stage_scan(conn, src, report_dir, log=log)
            elif stage == 'parse':
                partsingest.stage_parse(conn, src, jobs=opts['jobs'],
                                        frames_filter=frames,
                                        force=opts['force'], log=log)
            elif stage == 'validate':
                partsingest.stage_validate(conn, src, report_dir, log=log)
            elif stage == 'build':
                stats = partsingest.stage_validate(conn, src, report_dir, log=log)
                if stats['hard_issues'] and not opts['allow_hard_issues']:
                    raise CommandError(
                        f"{stats['hard_issues']} hard validation issues — inspect "
                        f'{report_dir}/validate.md, then re-run with '
                        f'--allow-hard-issues to build with the affected groups pruned.')
                partsingest.stage_build(conn, src, backend_dir, report_dir,
                                        vehicles_filter=vehicles, log=log)
            elif stage == 'catalog':
                partsingest.stage_catalog(conn, backend_dir, log=log)
            elif stage == 'audit':
                summary = partsingest.stage_audit(conn, backend_dir, report_dir, log=log)
                if not summary['ok']:
                    raise CommandError('audit found problems — see report_summary.json')
        conn.commit()
        conn.close()
        log('done.')
