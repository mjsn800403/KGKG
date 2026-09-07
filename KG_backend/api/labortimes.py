"""Per-vehicle "Labor Times" CSV export.

Each car's manual has a top-level ``Labor Times`` section: a tree of
``Category / Sub-category / Part / Operation`` leaves, every leaf holding a
small HTML table of flat-rate hours (Applies To / Note / Standard Hours /
Warranty Hours / Skill Level). This module flattens that whole subtree for one
car into a single CSV — one output row per table row — so a shop can download a
complete labor-time report for the vehicle.

Path shapes seen in the warehouse (verified across the fleet):

    <car>/Labor Times/Other Variant/<Cat>/<Sub1>/<Part>/<Operation>
    <car>/Labor Times/<Cat>/<Sub1>/<Part>/<Operation>

The optional ``Other Variant`` wrapper (labor data borrowed from a sibling
trim) is dropped; both shapes normalise to ``[Cat, Sub1, Part, Operation]``,
which maps onto the report's catagory / sub-catagory1 / sub-catagory2 /
sub-catagory3 columns. "Known missing" leaves (captured with no table) still
emit one row, with the breadcrumb filled and the hour columns blank.

The module core (:func:`build_csv`) depends only on sqlite3 + BeautifulSoup so
it can be unit-tested against a raw car DB; the Django view wraps it with the
same auth + per-car access gate the manual content endpoints use.
"""
import csv
import io

from bs4 import BeautifulSoup

LABOR_TIMES_TITLE = 'Labor Times'
# A variant wrapper the tree inserts when the labor data is inherited from a
# sibling trim; it is a scope marker, not a real category, so we drop it.
_VARIANT_WRAPPER = 'Other Variant'
# Titles embed a literal "/" as U+2044 FRACTION SLASH so the crawler's
# "/"-joined path column never splits mid-title. Restore it for display.
_FRACTION_SLASH = '⁄'

# The report header, verbatim (including the caller's "catagory" spelling).
CSV_HEADER = [
    'brand', 'car', 'year',
    'catagory', 'sub-catagory1', 'sub-catagory2', 'sub-catagory3',
    'Applies To', 'Note', 'Standard Hours', 'Warranty Hours', 'Skill Level',
]
# The five data columns, in the order they appear in the leaf tables.
_DATA_FIELDS = ['Applies To', 'Note', 'Standard Hours', 'Warranty Hours', 'Skill Level']


def _clean(seg):
    return (seg or '').replace(_FRACTION_SLASH, '/').strip()


def _breadcrumb(path, car_name):
    """Return ``[catagory, sub1, sub2, operation]`` for one leaf ``path``.

    Anything past the fourth level is folded into sub-category-2 so no data is
    silently dropped if the tree ever nests deeper; shorter chains left-fill
    and pad with blanks.
    """
    parts = [p for p in path.split('/') if p != '']
    # Drop the leading car stem and the "Labor Times" root.
    if parts and parts[0] == car_name:
        parts = parts[1:]
    if parts and parts[0] == LABOR_TIMES_TITLE:
        parts = parts[1:]
    if parts and parts[0] == _VARIANT_WRAPPER:
        parts = parts[1:]
    parts = [_clean(p) for p in parts]
    if not parts:
        return ['', '', '', '']
    operation = parts[-1]
    folders = parts[:-1]
    catagory = folders[0] if len(folders) >= 1 else ''
    sub1 = folders[1] if len(folders) >= 2 else ''
    sub2 = ' / '.join(folders[2:]) if len(folders) >= 3 else ''
    return [catagory, sub1, sub2, operation]


def _table_rows(content):
    """Yield the ``[Applies To, Note, Standard Hours, Warranty Hours,
    Skill Level]`` cell lists from a leaf's HTML.

    Returns ``[]`` when the leaf has no labor table (e.g. a "known missing"
    page) — the caller then emits a single blank-data row so the operation is
    still represented in the report.
    """
    if not content:
        return []
    soup = BeautifulSoup(content, 'html.parser')
    table = None
    for t in soup.find_all('table'):
        heads = [th.get_text(strip=True) for th in t.find_all('th')]
        if 'Standard Hours' in heads:
            table = t
            break
    if table is None:
        return []
    heads = [th.get_text(strip=True) for th in table.find_all('th')]
    # Map each wanted field to its column index (fall back to fixed order).
    col = {name: (heads.index(name) if name in heads else i)
           for i, name in enumerate(_DATA_FIELDS)}
    body = table.find('tbody') or table
    out = []
    for tr in body.find_all('tr'):
        cells = tr.find_all('td')
        if not cells:
            continue  # header row / spacer
        vals = [c.get_text(' ', strip=True) for c in cells]
        row = []
        for name in _DATA_FIELDS:
            idx = col[name]
            row.append(vals[idx] if idx < len(vals) else '')
        out.append(row)
    return out


def iter_report_rows(conn, car_name, brand, year):
    """Yield full CSV rows (lists aligned to :data:`CSV_HEADER`) for one car."""
    year_str = '' if year is None else str(year)
    cur = conn.cursor()
    # The path stem stored in the DB is not always the catalog ``car_name``:
    # some catalog names carry a suffix (e.g. "(2024)") that the crawl path
    # stem lacks. Discover the Labor Times root from the DB so the leaf query
    # and the breadcrumb stem-drop use the real stem, not the display name.
    root = cur.execute(
        "SELECT path FROM nodes WHERE title = ? AND path LIKE ? "
        "ORDER BY LENGTH(path) LIMIT 1",
        (LABOR_TIMES_TITLE, '%/' + LABOR_TIMES_TITLE),
    ).fetchone()
    if not root:
        return
    lt_path = root[0]
    stem = lt_path.split('/')[0]
    cur.execute(
        "SELECT path, content FROM nodes "
        "WHERE node_type = 'leaf' AND path LIKE ? "
        "ORDER BY path",
        (lt_path + '/%',),
    )
    for path, content in cur.fetchall():
        crumb = _breadcrumb(path, stem)
        table = _table_rows(content)
        prefix = [brand or '', car_name, year_str] + crumb
        if table:
            for data in table:
                yield prefix + data
        else:
            yield prefix + ['', '', '', '', '']


def build_csv(conn, car_name, brand, year):
    """Return the complete Labor Times report for one car as a CSV string
    (UTF-8 text, prefixed with a BOM so Excel opens it correctly)."""
    buf = io.StringIO()
    buf.write('﻿')  # BOM for Excel
    w = csv.writer(buf, lineterminator='\r\n')
    w.writerow(CSV_HEADER)
    for row in iter_report_rows(conn, car_name, brand, year):
        w.writerow(row)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Django view
# ---------------------------------------------------------------------------
# A vehicle's Labor Times are paid manual content, so the download is gated by
# exactly the same login + per-car access check the manual-content endpoints
# use (see car_view Case 3). Auth rides the ``kg_portal_token`` cookie, which a
# top-level browser download navigation carries (SameSite=Lax), so a plain
# <a href download> works without any client-side token juggling.
def _sanitize_filename(stem):
    out = ''.join(ch if (ch.isalnum() or ch in ' -_') else '_' for ch in stem)
    return (out.strip().replace(' ', '_') or 'car')


def labor_times_csv_view(request, brand_name=None, year=None, model_name=None):
    from django.http import HttpResponse, JsonResponse
    from .models import Car
    from .access import car_db_ready, user_can_open_car
    from .portal import portal_user
    from .views import get_car_db

    # Resolve the car with the same tolerant (brand, name) fallback car_view
    # uses: legacy links can carry a stale/placeholder year segment.
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

    conn = get_car_db(car.db_address)
    body = build_csv(conn, car.car_name, car.brand_name, car.year)

    resp = HttpResponse(body, content_type='text/csv; charset=utf-8')
    fname = _sanitize_filename(
        '{}_{}_{}_labor_times'.format(car.brand_name, car.car_name, car.year)
    ) + '.csv'
    resp['Content-Disposition'] = 'attachment; filename="{}"'.format(fname)
    return resp
