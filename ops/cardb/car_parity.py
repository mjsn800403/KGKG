"""Byte-for-byte parity: car_view served from SQLite vs from PostgreSQL.

    cd KG_backend && python /root/pgpilot/car_parity.py "<car file>.db"

The real view function is called with identical requests in both modes
(access check stubbed; everything runs in a rolled-back transaction, so
nothing is written). Every JSON response must match exactly.
"""
import json, os, random, sqlite3, sys, time
sys.path.insert(0, '.')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'KG_backend.settings')
import django; django.setup()
from unittest import mock
from django.db import transaction
from django.test import RequestFactory
from api import views, cardb, cardb_pg
from api.models import Car

FILE = sys.argv[1]
car = next(c for c in Car.objects.all() if os.path.basename(c.db_address.replace('\\', '/')) == FILE)
path = os.path.join(str(views.settings.KG_DATA_DIR), car.db_address.replace('\\', '/'))
src = sqlite3.connect(f'file:{path}?mode=ro', uri=True); src.row_factory = sqlite3.Row
rng = random.Random(7)
nodes = src.execute('SELECT id, path, href, title, content IS NOT NULL leaf FROM nodes').fetchall()


def segs(p):
    return [s.replace('⁄', '/') for s in p.split('/')[1:]]


reqs = [{}, {'nav': '1'}]
for n in rng.sample(nodes, min(400, len(nodes))):
    reqs.append({'seg': segs(n['path'])})
for n in (lambda L: rng.sample(L, min(60, len(L))))([n for n in nodes if not n['leaf']]):
    reqs.append({'seg': segs(n['path']), 'subtree': '1'})
for n in (lambda L: rng.sample(L, min(60, len(L))))([n for n in nodes if n['href']]):
    reqs.append({'href': n['href']})
for q in ['brake', 'Brake Pad', 'torque', 'OIL', 'clutch', 'P0', 'sensor', 'wiper', 'bulb', 'coolant',
          'remove', 'INSTALL', 'fuse', 'airbag', 'harness', 'gasket', 'ECU', '100%', 'a_b', 'ترمز']:
    reqs.append({'q': q})
    reqs.append({'q': q, 'limit': '80'})

rf = RequestFactory()


def run(mode):
    os.environ['KG_CARDB_PG'] = FILE if mode == 'pg' else ''
    cardb._tls.__dict__.clear(); cardb_pg._tls.__dict__.clear()
    out, t = [], time.perf_counter()
    with mock.patch.object(views, 'portal_user', return_value=object()), \
            mock.patch.object(views, 'user_can_open_car', return_value=True):
        for p in reqs:
            r = rf.get('/x', p)
            try:
                with transaction.atomic():
                    resp = views.car_view(r, car.brand_name, str(car.year), car.car_name)
                    out.append((resp.status_code, resp.content))
                    raise RuntimeError('rollback')
            except RuntimeError:
                pass
    return out, time.perf_counter() - t


sq, t_sq = run('sqlite')
pg, t_pg = run('pg')
os.environ['KG_CARDB_PG'] = FILE
cardb._tls.__dict__.clear(); cardb_pg._tls.__dict__.clear()
assert isinstance(cardb.connect(path), cardb_pg.PgCarConn), 'PostgreSQL path not taken'
same = sum(a == b for a, b in zip(sq, pg))
diff = [(reqs[i], sq[i][0], pg[i][0], sq[i][1][:160], pg[i][1][:160])
        for i in range(len(reqs)) if sq[i] != pg[i]]
by_status = {}
for s, _ in sq:
    by_status[s] = by_status.get(s, 0) + 1
print(json.dumps({'car': FILE, 'requests': len(reqs), 'identical': same, 'different': len(diff),
                  'sqlite_status_counts': by_status, 'sqlite_s': round(t_sq, 1), 'pg_s': round(t_pg, 1)}, indent=2))
for d in diff[:8]:
    print('DIFF', d)
