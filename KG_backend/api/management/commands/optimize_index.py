"""Maintain the unified RAG index (SQLite-only; NO embedding model).

    python manage.py optimize_index            # ANALYZE + FTS/segment optimize
    python manage.py optimize_index --fts       # also rebuild the keyword index:
                                                # migrate it to the contentless +
                                                # porter-stemmer form (stops the
                                                # page text being stored twice and
                                                # makes brake≈brakes≈braking match)

Touches ONLY Database_warehouse/_rag/index.rag.db. Fast (seconds; --fts adds a
VACUUM to reclaim the freed text, which on the full index takes a minute or two).
Run it once to migrate an index built before the contentless-FTS change, and any
time after a build. Best run while the web server is stopped (VACUUM needs an
exclusive lock).
"""
from django.core.management.base import BaseCommand, CommandError

from api.rag import config, store


class Command(BaseCommand):
    help = 'ANALYZE + optimize the unified RAG index (optionally rebuild FTS).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--fts', action='store_true',
            help='Rebuild the keyword index (contentless + porter stemmer) and '
                 'VACUUM to reclaim the duplicated text.')

    def handle(self, *args, **opts):
        if not config.INDEX_DB.exists():
            raise CommandError(f"no index at {config.INDEX_DB} — build it first.")
        before = config.INDEX_DB.stat().st_size
        conn = store.open_index(write=True)
        try:
            if opts['fts']:
                self.stdout.write(self.style.MIGRATE_HEADING(
                    "=== rebuild keyword index (contentless + porter) ==="))
                store.rebuild_fts(conn, log=self.stdout.write)
                self.stdout.write("    VACUUM (reclaiming freed text) ...")
                conn.execute("VACUUM")
            self.stdout.write(self.style.MIGRATE_HEADING("=== optimize ==="))
            store.optimize(conn, log=self.stdout.write)
        finally:
            conn.close()
        # drop the cached serving connection so the next query reopens the
        # freshly-optimised index.
        store.reset_index_ro()
        after = config.INDEX_DB.stat().st_size
        self.stdout.write(self.style.SUCCESS(
            f"done. index size {before/1e6:.0f}MB -> {after/1e6:.0f}MB"))
