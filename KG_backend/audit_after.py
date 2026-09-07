"""Independent check of what actually landed in the database."""
import os, django, sqlite3, json
from urllib.parse import unquote
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'KG_backend.settings')
django.setup()
from api.models import ActivityLog, PortalUser, Car
from api.access import user_car_documents, car_db_ready, car_db_path

m = json.load(open('reconstructed_activity_manifest.json'))
LO, HI = m['activitylog_id_min'], m['activitylog_id_max']
FRAC, MANUAL = '⁄', 'manual'

new = ActivityLog.objects.filter(id__gte=LO, id__lte=HI)
old = ActivityLog.objects.filter(id__lt=LO)
print("genuine rows (id < %d)   : %d   range %s .. %s" % (
    LO, old.count(),
    old.order_by('created_at').values_list('created_at', flat=True).first(),
    old.order_by('-created_at').values_list('created_at', flat=True).first()))
print("reconstructed rows       : %d   range %s .. %s" % (
    new.count(),
    new.order_by('created_at').values_list('created_at', flat=True).first(),
    new.order_by('-created_at').values_list('created_at', flat=True).first()))

# 1. genuine rows untouched: none of them carry the marker, and none moved in time
print("genuine rows carrying the marker      :", old.filter(detail__contains='بازسازی‌شده').count())
print("genuine rows dated before 2026-07-04  :", old.filter(created_at__lt='2026-07-04').count())
print("reconstructed rows missing the marker :", new.exclude(detail__contains='بازسازی‌شده').count())
print("reconstructed rows on/after 2026-07-04:", new.filter(created_at__gte='2026-07-04').count())

# 2. every actor genuinely holds the manual package for that car
perm = {}
for u in PortalUser.objects.select_related('company'):
    ok = set()
    for a in u.car_accesses.select_related('car'):
        d = user_car_documents(u, a.car)
        if d and MANUAL in d:
            ok.add(a.car_id)
    perm[u.id] = ok
viol = [l.id for l in new.exclude(car=None).only('id', 'user_id', 'car_id')
        if l.car_id not in perm.get(l.user_id, ())]
print("rows whose actor lacks manual access  :", len(viol))

# 3. every URL is inside the manual tree and resolves to a real node
roots = {}
def root_of(car):
    if car.id not in roots:
        con = sqlite3.connect("file:%s?mode=ro" % car_db_path(car), uri=True)
        r = con.execute("SELECT path FROM nodes WHERE depth=1 LIMIT 1").fetchone()
        con.close()
        roots[car.id] = r[0].rsplit('/', 1)[0] if r and '/' in r[0] else ''
    return roots[car.id]

outside = dead = checked = 0
for l in new.exclude(app_url='').select_related('car').order_by('id')[::7]:
    segs = l.app_url.strip('/').split('/')
    if len(segs) < 5 or unquote(segs[3]) not in ('Repair and Diagnosis', 'Repair and Diagnosis (Single Page)'):
        outside += 1
        continue
    tail = [unquote(s) for s in segs][3:]
    path = '/'.join([root_of(l.car)] + [s.replace('/', FRAC) for s in tail])
    con = sqlite3.connect("file:%s?mode=ro" % car_db_path(l.car), uri=True)
    hit = con.execute("SELECT 1 FROM nodes WHERE path=? LIMIT 1", (path,)).fetchone()
    con.close()
    checked += 1
    if not hit:
        dead += 1
print("URLs checked %d | outside the manual tree %d | not resolving to a node %d"
      % (checked, outside, dead))

# 4. no Labor Times (that is the standard_time package, not manual)
print("rows pointing at Labor Times          :", new.filter(app_url__contains='Labor%20Times').count())
print("truncated URLs (exactly 600 chars)    :", sum(1 for l in new.exclude(app_url='').only('app_url')
                                                     if len(l.app_url) == 600))
