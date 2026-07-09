"""Sync main_db (the Car catalog) with the per-car databases on disk.

Every valid per-car database file in ``Database_warehouse/`` (i.e. a car whose
crawl/ingest — its "database + RAG" work — is complete) gets a ``Car`` row so it
appears on the site, in the admin catalog, and can be granted to portal users.

Design goals (why this replaces the old hardcoded/prune version):

* Filesystem-driven, not a hardcoded list — new cars show up automatically as
  their database files land in the warehouse. No code edit per car.
* Additive + idempotent — safe to run repeatedly; existing rows are matched and
  only corrected in place, never duplicated.
* NON-DESTRUCTIVE — it NEVER deletes Car rows or access grants. A car whose file
  is temporarily missing/incomplete is simply skipped here and already hidden
  everywhere by ``car_db_ready``; its admin/company/user grants are preserved so
  they light back up the moment the file is healthy again. (The previous command
  hard-deleted rows *and* their grants, which is why cars vanished from the admin
  panel — that behaviour is intentionally gone.)
"""
import sqlite3

from django.core.management.base import BaseCommand

from api.rag import config
from api.access import car_db_ready
from api.models import Car

# Every manual currently in the fleet is a MY2025 Toyota/Lexus. Used only as a
# fallback when a stem is not in config.CAR_REGISTRY (which carries explicit years).
DEFAULT_YEAR = 2025


def db_is_valid(path):
    """Fast readiness check: the file opens as SQLite and carries a populated
    manual ``nodes`` tree (a root node + at least one content leaf).

    Uses ``LIMIT 1`` probes so it stays fast even on multi-hundred-MB files, and
    treats a malformed / partially-uploaded / locked file as *not* ready (so an
    in-flight upload never produces a broken catalog row)."""
    try:
        conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    except sqlite3.Error:
        return False
    try:
        cur = conn.cursor()
        has_nodes = cur.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='nodes' LIMIT 1"
        ).fetchone()
        if not has_nodes:
            return False
        root = cur.execute(
            "SELECT 1 FROM nodes WHERE node_type='root' AND depth=1 LIMIT 1"
        ).fetchone()
        leaf = cur.execute(
            "SELECT 1 FROM nodes WHERE content IS NOT NULL LIMIT 1"
        ).fetchone()
        return bool(root and leaf)
    except sqlite3.DatabaseError:
        # malformed image / truncated partial upload
        return False
    finally:
        conn.close()


class Command(BaseCommand):
    help = ('Import/refresh a Car row for every valid per-car database in '
            'Database_warehouse/. Additive and idempotent; never deletes grants.')

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report what would change without writing to the database.')

    def handle(self, *args, **opts):
        dry = opts['dry_run']
        added = updated = unchanged = skipped = 0

        for path in config.car_db_files():
            stem = path.stem
            if not db_is_valid(path):
                skipped += 1
                self.stdout.write(self.style.WARNING(
                    f'skip (not ready / malformed): {stem}'))
                continue

            meta = config.car_meta(stem)
            brand = meta['brand']
            year = meta['year'] or DEFAULT_YEAR
            db_address = f'./Database_warehouse/{stem}.db'

            # Match on the on-disk stem (car_name), which is the stable identity
            # of a car row and is what db_address is derived from. This keeps the
            # existing rows (and every grant that FKs to them) intact.
            car = Car.objects.filter(car_name=stem).first()
            if car is None:
                added += 1
                if dry:
                    self.stdout.write(f'would add: {brand} / {stem} / {year}')
                else:
                    Car.objects.create(brand_name=brand, car_name=stem,
                                       year=year, db_address=db_address)
                    self.stdout.write(self.style.SUCCESS(f'added: {brand} / {stem}'))
                continue

            changed = []
            if car.db_address != db_address:
                car.db_address = db_address
                changed.append('db_address')
            if not car.brand_name:
                car.brand_name = brand
                changed.append('brand_name')
            if not car.year:
                car.year = year
                changed.append('year')
            if changed:
                updated += 1
                if not dry:
                    car.save(update_fields=changed)
                self.stdout.write(f'updated {stem}: {", ".join(changed)}')
            else:
                unchanged += 1

        total = Car.objects.count()
        ready = sum(1 for c in Car.objects.all() if car_db_ready(c))
        verb = 'would be' if dry else 'now'
        self.stdout.write(self.style.SUCCESS(
            f'\ncatalog sync: +{added} added, {updated} updated, '
            f'{unchanged} unchanged, {skipped} skipped (not ready). '
            f'main_db {verb} at {total} rows ({ready} ready on disk).'))
