"""Fast real-time detector — runs on a short timer (kgkg-detect.timer, ~30s).

Its only job is to notice when the "what still needs processing" picture changes
(new vehicle data landed, a job advanced, embeddings caught up) and emit an
admin event so the dashboard reflects it within seconds — without every SSE
connection having to recompute the picture itself. Cheap: a few counts + one
directory scan. Idempotent and safe to run concurrently with the pipeline (it
only reads + appends one event when something actually changed).
"""
from django.core.management.base import BaseCommand

from api import events


class Command(BaseCommand):
    help = 'Detect processing-state changes and emit real-time events.'

    def handle(self, *args, **opts):
        etype = events.detect_and_emit()
        if etype:
            self.stdout.write(f'emitted {etype}')
        else:
            self.stdout.write('no change')
