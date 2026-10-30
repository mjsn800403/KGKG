"""PostgreSQL per-vehicle databases (cardb_pg): SQL translation, rows, routing.

    cd KG_backend
    DJANGO_DEBUG=true .venv/bin/python manage.py test api.test_cardb_pg -v 2
"""
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from api import cardb, cardb_pg

CAR = 'GR86 Premium, Standard Trans.db'


class TranslateTest(unittest.TestCase):
    def test_placeholders(self):
        self.assertEqual(cardb_pg.translate('SELECT * FROM nodes WHERE id = ?'),
                         'SELECT * FROM nodes WHERE id = %s')

    def test_like_on_twinned_columns_uses_the_lowercase_twin(self):
        self.assertEqual(cardb_pg.translate("title LIKE ? ESCAPE '\\' OR n.content LIKE ?"),
                         "title_lc LIKE lower(%s) ESCAPE '\\' OR n.content_lc LIKE lower(%s)")

    def test_other_like_becomes_ilike(self):
        self.assertEqual(cardb_pg.translate('WHERE x.other LIKE ?'), 'WHERE x.other ILIKE %s')

    def test_printf_zero_pad(self):
        self.assertEqual(cardb_pg.translate("printf('%08d', n.sort_order)"),
                         "lpad((n.sort_order)::text, 8, '0')")

    def test_literal_percent_is_escaped_for_psycopg(self):
        self.assertEqual(cardb_pg.translate("SELECT 'a%b'"), "SELECT 'a%%b'")


class RowTest(unittest.TestCase):
    def test_behaves_like_sqlite_row(self):
        r = cardb_pg.Row({'id': 0, 'title': 1}, ('n1', 'Brakes'))
        self.assertEqual((r[0], r['title']), ('n1', 'Brakes'))
        self.assertEqual(dict(zip(r.keys(), r)), {'id': 'n1', 'title': 'Brakes'})
        self.assertEqual(dict(r), {'id': 'n1', 'title': 'Brakes'})


class RoutingTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, CAR)
        c = sqlite3.connect(self.path)
        c.execute('CREATE TABLE nodes (id TEXT)')
        c.commit(); c.close()
        cardb._tls.__dict__.clear(); cardb_pg._tls.__dict__.clear()

    def tearDown(self):
        cardb._tls.__dict__.clear(); cardb_pg._tls.__dict__.clear()
        self.dir.cleanup()

    def test_names_with_commas_are_listed_with_pipes(self):
        with mock.patch.dict(os.environ, {'KG_CARDB_PG': f'{CAR}|Other.db'}):
            self.assertEqual(cardb_pg.pg_cars(), {CAR, 'Other.db'})

    def test_unlisted_car_stays_on_sqlite(self):
        with mock.patch.dict(os.environ, {'KG_CARDB_PG': 'Other.db'}):
            self.assertIsInstance(cardb.connect(self.path), sqlite3.Connection)

    def test_listed_car_goes_to_postgres(self):
        fake = object()
        with mock.patch.dict(os.environ, {'KG_CARDB_PG': CAR}), \
                mock.patch.object(cardb_pg, 'PgCarConn', return_value=fake):
            self.assertIs(cardb.connect(self.path), fake)

    def test_unreachable_postgres_falls_back_to_sqlite(self):
        with mock.patch.dict(os.environ, {'KG_CARDB_PG': CAR}), \
                mock.patch.object(cardb_pg, 'PgCarConn', side_effect=OSError('down')):
            self.assertIsInstance(cardb.connect(self.path), sqlite3.Connection)

    def test_schema_name_is_stable_and_safe(self):
        s = cardb_pg.schema_for(CAR)
        self.assertRegex(s, r'^car_[0-9a-f]{16}$')
        self.assertEqual(s, cardb_pg.schema_for(CAR))
