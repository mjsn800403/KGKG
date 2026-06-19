import re
import sqlite3
from pathlib import Path
from urllib.parse import quote
from django.http import JsonResponse
from django.conf import settings
from .models import Car

def brands_list_view(request):
    """GET / -> distinct list of brand names available across all cars."""
    brands = Car.objects.order_by('brand_name').values_list('brand_name', flat=True).distinct()
    return JsonResponse(list(brands), safe=False)

def get_car_db(db_address):
    """Connect to car-specific database"""
    main_dir = Path(settings.DATABASES['default']['NAME']).parent
    abs_path = main_dir / db_address
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

            if href_lookup:
                # The manual's HTML content cross-links to other pages by
                # their original static filename (e.g. "pages/40738.html"),
                # which doesn't correspond to any node path in our tree.
                # Resolve the filename to a node, then walk up via parent_id
                # to build the title chain so the frontend can navigate to
                # the equivalent app URL.
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
                return JsonResponse({'segments': segments})

            if not path_segments:
                # No path: return the car's root nodes.
                cur.execute(f"""
                    SELECT {NODE_COLUMNS}
                    FROM nodes
                    WHERE node_type = 'root' AND depth = 1
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
