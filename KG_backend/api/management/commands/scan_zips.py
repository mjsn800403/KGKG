"""Discover vehicle-manual ZIPs in the inbox and register them in the parse
queue (ZipPackage rows).

    manage.py scan_zips --dry-run              # classify only, change nothing
    manage.py scan_zips --normalize            # also rename legacy model-only
                                               # filenames to KGTV convention
    manage.py scan_zips                        # register with current names

The duplicate guard marks ZIPs of already-ingested cars (or a second copy of
a queued car) as skipped_duplicate — they are listed but never parsed.
"""
from django.core.management.base import BaseCommand

from api import ingest
from api.models import ZipPackage


class Command(BaseCommand):
    help = 'Scan the ZIP inbox and register packages for the pipeline parse stage.'

    def add_arguments(self, parser):
        parser.add_argument('--normalize', action='store_true',
                            help='Rename legacy model-only ZIPs to '
                                 '"KGTV <year> <brand> <model>.zip" first.')
        parser.add_argument('--dry-run', action='store_true',
                            help='Report what would happen without renaming '
                                 'files or writing queue rows.')

    def handle(self, *args, **opts):
        summary = ingest.scan_inbox(normalize=opts['normalize'],
                                    dry_run=opts['dry_run'],
                                    log=self.stdout.write)
        verb = 'would be ' if opts['dry_run'] else ''
        self.stdout.write(self.style.SUCCESS(
            f"\nscan: {summary['found']} zip(s) found | "
            f"{summary['registered']} {verb}newly queued "
            f"({summary['renamed']} {verb}renamed) | "
            f"{summary['duplicates']} duplicate(s) skipped | "
            f"{summary['refreshed']} refreshed | "
            f"{summary['removed_missing']} vanished row(s) removed | "
            f"{len(summary['unrecognized'])} unrecognized"))
        if not opts['dry_run']:
            counts = {}
            for st in ZipPackage.objects.values_list('status', flat=True):
                counts[st] = counts.get(st, 0) + 1
            self.stdout.write('queue now: ' + ', '.join(
                f'{k}={v}' for k, v in sorted(counts.items())))
