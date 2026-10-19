"""Build a parts serving DB from a finished partsouq VIN crawl, and register the car.

Same schema as api/partsingest.build_vehicle_db (VEHICLE_DB_SCHEMA), so
api/parts.py serves it unchanged:
  frame root -> 4 EPC category folders -> one leaf group per diagram
  (1 section = the diagram image, part_rows from the "Spare parts" list,
  section_labels from the diagram hotspots).

The crawl folder is named <Model>_<year>_<frame>_<VIN> (partsouq_crawler.parse_url).
Output: Database_warehouse/_parts/<car name>.db, diagram images copied into
static_warehouse/_parts_assets with a per-VIN prefix. Diagram images are kept
as crawled (the PARTSOUQ watermark is not removed here).
"""
import html as H
import os
import re
import shutil
import sqlite3
import time
from pathlib import Path

from django.conf import settings

from . import partsouq_crawler
from .partsingest import (CATEGORY_FA, CATEGORY_ORDER, SCHEMA_VERSION, VEHICLE_DB_SCHEMA,
                          load_fa_terms, nfkc, sha1)

MEDIA = '/media/_parts_assets'
FOLDER = re.compile(r'(?P<model>[A-Za-z0-9]+)_(?P<year>\d{4})_(?P<frame>[A-Za-z0-9-]+)_(?P<vin>[A-HJ-NPR-Z0-9]{17})')
CAR_NAME = re.compile(r'[\w ()\-.]{3,80}')


class BuildError(Exception):
    pass


def _text(s):
    return re.sub(r'\s+', ' ', H.unescape(re.sub(r'<[^>]+>', ' ', s or ''))).strip()


def _attrs(tag):
    return {k: H.unescape(v) for k, v in re.findall(r'data-([a-z-]+)="([^"]*)"', tag)}


def parse_diagram(path):
    h = path.read_text(encoding='utf-8')
    title = _text((re.search(r'<h2 class="section-title diagram-title">(.*?)</h2>', h, re.S) or [None, ''])[1])
    img = re.search(r'id="diagramImage"[^>]*src="([^"]+)"', h)
    rows = []
    for b in re.split(r'(?=<div class="part-row")', h)[1:]:
        b = b.split('<div class="col-md-8', 1)[0]
        a = _attrs(re.match(r'<div[^>]*>', b).group(0))
        pn_disp = _text((re.search(r'class="part-number-link[^"]*"[^>]*>(.*?)</a>', b, re.S) or [None, ''])[1])
        name = _text((re.search(r'class="part-description">(.*?)</span>', b, re.S) or [None, ''])[1])
        pills = {H.unescape(k): H.unescape(v) for k, v in
                 re.findall(r'data-detail-label="([^"]*)" data-detail-value="([^"]*)"', b)}
        qd = pills.pop('Qty', '')
        m = re.match(r'^0*(\d{1,3})$', qd)
        date = pills.pop('Date', '').replace(' » ', ' - ')
        pills.pop('Code', None)
        note = '; '.join(f'{k}: {v}' for k, v in pills.items() if v)
        rows.append(dict(callout=a.get('callout', ''), pn=a.get('part-number') or pn_disp.replace('-', ''),
                         pn_display=pn_disp, name_en=name, qty=int(m.group(1)) if m else None,
                         qty_display=qd, note=note, date_range=date))
    labels = []
    for tag in re.findall(r'<div[^>]+class="hotspot"[^>]*>', h):
        d = _attrs(tag)
        try:
            labels.append(dict(code=d.get('code', ''), x=int(float(d['x'])), y=int(float(d['y'])),
                               w=int(float(d['width'])), h=int(float(d['height'])),
                               title=f"{d.get('number', '')} {d.get('description', '')}".strip()))
        except (KeyError, ValueError):
            pass
    return title, (img.group(1) if img else ''), rows, labels


def frame_info(crawl):
    t = _text((crawl / 'pages' / 'groups.html').read_text(encoding='utf-8'))

    def g(pat):
        return (re.search(pat, t) or [None, ''])[1].strip()
    return dict(engine=g(r'Engine:?\s+(\w+)'), transmission=g(r'Transmission\s+([A-Z]+ ?\w*)'),
                steering=g(r'Drivers Position\s+(\w+)'),
                destination=g(r'Destination Description:\s+([A-Z ]+?)(?:\s{2}|\s+Catalog|$)'),
                date=g(r'Production Date:\s+([\d-]+)'), catalog=g(r'Catalog Code\s+(\w+)'))


def build_db(crawl, car, grade, backend=None):
    """Write Database_warehouse/_parts/<car>.db from `crawl`. Returns the counts."""
    backend = Path(backend or settings.BASE_DIR)
    m = FOLDER.fullmatch(crawl.name)
    if not m:
        raise BuildError('folder name is not <Model>_<year>_<frame>_<VIN>')
    frame, vin = m['frame'], m['vin']
    prefix = f'ps_{vin.lower()}_'          # shared asset dir: keep our names unique
    out = backend / 'Database_warehouse' / '_parts' / f'{car}.db'
    assets = backend / 'static_warehouse' / '_parts_assets'
    fi = frame_info(crawl)
    fa = load_fa_terms(backend)
    out.parent.mkdir(parents=True, exist_ok=True)
    assets.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(out) + '.tmp')
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    db.executescript(VEHICLE_DB_SCHEMA)
    now = time.strftime('%Y-%m-%d %H:%M:%S')
    root_path = f'{car}/{frame}'
    root_id = sha1(root_path)
    ins = ('INSERT INTO nodes(id,parent_id,path,title,node_type,file_type,href,source_file,'
           'sort_order,depth,root_order,content,updated_at,frame,group_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)')
    db.execute(ins, (root_id, None, root_path, frame, None, 'root_path', None, None, 0, 0, 0, None, now, frame, None))
    counts = dict(groups=0, rows=0, labels=0, skipped=0)
    gid = 0
    for ci, cat in enumerate(CATEGORY_ORDER, start=1):
        cpath = f'{root_path}/{cat}'
        cid = sha1(cpath)
        db.execute(ins, (cid, root_id, cpath, cat, 'root', 'parts_folder', None, None, ci, 1, ci, None, now, frame, None))
        seen = set()
        for order, f in enumerate(sorted((crawl / 'pages').glob(f'diagram_c{ci}_*.html'))):
            title, img, rows, labels = parse_diagram(f)
            img_file = Path(img).name if img else ''
            src = crawl / 'images' / img_file
            if not rows or not img_file or not src.is_file() or src.stat().st_size == 0:
                counts['skipped'] += 1
                continue
            code = f.stem.split('_')[-1]
            label = title or code
            if label in seen:
                label = f'{label} ({code})'
            seen.add(label)
            dst = prefix + img_file
            if not (assets / dst).exists():
                shutil.copy2(src, assets / dst)
            gid += 1
            lpath = f'{cpath}/{label}'
            lid = sha1(lpath)
            db.execute(ins, (lid, cid, lpath, label, 'leaf', 'parts_group', None, f'{frame}/_groups/{f.stem}',
                             order, 2, None, None, now, frame, gid))
            db.execute('INSERT INTO groups(id,frame,gid,label,category,category_fa,node_id) VALUES (?,?,?,?,?,?,?)',
                       (gid, frame, int(code) if code.isdigit() else None, label, cat, CATEGORY_FA[cat], lid))
            fig = re.sub(r'^diagram_\w+?_', '', Path(img_file).stem)
            sid = db.execute('INSERT INTO sections(group_id,section_index,figure_code,image_url,caption) '
                             'VALUES (?,?,?,?,?)', (gid, 0, fig, f'{MEDIA}/{dst}', title)).lastrowid
            for i, r in enumerate(rows):
                db.execute('INSERT INTO part_rows(section_id,row_index,callout,pn,pn_display,name_en,name_fa,qty,'
                           'qty_display,note,date_range,is_xref) VALUES (?,?,?,?,?,?,?,?,?,?,?,0)',
                           (sid, i, r['callout'], r['pn'], r['pn_display'], r['name_en'],
                            fa.get(nfkc(r['name_en']).lower()) if r['name_en'] else None,
                            r['qty'], r['qty_display'], r['note'], r['date_range']))
            for lb in labels:
                db.execute('INSERT INTO section_labels(section_id,code,x,y,w,h,title) VALUES (?,?,?,?,?,?,?)',
                           (sid, lb['code'], lb['x'], lb['y'], lb['w'], lb['h'], lb['title']))
            counts['groups'] += 1
            counts['rows'] += len(rows)
            counts['labels'] += len(labels)
    if not counts['groups']:
        db.close()
        tmp.unlink(missing_ok=True)
        raise BuildError('no usable diagrams in this crawl')
    db.execute('INSERT INTO frames(code,engine,transmission,steering,destination,grade,region,date_from,date_to,'
               'sort_order,is_default,n_groups,n_parts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
               (frame, fi['engine'], fi['transmission'], fi['steering'], fi['destination'], grade, 'General',
                fi['date'].replace('-', ''), '', 0, 1, counts['groups'], counts['rows']))
    for k, v in [('schema_version', str(SCHEMA_VERSION)), ('built_at', now), ('source', str(crawl)),
                 ('car_name', car), ('counts', str(counts)), ('vin', vin), ('catalog_code', fi['catalog'])]:
        db.execute('INSERT INTO meta(k,v) VALUES (?,?)', (k, v))
    db.commit()
    db.close()
    os.replace(tmp, out)
    return counts


def build_and_register(folder, car_name, grade=''):
    """Admin action: build the DB from a finished crawl and add the car (parts only).

    Returns (result dict, error). Companies on an all-cars plan get the new car
    automatically (api/signals.py); everyone else is granted through the usual scope editor.
    """
    from .models import Car
    from . import cardb
    car_name = (car_name or '').strip()
    grade = (grade or '').strip()[:40]
    m = FOLDER.fullmatch(folder or '')
    if not m:
        return None, 'پوشهٔ خزش نامعتبر است.'
    if not CAR_NAME.fullmatch(car_name):
        return None, 'نام خودرو نامعتبر است (۳ تا ۸۰ حرف لاتین، عدد، فاصله یا پرانتز).'
    crawl = partsouq_crawler.OUT_ROOT / folder
    if not (crawl / 'pages' / 'groups.html').is_file():
        return None, 'این خزش صفحهٔ گروه‌ها را ندارد.'
    if partsouq_crawler.status()['running']:
        return None, 'تا پایان خزش صبر کنید یا آن را متوقف کنید.'
    try:
        counts = build_db(crawl, car_name, grade)
    except (BuildError, OSError, sqlite3.Error) as e:
        return None, f'ساخت پایگاه داده ناموفق بود: {e}'
    car, created = Car.objects.get_or_create(brand_name='Toyota', car_name=car_name, year=int(m['year']),
                                             defaults={'db_address': ''})
    cardb.invalidate_ready_cache()
    return {'car_id': car.id, 'created': created, 'counts': counts}, None
