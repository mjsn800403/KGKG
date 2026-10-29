"""Copy the portal data from the old SQLite file into PostgreSQL.

    KG_DB_ENGINE=postgres manage.py migrate
    KG_DB_ENGINE=postgres manage.py copy_sqlite_to_postgres /path/db.sqlite3 [--verify-only]

The target is the configured `default` database, which must be PostgreSQL and
fully migrated. Every model table (including auto-created many-to-many tables,
contenttypes, permissions and sessions) is emptied and refilled with the
source rows, primary keys preserved, then every sequence is moved past the
highest copied id. It is safe to re-run: each run is a full, idempotent
replace inside one transaction, so a failure leaves the target unchanged.

Rows are copied through the ORM so types convert correctly (SQLite stores
booleans as 0/1, datetimes and JSON as text). Two things make that a faithful
copy rather than a re-save:

  * auto_now / auto_now_add are switched off for the copy, otherwise every
    created_at/updated_at would become "now";
  * Django creates PostgreSQL foreign keys DEFERRABLE INITIALLY DEFERRED, so
    insertion order does not matter inside the single transaction; they are
    all checked at COMMIT.

Then it verifies: per-table row counts must match exactly, and the max id per
table must match. Any mismatch fails the command (non-zero exit).

Cutover without losing writes (ops/deploy/cutover_postgres.sh):

  1. full copy while the site runs on SQLite;
  2. a second copy right before the switch, with --reuse for the big
     immutable table (data-quality runs) so it takes seconds, writing
     --watermarks: the highest id of every append-only log table;
  3. switch the backend to PostgreSQL;
  4. --catchup <watermarks>: log rows the old SQLite backend wrote after the
     second copy (until it stopped) are appended with fresh ids. Log tables
     have no incoming foreign keys, so a new id breaks nothing.
"""
import json

import sqlite3
import time
from contextlib import contextmanager
from io import StringIO

from django.apps import apps
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction

SRC = 'sqlite_src'
# Append-only logs: nothing references them, so late rows can be appended with
# new ids after the switch (--catchup).
LOG_TABLES = ('api_activitylog', 'api_auditlog', 'api_chatlog', 'api_searchlog',
              'api_event', 'api_notificationlog', 'api_otpevent')
BATCH = 2000
MAX_BATCH_BYTES = 32 * 1024 * 1024


def _models():
    out = []
    for m in apps.get_models(include_auto_created=True):
        meta = m._meta
        if meta.proxy or not meta.managed:
            continue
        out.append(m)
    return out


@contextmanager
def _no_auto_timestamps(models):
    saved = []
    for m in models:
        for f in m._meta.concrete_fields:
            if getattr(f, 'auto_now', False) or getattr(f, 'auto_now_add', False):
                saved.append((f, f.auto_now, f.auto_now_add))
                f.auto_now = f.auto_now_add = False
    try:
        yield
    finally:
        for f, a, b in saved:
            f.auto_now, f.auto_now_add = a, b


def _src_tables(path):
    con = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    try:
        return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        con.close()


class Command(BaseCommand):
    help = 'Copy every portal table from a SQLite file into the PostgreSQL default DB.'

    def add_arguments(self, p):
        p.add_argument('sqlite_path')
        p.add_argument('--verify-only', action='store_true')
        p.add_argument('--reuse', action='append', default=[], metavar='TABLE',
                       help='keep this table as is when the target already has the same '
                            'row count and max id (immutable rows; repeatable)')
        p.add_argument('--watermarks', metavar='FILE',
                       help='after the copy, write the max id of each log table here')
        p.add_argument('--catchup', metavar='FILE',
                       help='append log rows newer than these watermarks; nothing else')

    def handle(self, sqlite_path, verify_only=False, reuse=(), watermarks=None,
               catchup=None, **o):
        target = connections['default']
        if target.vendor != 'postgresql':
            raise CommandError('the default database is not PostgreSQL (set KG_DB_ENGINE=postgres)')
        connections.settings[SRC] = {
            **connections.settings['default'],
            'ENGINE': 'django.db.backends.sqlite3', 'NAME': sqlite_path,
            'OPTIONS': {}, 'TEST': {}, 'CONN_MAX_AGE': 0, 'CONN_HEALTH_CHECKS': False,
            'HOST': '', 'PORT': '', 'USER': '', 'PASSWORD': '',
        }
        models = _models()
        present = _src_tables(sqlite_path)
        models = [m for m in models if m._meta.db_table in present]
        missing = sorted({m._meta.db_table for m in _models()} - present)
        if missing:
            self.stdout.write(f'tables not in the source (left empty): {", ".join(missing)}')

        if catchup:
            self._catchup(models, json.loads(open(catchup).read()))
            return
        if not verify_only:
            self._copy(models, set(reuse))
        ok = self._verify(models)
        if ok and watermarks:
            marks = {}
            for m in models:
                if m._meta.db_table in LOG_TABLES:
                    pk = m._meta.pk.attname
                    marks[m._meta.db_table] = (m._base_manager.using(SRC).order_by(f'-{pk}')
                                               .values_list(pk, flat=True).first() or 0)
            with open(watermarks, 'w') as fh:
                json.dump(marks, fh, indent=1)
            self.stdout.write(f'watermarks -> {watermarks}')
        if not ok:
            raise CommandError('verification FAILED: source and target differ')
        self.stdout.write(self.style.SUCCESS(f'verified {len(models)} tables: identical row counts and max ids'))

    def _same(self, m):
        pk = m._meta.pk.attname
        a, b = m._base_manager.using(SRC), m._base_manager.using('default')
        return (a.count() == b.count() and
                a.order_by(f'-{pk}').values_list(pk, flat=True).first()
                == b.order_by(f'-{pk}').values_list(pk, flat=True).first())

    def _copy(self, models, reuse=frozenset()):
        t0 = time.time()
        kept = {m for m in models if m._meta.db_table in reuse and self._same(m)}
        for m in kept:
            self.stdout.write(f'  {m._meta.db_table:40} reused (unchanged)')
        models_to_copy = [m for m in models if m not in kept]
        # no CASCADE: a kept table must not be emptied through a foreign key
        tables = ', '.join(f'"{m._meta.db_table}"' for m in models_to_copy)
        with transaction.atomic(using='default'), _no_auto_timestamps(models):
            with connections['default'].cursor() as cur:
                cur.execute(f'TRUNCATE {tables} RESTART IDENTITY' + ('' if kept else ' CASCADE'))
            for m in models_to_copy:
                t1 = time.time()
                n = 0
                qs = m._base_manager.using(SRC).order_by('pk')
                fields = m._meta.concrete_fields
                buf, size = [], 0
                for obj in qs.iterator(chunk_size=200):
                    obj._state.db = 'default'
                    buf.append(obj)
                    # flush by row count OR payload size: some rows (data
                    # quality runs) carry ~600 KB of JSON, and one INSERT
                    # statement is capped at 1 GB by PostgreSQL
                    size += sum(len(str(v)) for v in (getattr(obj, f.attname) for f in fields)
                                if isinstance(v, (str, dict, list)))
                    if len(buf) >= BATCH or size >= MAX_BATCH_BYTES:
                        m._base_manager.using('default').bulk_create(buf)
                        n += len(buf)
                        buf, size = [], 0
                if buf:
                    m._base_manager.using('default').bulk_create(buf)
                    n += len(buf)
                self.stdout.write(f'  {m._meta.db_table:40} {n:>8} rows  {time.time() - t1:6.1f}s')
            # sequences past the copied ids
            labels = sorted({m._meta.app_label for m in models})
            out = StringIO()
            call_command('sqlsequencereset', *labels, stdout=out, no_color=True)
            with connections['default'].cursor() as cur:
                cur.execute(out.getvalue())
        self.stdout.write(f'copied {len(models_to_copy)} tables in {time.time() - t0:.1f}s')

    def _catchup(self, models, marks):
        """Append log rows the SQLite backend wrote after the watermarks."""
        with transaction.atomic(using='default'), _no_auto_timestamps(models):
            for m in models:
                t = m._meta.db_table
                if t not in marks:
                    continue
                pk = m._meta.pk.attname
                late = list(m._base_manager.using(SRC).filter(**{f'{pk}__gt': marks[t]}).order_by(pk))
                for obj in late:
                    obj.pk = None
                    obj._state.db = 'default'
                    obj._state.adding = True
                if late:
                    m._base_manager.using('default').bulk_create(late)
                self.stdout.write(f'  {t:40} +{len(late)} late rows')
        self.stdout.write(self.style.SUCCESS('catch-up done'))

    def _verify(self, models):
        ok = True
        for m in models:
            src_qs = m._base_manager.using(SRC)
            dst_qs = m._base_manager.using('default')
            a, b = src_qs.count(), dst_qs.count()
            pk = m._meta.pk.attname
            ma = src_qs.order_by(f'-{pk}').values_list(pk, flat=True).first()
            mb = dst_qs.order_by(f'-{pk}').values_list(pk, flat=True).first()
            if a != b or ma != mb:
                ok = False
                self.stdout.write(self.style.ERROR(
                    f'  MISMATCH {m._meta.db_table}: rows {a} vs {b}, max id {ma} vs {mb}'))
        return ok
