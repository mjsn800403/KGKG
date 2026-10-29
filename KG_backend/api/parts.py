"""Parts-catalog serving (کاتالوگ قطعات یدکی).

Mirrors the manuals serving path (views.car_view) for a different warehouse:
per-vehicle parts DBs under ``Database_warehouse/_parts/<car_name>.db`` built
by ``manage.py import_parts``. Same auth order as manual content, but the
required grant layer is the ``parts`` package specifically — a car granted
without the parts layer stays 403 here even though the manual side would open.

Tree walking mirrors the manuals' ``?seg=`` semantics (titles can contain a
literal "/", so segments ride as repeated query params, never as URL path).
An extra ``?cfg=<frame>`` dimension selects the vehicle configuration (frame /
model code) whose group tree is being browsed — a parts catalog is per-frame
in the source EPC, unlike manuals.
"""
import json
import os
import re
import sqlite3
from pathlib import Path

from django.conf import settings
from django.http import JsonResponse

from . import cardb
from .access import user_car_documents
from .models import Car
from .portal import portal_user
from .ratelimit import rate_limited, require_admin_token

PARTS_DIRNAME = '_parts'

NODE_COLUMNS = """id, parent_id, path, title, node_type, file_type,
                  href, sort_order, depth, content"""


def parts_warehouse_dir():
    """Directory holding the per-vehicle parts DBs. Overridable for tests
    (settings.KG_PARTS_DIR / env KG_PARTS_DIR) because the default derives
    from the main DB location, which under test is ':memory:'."""
    override = getattr(settings, 'KG_PARTS_DIR', None) or os.environ.get('KG_PARTS_DIR')
    if override:
        return Path(override)
    main_dir = Path(settings.KG_DATA_DIR)
    return main_dir / 'Database_warehouse' / PARTS_DIRNAME


def parts_db_path(car):
    """Absolute path of a car's parts DB (exists only for parts vehicles)."""
    return parts_warehouse_dir() / f'{car.car_name}.db'


def parts_db_ready(car):
    """True when the car has a built parts DB on disk (TTL-cached stat)."""
    return cardb.ready_path(parts_db_path(car))


def get_parts_db(car):
    return cardb.connect(parts_db_path(car))


def _unauthorized():
    return JsonResponse({'error': 'unauthorized'}, status=401)


def _forbidden_car():
    return JsonResponse(
        {'error': 'forbidden',
         'detail': 'دسترسی به مستندات این خودرو در اشتراک شما نیست.'},
        status=403)


def _frame_dict(row):
    return {
        'code': row['code'], 'engine': row['engine'],
        'transmission': row['transmission'], 'steering': row['steering'],
        'destination': row['destination'], 'grade': row['grade'],
        'region': row['region'], 'date_from': row['date_from'],
        'date_to': row['date_to'], 'is_default': bool(row['is_default']),
        'n_groups': row['n_groups'], 'n_parts': row['n_parts'],
    }


def _leaf_payload(conn, node, car):
    g = conn.execute('SELECT * FROM groups WHERE id=?', (node['group_id'],)).fetchone()
    if g is None:
        return JsonResponse({'error': 'group data missing'}, status=500)
    sections = []
    for s in conn.execute("""
        SELECT id, section_index, figure_code, image_url, caption
        FROM sections WHERE group_id=? ORDER BY section_index""", (g['id'],)):
        parts = [{
            'callout': p['callout'], 'pn': p['pn'], 'pn_display': p['pn_display'],
            'name_en': p['name_en'], 'name_fa': p['name_fa'], 'qty': p['qty'],
            'qty_display': p['qty_display'],
            'note': p['note'], 'date_range': p['date_range'],
            'is_xref': bool(p['is_xref']),
        } for p in conn.execute("""
            SELECT callout, pn, pn_display, name_en, name_fa, qty, qty_display,
                   note, date_range, is_xref
            FROM part_rows WHERE section_id=? ORDER BY row_index""", (s['id'],))]
        # Callout landmarks (interactive highlight coordinates). Guarded so a
        # car DB built before this table existed degrades to "no hotspots"
        # instead of 500-ing; a rebuild backfills them.
        try:
            labels = [{
                'code': lab['code'], 'x': lab['x'], 'y': lab['y'],
                'w': lab['w'], 'h': lab['h'], 'title': lab['title'],
            } for lab in conn.execute("""
                SELECT code, x, y, w, h, title FROM section_labels
                WHERE section_id=? ORDER BY id""", (s['id'],))]
        except sqlite3.OperationalError:
            labels = []
        sections.append({
            'figure_code': s['figure_code'], 'caption': s['caption'],
            'image': s['image_url'], 'parts': parts, 'labels': labels,
        })
    resp = JsonResponse({
        'leaf': True,
        'group': {'label': g['label'], 'gid': g['gid'], 'frame': g['frame'],
                  'category': g['category'], 'category_fa': g['category_fa'],
                  'title': node['title'], 'path_titles': _title_chain(conn, node)},
        'sections': sections,
    })
    resp['Cache-Control'] = 'private, max-age=300'
    return resp


def _title_chain(conn, node):
    """Breadcrumb titles for a node, topmost group first (frame root excluded)."""
    chain = []
    cur = node
    while cur is not None and cur['parent_id'] is not None:
        chain.append(cur['title'])
        cur = conn.execute(
            f'SELECT {NODE_COLUMNS}, frame, group_id FROM nodes WHERE id=?',
            (cur['parent_id'],)).fetchone()
        if cur is not None and cur['depth'] == 0:
            break
    return list(reversed(chain))


def _node_dicts(rows):
    out = []
    for r in rows:
        out.append({
            'id': r['id'], 'parent_id': r['parent_id'], 'path': r['path'],
            'title': r['title'], 'node_type': r['node_type'],
            'file_type': r['file_type'], 'href': None,
            'sort_order': r['sort_order'], 'depth': r['depth'], 'content': None,
            'is_leaf': r['group_id'] is not None,
        })
    return out


# Deliberately generous: this is a grant-gated content endpoint (the manuals'
# car_view has no limit at all), and EVERY vehicle page server-renders one call
# to it — a tight bucket would be shared by all SSR traffic and 429 real users.
@rate_limited('parts', 600, 60)
def parts_view(request, brand_name, year, model_name):
    """GET /api/parts/<brand>/<year>/<model>/[?cfg=FRAME][&seg=..&seg=..]

    - no params        -> vehicle parts root: the frame (configuration) list
    - ?cfg=F           -> top-level group nodes of that frame's tree
    - ?cfg=F&seg=A...  -> walk the group tree by titles; a leaf answers with
                          the full parts payload (sections + rows)
    """
    # Authenticate FIRST: resolving the car before this would let an anonymous
    # caller tell a real (hidden) parts vehicle apart from a made-up name by
    # the 401-vs-404 difference.
    user = portal_user(request)
    if not user:
        return _unauthorized()

    # Tolerant car resolution — same rules as views.car_view case 3.
    base_qs = Car.objects.filter(
        brand_name__iexact=brand_name, car_name__iexact=model_name)
    try:
        car = base_qs.get(year=int(year))
    except (ValueError, TypeError, Car.DoesNotExist):
        car = base_qs.order_by('-year').first()
    if car is None:
        return JsonResponse({'error': 'car not found'}, status=404)

    # Paid content: the *parts* layer for THIS car — checked before readiness
    # so a granted-but-unbuilt vehicle can't be told from an ungranted one.
    docs = user_car_documents(user, car)
    if docs is None:
        return _forbidden_car()
    # Manual vehicles have no catalog of their own; the EPC catalogs are
    # separate "(Parts YYYY)" vehicles. Point at the matching one(s) instead.
    if not _is_parts_vehicle(car) and not parts_db_ready(car):
        return JsonResponse({'error': 'no_parts_catalog',
                             'related': _related_catalogs(user, car)},
                            status=404)
    if 'parts' not in docs:
        return _forbidden_car()

    if not parts_db_ready(car):
        return JsonResponse({'error': 'parts catalog not available on server'},
                            status=404)
    try:
        return _serve_parts(request, car)
    except FileNotFoundError:
        # The DB vanished between the readiness check and the open (rebuild).
        return JsonResponse({'error': 'parts catalog not available on server'},
                            status=404)
    except sqlite3.Error as e:
        return JsonResponse({'error': 'parts catalog unavailable',
                             'detail': str(e)}, status=503)


_PARTS_SUFFIX = re.compile(r'\s*\(Parts \d{4}\)\s*$', re.I)
_YEAR_SUFFIX = re.compile(r'\s*\(\d{4}\)\s*$')


def _is_parts_vehicle(car):
    return bool(_PARTS_SUFFIX.search(car.car_name or ''))


def _trim_base(name):
    """'Corolla Cross XLE, AWD (2023)' -> 'corolla cross xle'."""
    name = _YEAR_SUFFIX.sub('', _PARTS_SUFFIX.sub('', name or ''))
    return name.split(',')[0].strip().lower()


def _related_catalogs(user, car):
    """Parts vehicles of the same brand+year whose trim matches this manual
    vehicle: an exact trim match, else the longest whole-word prefix (so a
    'Corolla Cross Hybrid Nightshade' manual finds the 'Corolla Cross Hybrid'
    catalog, while 'Corolla Cross L' never matches 'Corolla Cross LE').
    Only catalogs the user may open are returned."""
    base = _trim_base(car.car_name)
    cands = []
    for pc in Car.objects.filter(brand_name__iexact=car.brand_name, year=car.year):
        if not _is_parts_vehicle(pc):
            continue
        pb = _trim_base(pc.car_name)
        if pb == base or base.startswith(pb + ' '):
            cands.append((len(pb), pc))
    if not cands:
        return []
    best = max(n for n, _ in cands)
    out = []
    for n, pc in cands:
        if n != best or not parts_db_ready(pc):
            continue
        docs = user_car_documents(user, pc)
        if docs is not None and 'parts' in docs:
            out.append({'brand': pc.brand_name, 'model': pc.car_name, 'year': pc.year})
    return out


SEARCH_LIMIT = 60


def _search_parts(conn, cfg, q):
    """Part rows of one configuration matching a part number (dashes/spaces
    ignored) or an English / Persian name fragment."""
    pn = re.sub(r'[\s-]+', '', q).upper()
    like = f'%{cardb.like_escape(q)}%'
    rows = conn.execute("""
        SELECT p.callout, p.pn, p.pn_display, p.name_en, p.name_fa, p.qty_display,
               p.date_range, n.id AS node_id
        FROM part_rows p
        JOIN sections s ON s.id = p.section_id
        JOIN groups g ON g.id = s.group_id
        JOIN nodes n ON n.id = g.node_id
        WHERE g.frame = ?
          AND ((? != '' AND REPLACE(REPLACE(UPPER(p.pn), '-', ''), ' ', '') LIKE ? ESCAPE '\\')
               OR p.name_en LIKE ? ESCAPE '\\' OR p.name_fa LIKE ? ESCAPE '\\')
        ORDER BY p.pn, p.id
        LIMIT ?""", (cfg, pn, cardb.like_escape(pn) + '%', like, like, SEARCH_LIMIT * 4)).fetchall()
    hits, seen, chains = [], set(), {}
    for r in rows:
        key = (r['pn'], r['node_id'])
        if key in seen:
            continue
        seen.add(key)
        if r['node_id'] not in chains:
            node = conn.execute(
                f'SELECT {NODE_COLUMNS}, frame, group_id FROM nodes WHERE id=?',
                (r['node_id'],)).fetchone()
            chains[r['node_id']] = _title_chain(conn, node) if node else []
        hits.append({
            'pn': r['pn'], 'pn_display': r['pn_display'], 'name_en': r['name_en'],
            'name_fa': r['name_fa'], 'qty_display': r['qty_display'],
            'callout': r['callout'], 'date_range': r['date_range'],
            'path_titles': chains[r['node_id']],
        })
        if len(hits) >= SEARCH_LIMIT:
            break
    return hits


def _serve_parts(request, car):
    conn = get_parts_db(car)

    cfg = (request.GET.get('cfg') or '').strip()
    frames = conn.execute('SELECT * FROM frames ORDER BY sort_order').fetchall()
    if not frames:
        return JsonResponse({'error': 'parts catalog empty'}, status=404)

    if not cfg:
        counts = {}
        meta = conn.execute("SELECT v FROM meta WHERE k='counts'").fetchone()  # noqa: E501
        if meta:
            try:
                counts = json.loads(meta['v'])
            except (ValueError, TypeError):
                counts = {}
        default = next((f['code'] for f in frames if f['is_default']),
                       frames[0]['code'])
        return JsonResponse({
            'car': {'brand': car.brand_name, 'model': car.car_name,
                    'year': car.year},
            'frames': [_frame_dict(f) for f in frames],
            'default_frame': default,
            'counts': counts,
        })

    if not any(f['code'] == cfg for f in frames):
        return JsonResponse({'error': f'unknown configuration: {cfg}'}, status=404)

    q = (request.GET.get('q') or '').strip()[:80]
    if q:
        if len(q) < 2:
            return JsonResponse({'query': q, 'results': []})
        return JsonResponse({'query': q, 'results': _search_parts(conn, cfg, q)})

    segments = request.GET.getlist('seg')

    if not segments:
        rows = conn.execute(f"""
            SELECT {NODE_COLUMNS}, frame, group_id FROM nodes
            WHERE frame=? AND depth=1 ORDER BY sort_order""", (cfg,)).fetchall()
        return JsonResponse(_node_dicts(rows), safe=False)

    # Walk by (parent, title) exactly like the manuals tree.
    node = conn.execute(f"""
        SELECT {NODE_COLUMNS}, frame, group_id FROM nodes
        WHERE frame=? AND depth=0 LIMIT 1""", (cfg,)).fetchone()
    if node is None:
        return JsonResponse({'error': 'configuration tree missing'}, status=404)
    for seg in segments:
        node = conn.execute(f"""
            SELECT {NODE_COLUMNS}, frame, group_id FROM nodes
            WHERE frame=? AND parent_id=? AND title=?
            ORDER BY sort_order LIMIT 1""", (cfg, node['id'], seg)).fetchone()
        if node is None:
            return JsonResponse(
                {'error': f'Path not found: {" / ".join(segments)}'}, status=404)

    if node['group_id'] is not None:
        return _leaf_payload(conn, node, car)

    rows = conn.execute(f"""
        SELECT {NODE_COLUMNS}, frame, group_id FROM nodes
        WHERE frame=? AND parent_id=? ORDER BY sort_order""",
        (cfg, node['id'])).fetchall()
    return JsonResponse(_node_dicts(rows), safe=False)


@require_admin_token
def admin_parts_summary_view(request):
    """GET /api/admin/parts/ — the import/audit summary for the parts module."""
    summary_path = parts_warehouse_dir() / 'report_summary.json'
    if not summary_path.is_file():
        return JsonResponse({'available': False, 'vehicles': {}})
    try:
        data = json.loads(summary_path.read_text(encoding='utf-8'))
    except (ValueError, OSError):
        return JsonResponse({'available': False, 'vehicles': {}})
    data['available'] = True
    # attach catalog ids so the admin UI can cross-link
    ids = {c.car_name: {'id': c.id, 'year': c.year}
           for c in Car.objects.filter(car_name__in=list(data.get('vehicles', {})))}
    for name, v in data.get('vehicles', {}).items():
        v['car'] = ids.get(name)
    return JsonResponse(data)
