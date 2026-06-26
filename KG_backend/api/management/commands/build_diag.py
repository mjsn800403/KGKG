"""Build (or rebuild) the per-car DIAGNOSTIC SIDECARS — the DTC / symptom rule
-engine layer that sits on top of the unified RAG index.

    python manage.py build_diag                  # all cars on disk
    python manage.py build_diag --car "bZ4X XLE, FWD"   # one car (repeatable)
    python manage.py build_diag --rebuild        # wipe each sidecar first
    python manage.py build_diag --pilot bZ4X     # only cars of one model

Reads each car DB read-only (verifies they are byte-identical afterwards) plus
the unified index for labor/cross-vehicle links. Writes ONLY to
Database_warehouse/_rag/diag/. Run this AFTER build_rag (it reuses the same
bge-m3 embeddings and the unified index's edges).
"""
import time
import hashlib
from django.core.management.base import BaseCommand, CommandError

from api.rag import config, diag_build


def _checksums():
    out = {}
    for f in config.car_db_files():
        h = hashlib.sha256()
        with open(f, 'rb') as fh:
            for blk in iter(lambda: fh.read(1 << 20), b''):
                h.update(blk)
        out[f.name] = (f.stat().st_size, h.hexdigest())
    return out


class Command(BaseCommand):
    help = 'Build per-car diagnostic sidecars (DTC / symptom rule engine).'

    def add_arguments(self, parser):
        parser.add_argument('--car', action='append', default=[],
                            help='Car stem (DB filename without .db). Repeatable.')
        parser.add_argument('--pilot', help='Only cars whose model matches (e.g. "bZ4X").')
        parser.add_argument('--rebuild', action='store_true', help='Wipe each sidecar first.')

    def handle(self, *args, **opts):
        config.DIAG_DIR.mkdir(parents=True, exist_ok=True)
        t0 = time.time()

        self.stdout.write(self.style.MIGRATE_HEADING("=== safety: checksumming original car DBs ==="))
        pre = _checksums()
        self.stdout.write(f"  {len(pre)} originals snapshotted")

        stems = [f.stem for f in config.car_db_files()]
        if opts['car']:
            want = set(opts['car'])
            stems = [s for s in stems if s in want]
            missing = want - set(stems)
            if missing:
                raise CommandError(f"unknown car stem(s): {sorted(missing)}")
        if opts['pilot']:
            stems = [s for s in stems
                     if opts['pilot'].lower() in config.car_meta(s)['model'].lower()]
        if not stems:
            raise CommandError("no matching cars on disk.")

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"=== building diagnostic sidecars for {len(stems)} car(s) ==="))
        self.stdout.write(f"  embedding model: {config.EMBED_MODEL} (dim={config.EMBED_DIM})")

        totals = {'dtc': 0, 'symptoms': 0, 'links': 0}
        for s in stems:
            stats = diag_build.build_car(s, rebuild=opts['rebuild'], log=self.stdout.write)
            for kk in totals:
                totals[kk] += stats[kk]

        self.stdout.write(self.style.MIGRATE_HEADING("=== safety: re-checksumming originals ==="))
        post = _checksums()
        changed = [n for n in pre if pre[n] != post.get(n)]
        if changed:
            self.stdout.write(self.style.ERROR(f"  !! ORIGINALS CHANGED: {changed}"))
        else:
            self.stdout.write(self.style.SUCCESS(f"  all {len(pre)} original DBs byte-identical (untouched)."))

        self.stdout.write(self.style.SUCCESS(
            f"\nDiagnostic build complete in {time.time()-t0:.0f}s — "
            f"DTCs={totals['dtc']}  symptoms={totals['symptoms']}  links={totals['links']}."))
