import re
import sqlite3
from pathlib import Path
from urllib.parse import quote
from django.http import JsonResponse
from django.conf import settings
from bs4 import BeautifulSoup
from .models import Car

def health_view(request):
    """GET /healthz -> liveness/readiness probe for load balancers and
    container healthchecks. Touches the DB so an unreachable database is
    reported as unhealthy."""
    try:
        Car.objects.exists()
    except Exception:
        return JsonResponse({'status': 'error', 'db': 'unreachable'}, status=503)
    return JsonResponse({'status': 'ok'})

def brands_list_view(request):
    """GET / -> distinct list of brand names available across all cars."""
    brands = Car.objects.order_by('brand_name').values_list('brand_name', flat=True).distinct()
    return JsonResponse(list(brands), safe=False)

def get_car_db(db_address):
    """Connect to car-specific database"""
    main_dir = Path(settings.DATABASES['default']['NAME']).parent
    # db_address may carry Windows separators (rows were seeded from the
    # Windows parser); normalize so it resolves on POSIX/Linux containers too.
    abs_path = main_dir / db_address.replace('\\', '/')
    if not abs_path.exists():
        raise FileNotFoundError(f"Database not found: {abs_path}")
    return sqlite3.connect(str(abs_path))

NODE_COLUMNS = """id, parent_id, path, title, node_type, file_type,
                  href, sort_order, depth, content"""

# Manual content references images two ways, both pointing at files that
# live in static_warehouse/<car_name>/ (mirroring the original crawl's
# "images/" folder):
#   <img src="../images/VA899634.svg">
#   <object data="/api/Image/SVGImage/VA899634">
_IMG_SRC_RE = re.compile(r'src="(?:\.\./)*images/([^"]+)"')
_IMG_DATA_RE = re.compile(r'data="/api/Image/SVGImage/([^"]+)"')

def rewrite_image_urls(content, car_name):
    """Point manual-content image references at this car's media folder.

    Deliberately relative ("/media/..."), not absolute: the backend doesn't
    know (and shouldn't need to know) what public host/port the frontend
    will use to reach it - that's the frontend's API_BASE concern, same as
    every other endpoint it calls.
    """
    if not content:
        return content
    media_base = f"/media/{quote(car_name)}"
    content = _IMG_SRC_RE.sub(lambda m: f'src="{media_base}/{m.group(1)}"', content)
    content = _IMG_DATA_RE.sub(lambda m: f'data="{media_base}/{m.group(1)}.svg"', content)
    return content

def node_to_dict(row, car_name):
    node = dict(row)
    node['content'] = rewrite_image_urls(node.get('content'), car_name)
    return node

def _car_source_dir(cur):
    """The on-disk root of this car's original crawl, derived from the
    source_file recorded against its index/root node."""
    row = cur.execute(
        "SELECT source_file FROM nodes WHERE source_file IS NOT NULL AND file_type='root_path' LIMIT 1"
    ).fetchone()
    if not row:
        row = cur.execute(
            "SELECT source_file FROM nodes WHERE source_file IS NOT NULL LIMIT 1"
        ).fetchone()
    if not row or not row['source_file']:
        return None
    return Path(row['source_file']).parent

def read_page_content(cur, car_name, filename):
    """Render the raw HTML of a manual page that exists on disk but was never
    registered as a node (e.g. an alternate-variant page only reachable via a
    cross-link, like "Labor Times: Other Variant"). Scoped to THIS car's own
    source directory so a bare filename like "5.html" can't collide with an
    unrelated page in another car's crawl."""
    base = _car_source_dir(cur)
    if base is None:
        return None
    candidates = [base / 'pages' / filename, base / filename]
    fp = next((c for c in candidates if c.exists()), None)
    if fp is None:
        return None
    html = fp.read_text(encoding='utf-8', errors='replace')
    try:
        soup = BeautifulSoup(html, 'html5lib')
    except Exception:
        soup = BeautifulSoup(html, 'html.parser')
    main = soup.select_one('div.main') or soup.body or soup
    h1 = main.find('h1')
    if h1 and h1.get_text(strip=True):
        title = h1.get_text(strip=True)
    else:
        parts = soup.select('a.breadcrumb-part')
        title = parts[-1].get_text(strip=True) if parts else filename
    content = rewrite_image_urls(main.decode_contents(), car_name)
    return {'title': title, 'content': content}

def car_view(request, brand_name=None, year=None, model_name=None):
    """
    /brand_name/                                -> from main.db
    /brand_name/year/                           -> from main.db
    /brand_name/year/car_name/                  -> root nodes from car db
    /brand_name/year/car_name/?seg=a&seg=b...    -> walk down the tree by
                                                     title, one "seg" per
                                                     path segment, from the
                                                     car's root nodes.
    """

    # Case 1: Only brand name
    if brand_name and not year:
        cars = Car.objects.filter(brand_name__iexact=brand_name).values('brand_name', 'car_name', 'year', 'db_address')
        return JsonResponse(list(cars), safe=False)

    # Case 2: Brand and year
    if brand_name and year and not model_name:
        cars = Car.objects.filter(brand_name__iexact=brand_name, year=year).values('brand_name', 'car_name', 'year', 'db_address')
        return JsonResponse(list(cars), safe=False)

    # Case 3: Brand, year, and car_name
    if brand_name and year and model_name:
        try:
            # Get the car from main db
            car = Car.objects.get(
                brand_name__iexact=brand_name,
                year=year,
                car_name__iexact=model_name
            )

            # Connect to car database
            conn = get_car_db(car.db_address)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            path_segments = request.GET.getlist('seg')
            href_lookup = request.GET.get('href')
            page_file = request.GET.get('page')

            if page_file:
                # Serve a raw manual page that has no node (orphan cross-link
                # target). Read straight from this car's own source folder.
                result = read_page_content(cur, car.car_name, page_file.rstrip('/').split('/')[-1])
                conn.close()
                if result is None:
                    return JsonResponse({'error': f'Page not found: {page_file}'}, status=404)
                return JsonResponse(result)

            if href_lookup:
                # The manual's HTML content cross-links to other pages by
                # their original static filename (e.g. "pages/40738.html"),
                # which doesn't correspond to any node path in our tree.
                # Resolve the filename to a node, then walk up via parent_id
                # to build the title chain so the frontend can navigate to
                # the equivalent app URL.
                #
                # Deliberately scoped to THIS car's db only: filenames like
                # "5.html" are sequential IDs assigned independently by each
                # crawl run, not globally unique identifiers. Searching other
                # cars' databases by filename alone risks matching a
                # completely unrelated page that happens to share the same
                # number (verified: "5.html" exists in two unrelated cars'
                # dbs pointing at totally different content). Some cross-links
                # point at a different vehicle variant that was never
                # onboarded at all (e.g. "Land Cruiser Base" linking to
                # "Land Cruiser 1958") - those correctly 404 here, and the
                # frontend shows a "not available" message instead of
                # guessing.
                filename = href_lookup.rstrip('/').split('/')[-1]
                cur.execute(f"""
                    SELECT {NODE_COLUMNS} FROM nodes WHERE href LIKE ? LIMIT 1
                """, ('%/' + filename,))
                node = cur.fetchone()

                if not node:
                    return JsonResponse({'error': f'No node found for href: {href_lookup}'}, status=404)

                segments = []
                current = node
                while current['parent_id'] is not None:
                    segments.append(current['title'])
                    cur.execute(f"SELECT {NODE_COLUMNS} FROM nodes WHERE id = ?", (current['parent_id'],))
                    parent = cur.fetchone()
                    if not parent:
                        break
                    current = parent
                segments.reverse()

                conn.close()
                return JsonResponse({
                    'brand': car.brand_name,
                    'year': car.year,
                    'model': car.car_name,
                    'segments': segments,
                })

            if not path_segments:
                # No path: return the car's root nodes. Excludes dead-link
                # artifacts from the crawl (e.g. a followed link that turned
                # out to be the site's 404 page, misclassified as a real
                # "Download .zip for offline use" node).
                cur.execute(f"""
                    SELECT {NODE_COLUMNS}
                    FROM nodes
                    WHERE node_type = 'root' AND depth = 1
                          AND (href IS NULL OR href != '404.html')
                    ORDER BY sort_order
                """)
            else:
                # Walk down the tree title by title. We deliberately do NOT
                # match against the `path` column: some titles contain a
                # literal "/" (e.g. "Service Data [11/2022 - ]"), and the
                # `path` column substitutes a different character for it,
                # so a concatenated-path string comparison is unreliable.
                # Matching by (parent_id, title) at each step sidesteps that
                # entirely, since titles are compared individually.
                cur.execute("""
                    SELECT parent_id FROM nodes WHERE node_type = 'root' AND depth = 1 LIMIT 1
                """)
                root_row = cur.fetchone()
                if not root_row:
                    return JsonResponse({'error': 'Car has no root nodes'}, status=404)

                current_parent_id = root_row['parent_id']
                matched = None
                walked = []
                for seg in path_segments:
                    cur.execute(f"""
                        SELECT {NODE_COLUMNS}
                        FROM nodes
                        WHERE parent_id = ? AND title = ?
                        ORDER BY sort_order
                        LIMIT 1
                    """, (current_parent_id, seg))
                    matched = cur.fetchone()
                    if not matched:
                        walked.append(seg)
                        return JsonResponse(
                            {'error': f"Path not found: {model_name}/" + '/'.join(walked)},
                            status=404
                        )
                    walked.append(seg)
                    current_parent_id = matched['id']

                # Leaf nodes carry their own content and have no children -
                # return the node itself instead of querying for children.
                if matched['content'] is not None:
                    nodes = [node_to_dict(matched, car.car_name)]
                    conn.close()
                    return JsonResponse(nodes, safe=False)

                cur.execute(f"""
                    SELECT {NODE_COLUMNS}
                    FROM nodes
                    WHERE parent_id = ?
                    ORDER BY sort_order
                """, (matched['id'],))

            nodes = [node_to_dict(row, car.car_name) for row in cur.fetchall()]
            conn.close()

            return JsonResponse(nodes, safe=False)

        except Car.DoesNotExist:
            return JsonResponse({'error': 'Car not found'}, status=404)
        except FileNotFoundError as e:
            return JsonResponse({'error': str(e)}, status=404)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'error': 'Invalid URL'}, status=400)
