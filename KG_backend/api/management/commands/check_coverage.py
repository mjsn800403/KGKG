"""Audit diagnostic-engine and retrieval coverage per vehicle; alert on regression.

Intended to run on a timer (see kgkg-coverage.timer):

    python manage.py check_coverage            # compare against the stored baseline
    python manage.py check_coverage --baseline # (re)write the baseline from current state

Phase 4 Task 4. A rebuild that silently drops vehicles, or empties a sidecar,
must surface as an alert rather than as an evaluator's finding. Coverage is a
published claim in the dossier (216/221 substantive), so a regression is a
correctness bug, not just an ops event.

Baseline lives beside the index at _rag/coverage_baseline.json.
"""
import json
import glob
import os
import sqlite3

from django.core.management.base import BaseCommand

from api import monitoring
from api.rag import config

# A vehicle counts as "substantively covered" above this many DTC rows.
# Deliberately low: the point is to catch a sidecar going empty, not to grade
# vehicles whose manufacturer publishes less (bZ4X at 110 is legitimate).
DTC_FLOOR = 10
# Fractional drop against baseline that constitutes a regression.
DROP_FRAC = 0.10


def _close_own_alert():
    from django.utils import timezone
    from api.models import SystemAlert
    SystemAlert.objects.filter(key='coverage_regression', is_open=True).update(
        is_open=False, resolved_at=timezone.now())


def _measure():
    """Current per-vehicle counts: dtc, symptom (sidecars) and occurrences (index)."""
    warehouse = config.INDEX_DB.parent.parent
    diag_dir = config.INDEX_DB.parent / 'diag'
    occ = {}
    try:
        idx = sqlite3.connect('file:%s?mode=ro' % config.INDEX_DB, uri=True)
        occ = dict(idx.execute(
            'SELECT car_stem, COUNT(*) FROM occurrences GROUP BY car_stem'))
        idx.close()
    except Exception:
        pass
    cars = {}
    for path in sorted(glob.glob(str(diag_dir / '*.diag.db'))):
        stem = os.path.basename(path)[:-8]
        d = s = 0
        try:
            c = sqlite3.connect('file:%s?mode=ro' % path, uri=True)
            d = c.execute('SELECT COUNT(*) FROM dtc').fetchone()[0]
            s = c.execute('SELECT COUNT(*) FROM symptom').fetchone()[0]
            c.close()
        except Exception:
            pass
        cars[stem] = {'dtc': d, 'symptom': s, 'occurrences': occ.get(stem, 0)}
    return cars, warehouse


class Command(BaseCommand):
    help = 'Audit per-vehicle diagnostic/retrieval coverage; alert on regression.'

    def add_arguments(self, parser):
        parser.add_argument('--baseline', action='store_true',
                            help='Write the current state as the new baseline and exit.')

    def handle(self, *args, **opts):
        cars, _ = _measure()
        base_path = config.INDEX_DB.parent / 'coverage_baseline.json'
        covered = sum(1 for v in cars.values() if v['dtc'] >= DTC_FLOOR)

        if opts['baseline']:
            base_path.write_text(json.dumps(
                {'cars': cars, 'covered': covered}, indent=1), encoding='utf-8')
            self.stdout.write(self.style.SUCCESS(
                'baseline written: %d vehicles, %d substantively covered'
                % (len(cars), covered)))
            return

        if not base_path.exists():
            self.stdout.write(self.style.WARNING(
                'no baseline yet - run: manage.py check_coverage --baseline'))
            return

        base = json.loads(base_path.read_text(encoding='utf-8'))
        prev, prev_covered = base['cars'], base['covered']

        missing = sorted(set(prev) - set(cars))
        emptied, dropped = [], []
        for stem, was in prev.items():
            now = cars.get(stem)
            if not now:
                continue
            if was['dtc'] >= DTC_FLOOR > now['dtc']:
                emptied.append(stem)
            for metric in ('dtc', 'symptom', 'occurrences'):
                if was[metric] and now[metric] < was[metric] * (1 - DROP_FRAC):
                    dropped.append('%s:%s %d->%d'
                                   % (stem, metric, was[metric], now[metric]))

        problems = bool(missing or emptied or dropped)
        if problems:
            parts = []
            if missing:
                parts.append('%d vehicle(s) gone: %s' % (len(missing), ', '.join(missing[:5])))
            if emptied:
                parts.append('%d sidecar(s) emptied: %s' % (len(emptied), ', '.join(emptied[:5])))
            if dropped:
                parts.append('%d count drop(s): %s' % (len(dropped), '; '.join(dropped[:5])))
            monitoring._raise_alert(
                'coverage_regression',
                'critical' if (missing or emptied) else 'warning',
                'Vehicle coverage regressed: ' + ' | '.join(parts),
                {'missing': missing, 'emptied': emptied, 'dropped': dropped[:50],
                 'covered_now': covered, 'covered_baseline': prev_covered})
            self.stdout.write(self.style.ERROR('REGRESSION: ' + ' | '.join(parts)))
        else:
            # evaluate_alerts() only auto-resolves the keys it owns, so this
            # component closes its own alert when the condition clears.
            _close_own_alert()
            self.stdout.write(self.style.SUCCESS(
                'coverage ok: %d vehicles, %d substantively covered (baseline %d)'
                % (len(cars), covered, prev_covered)))
