"""Pipeline scheduler/watchdog — run every few minutes from a systemd timer:

    python manage.py pipeline_tick

Each pass: marks dead workers' jobs 'stalled', auto-resumes them (bounded
attempts), starts jobs whose scheduled time arrived, and — when auto mode is
on, pending work exists and the server is quiet — starts processing of newly
landed data with no human involved.
"""
from django.core.management.base import BaseCommand

from api import pipeline


class Command(BaseCommand):
    help = 'Pipeline watchdog + scheduler + auto-start (systemd timer entrypoint).'

    def handle(self, *args, **opts):
        did = pipeline.tick()
        parts = []
        if did['stalled']:
            parts.append(f"stalled: {did['stalled']}")
        if did['resumed']:
            parts.append(f"resumed: {did['resumed']}")
        if did['started_scheduled']:
            parts.append(f"started scheduled: {did['started_scheduled']}")
        if did['auto_started']:
            parts.append('auto-started new job')
        self.stdout.write('; '.join(parts) if parts else 'nothing to do')
