"""Per-vehicle "SST" (Special Service Tools) CSV export.

Every system in a car's manual carries its own ``SST [<date window>]`` page: a
four-column table of the special tools that system's procedures require
(picture, tool number, tool name, note). A car has ~40 such pages, so a
technician who wants "the tool list for this vehicle" would otherwise have to
open forty pages and merge them by hand. This module does that merge once and
serves it as a single CSV from the car's front page, alongside the Labor Times
export.

Two properties of the source data shape the whole module:

**The same page is reachable by several paths.** A system sits under more than
one category — Park Assist appears under both ``Collision⁄Avoidance`` and
``Drivers Assistance Systems - ADAS`` — so the crawl stored the identical leaf
several times. Across the fleet ~40 SST leaves per car hold only ~23 distinct
bodies, and flattening them naively repeats most tools four or five times. The
export is therefore keyed on the **tool number**: one row per tool, with the
systems that call for it collected into a ``used_in`` column. That column is
the reason to aggregate at all — it answers "what do I need this tool for?",
which no single page can.

**Kit components are rows, not structure.** A tool set lists its parts as
ordinary rows whose number is parenthesised::

    09890-47010   Desktop Anti-Static Mat Set
    (09891-04010) Anti-Static Mat
    (09891-04020) Wrist Band

There is no ``rowspan`` or nesting to read — the only signal is the parentheses
and the row order. Components keep their own row (a shop may need to reorder
just the wrist band) and carry the parent's number in ``kit_of``, so the
grouping survives a sort in Excel.

The table shape was verified across the fleet before this was written: every
data row has exactly four ``<td>`` cells, no leaf uses ``<th>``, and the fourth
column has so far only ever held ``-`` — it is still exported rather than
dropped, since a note appearing later should not silently vanish.

Like :mod:`api.labortimes`, the core (:func:`build_csv`) depends only on
sqlite3 + BeautifulSoup so it can be tested against a raw car DB, and the
Django view wraps it in the same login + per-car access gate the manual content
endpoints use.
"""
import csv
import io
import re

from bs4 import BeautifulSoup

# Leaf and folder titles both start with "SST"; the date window follows.
SST_TITLE_PREFIX = 'SST'
# Titles embed a literal "/" as U+2044 FRACTION SLASH so the crawler's
# "/"-joined path column never splits mid-title. Restore it for display.
_FRACTION_SLASH = '⁄'
# The section root every SST page hangs under; dropped from the breadcrumb.
_SECTION_ROOT = 'Repair and Diagnosis'
# A page title's trailing date window, e.g. "SST [11/2021 - 03/2023]".
_DATE_WINDOW = re.compile(r'\[([^\]]*)\]\s*$')
# Tool numbers are 5-5 digits, sometimes with a letter suffix. Parentheses mark
# a component of the kit listed above it.
_TOOL_NUMBER = re.compile(r'^(\()?\s*(\d{5}-\d{5}[A-Z0-9-]*)\s*\)?$')
# Wrapper folders that describe the page kind, not the system.
_PREPARATION = ' (Preparation)'

CSV_HEADER = [
    'brand', 'car', 'year',
    'tool_number', 'tool_name', 'kit_of', 'note',
    'systems', 'used_in', 'date_range', 'image',
]


def _clean(seg):
    return (seg or '').replace(_FRACTION_SLASH, '/').strip()


def _system_of(path, stem):
    """Return ``(group, system, date_range)`` for one SST leaf ``path``.

    The tail of an SST path repeats itself — ``… /Lighting (Ext)/SST [w]/SST
    [w]`` — so the system name is the last segment that is not an SST page and
    not a ``(Preparation)`` wrapper, and the group is the first segment under
    the section root.
    """
    parts = [p for p in path.split('/') if p != '']
    if parts and parts[0] == stem:
        parts = parts[1:]
    if parts and parts[0] == _SECTION_ROOT:
        parts = parts[1:]

    window = ''
    while parts and parts[-1].startswith(SST_TITLE_PREFIX):
        if not window:
            m = _DATE_WINDOW.search(parts[-1])
            if m:
                window = _clean(m.group(1))
        parts.pop()

    group = _clean(parts[0]) if parts else ''
    system = ''
    for seg in reversed(parts[1:] if len(parts) > 1 else parts):
        seg = _clean(seg)
        if seg.endswith(_PREPARATION):
            seg = seg[:-len(_PREPARATION)]
        if seg:
            system = seg
            break
    return group, system, window


def _tool_rows(content):
    """Yield ``(number, is_component, name, note, image)`` per table row.

    Rows that carry no recognisable tool number are skipped rather than
    guessed at: without a number the row cannot be merged with the same tool
    seen on another page, which is the whole point of the export.
    """
    if not content:
        return
    soup = BeautifulSoup(content, 'html.parser')
    for tr in soup.find_all('tr'):
        cells = tr.find_all('td')
        if len(cells) != 4:
            continue  # header, spacer, or a shape this parser does not know
        m = _TOOL_NUMBER.match(cells[1].get_text(' ', strip=True))
        if not m:
            continue
        img = cells[0].find('img')
        # Keep the src, not the alt: most tool pictures are .png but some are
        # .svg, and guessing the extension from the alt text would 404 on those.
        src = (img.get('src') or '') if img else ''
        # A <br> inside the name is a line wrap in the manual's layout, not a
        # separator: "Crankshaft Front Oil Seal<br/>Replacer" is one name.
        name = ' '.join(cells[2].get_text(' ', strip=True).split())
        note = ' '.join(cells[3].get_text(' ', strip=True).split())
        yield (m.group(2), bool(m.group(1)), name, note,
               src.rsplit('/', 1)[-1] if src else '')


def collect_tools(conn):
    """Merge every SST page in one car into ``{tool_number: record}``.

    Returns an ordered list of records, kit components following their parent.
    """
    cur = conn.cursor()
    root = cur.execute(
        "SELECT path FROM nodes WHERE node_type='leaf' AND title LIKE ? "
        "ORDER BY LENGTH(path) LIMIT 1", (SST_TITLE_PREFIX + '%',)).fetchone()
    if not root:
        return []
    # The DB path stem is not always the catalog car_name (some catalog names
    # carry a suffix the crawl path lacks), so read it off a real node.
    stem = root[0].split('/')[0]

    tools = {}
    order = []
    for path, content in cur.execute(
            "SELECT path, content FROM nodes WHERE node_type='leaf' "
            "AND title LIKE ? ORDER BY path", (SST_TITLE_PREFIX + '%',)):
        group, system, window = _system_of(path, stem)
        label = ' › '.join(x for x in (group, system) if x)
        parent = ''
        for number, is_component, name, note, image in _tool_rows(content):
            if is_component:
                rec_parent = parent
            else:
                rec_parent = ''
                parent = number
            rec = tools.get(number)
            if rec is None:
                rec = tools[number] = {
                    'number': number, 'name': name, 'kit_of': rec_parent,
                    'note': note, 'image': image, 'used_in': [], 'windows': [],
                }
                order.append(number)
            # A tool listed under several systems keeps the first name seen;
            # they agree in the corpus, and a later blank must not overwrite it.
            if not rec['name']:
                rec['name'] = name
            if not rec['image']:
                rec['image'] = image
            if not rec['kit_of']:
                rec['kit_of'] = rec_parent
            if label and label not in rec['used_in']:
                rec['used_in'].append(label)
            if window and window not in rec['windows']:
                rec['windows'].append(window)

    # Sort by kit, then components after their parent, then by number.
    def key(number):
        rec = tools[number]
        return (rec['kit_of'] or rec['number'], 1 if rec['kit_of'] else 0,
                rec['number'])

    return [tools[n] for n in sorted(order, key=key)]


def iter_report_rows(conn, car_name, brand, year, media_base=''):
    """Yield full CSV rows (lists aligned to :data:`CSV_HEADER`) for one car."""
    year_str = '' if year is None else str(year)
    for rec in collect_tools(conn):
        image = rec['image']
        if image and media_base:
            image = "%s/%s" % (media_base.rstrip("/"), image)
        yield [
            brand or '', car_name, year_str,
            rec['number'], rec['name'], rec['kit_of'], rec['note'],
            len(rec['used_in']), ' | '.join(sorted(rec['used_in'])),
            ' | '.join(rec['windows']), image,
        ]


def build_csv(conn, car_name, brand, year, media_base=''):
    """Return the complete SST report for one car as a CSV string (UTF-8 text,
    prefixed with a BOM so Excel opens it correctly)."""
    buf = io.StringIO()
    buf.write('﻿')  # BOM for Excel
    w = csv.writer(buf, lineterminator='\r\n')
    w.writerow(CSV_HEADER)
    for row in iter_report_rows(conn, car_name, brand, year, media_base):
        w.writerow(row)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Django view
# ---------------------------------------------------------------------------
# Same gate as the Labor Times export: SST pages are paid manual content, and
# auth rides the kg_portal_token cookie, which a top-level browser download
# navigation carries (SameSite=Lax), so a plain <a href download> works.
def has_sst(conn):
    """True when this car has any SST page at all.

    Deliberately a bare existence check, not a tool count: the front page asks
    this on every load, and counting tools would mean parsing ~40 HTML pages.
    One car in the fleet (Mirai) has no SST section, so the download button has
    to be conditional rather than always shown.
    """
    return conn.execute(
        "SELECT 1 FROM nodes WHERE node_type='leaf' AND title LIKE ? LIMIT 1",
        (SST_TITLE_PREFIX + '%',)).fetchone() is not None


def sst_csv_view(request, brand_name=None, year=None, model_name=None):
    from django.http import HttpResponse, JsonResponse
    from .models import Car
    from .access import car_db_ready, user_can_open_car
    from .labortimes import _sanitize_filename
    from .portal import portal_user
    from .views import get_car_db

    # Same tolerant (brand, name) fallback car_view uses: legacy links can
    # carry a stale or placeholder year segment.
    base_qs = Car.objects.filter(
        brand_name__iexact=brand_name, car_name__iexact=model_name)
    try:
        car = base_qs.get(year=int(year))
    except (ValueError, TypeError, Car.DoesNotExist):
        car = base_qs.order_by('-year').first()
    if car is None:
        return JsonResponse({'error': 'vehicle not found'}, status=404)

    user = portal_user(request)
    if not user:
        return JsonResponse({'error': 'unauthorized'}, status=401)
    if not user_can_open_car(user, car):
        return JsonResponse(
            {'error': 'forbidden',
             'detail': 'دسترسی به مستندات این خودرو در اشتراک شما نیست.'},
            status=403)
    if not car_db_ready(car):
        return JsonResponse(
            {'error': 'vehicle database not available on server'}, status=404)

    from urllib.parse import quote
    conn = get_car_db(car.db_address)

    # ?probe=1 -> cheap availability check for the front-page button, so the
    # page never offers a download that would come back empty.
    if request.GET.get('probe'):
        return JsonResponse({'available': has_sst(conn)})

    if not has_sst(conn):
        return JsonResponse(
            {'error': 'no SST section',
             'detail': 'برای این خودرو فهرست ابزار مخصوص (SST) ثبت نشده است.'},
            status=404)
    # Same relative /media/<car> base the manual content uses, so the image
    # column resolves against whichever host the report is opened from.
    body = build_csv(conn, car.car_name, car.brand_name, car.year,
                     media_base='/media/%s' % quote(car.car_name))

    resp = HttpResponse(body, content_type='text/csv; charset=utf-8')
    fname = _sanitize_filename(
        '{}_{}_{}_sst'.format(car.brand_name, car.car_name, car.year)) + '.csv'
    resp['Content-Disposition'] = 'attachment; filename="{}"'.format(fname)
    return resp
