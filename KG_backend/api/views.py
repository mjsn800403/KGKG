import re
import json
from pathlib import Path
from urllib.parse import quote
from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from bs4 import BeautifulSoup
from . import cardb
from .models import Car, PurchaseRequest
from .access import car_db_ready, user_can_open_car
from .portal import portal_user
from .ratelimit import rate_limited, require_admin_token

# Public catalog listings change only when the fleet changes; a short TTL keeps
# them fresh enough while collapsing per-request table scans + fleet stat()s.
CATALOG_CACHE_TTL = 60


def _unauthorized():
    return JsonResponse({'error': 'unauthorized'}, status=401)


def _forbidden_car():
    return JsonResponse(
        {'error': 'forbidden',
         'detail': 'دسترسی به مستندات این خودرو در اشتراک شما نیست.'},
        status=403)


def _resolve_car(stem, brand=None, year=None):
    """Best-effort map a RAG car_stem / model name (+ optional brand/year) to a
    catalog Car row, for per-car access checks. Returns a Car or None."""
    if not stem:
        return None
    qs = Car.objects.all()
    if brand:
        qs = qs.filter(brand_name__iexact=brand)
    if year:
        try:
            qs = qs.filter(year=int(year))
        except (TypeError, ValueError):
            pass
    return qs.filter(car_name__iexact=stem).first()


def _guard_car_content(request, stem, brand=None, year=None):
    """Auth + per-car access gate for the manual-content endpoints (assist /
    diagnose / search / car content). Returns (user, None) when allowed, or
    (None, JsonResponse) with the right 401/403 to return.

    A resolvable car is access-checked; a query with no resolvable car (the
    general, car-less assistant) requires only a valid login. The RAG index is
    small (a handful of indexed vehicles); scoping the car-less path to the
    user's own vehicles is a follow-up."""
    user = portal_user(request)
    if not user:
        return None, _unauthorized()
    car = _resolve_car(stem, brand=brand, year=year)
    if car is not None and not user_can_open_car(user, car):
        return None, _forbidden_car()
    return user, None

def brands_list_view(request):
    """GET / -> distinct list of brand names available across all cars."""
    brands = cache.get('kg:brands')
    if brands is None:
        brands = sorted({
            c.brand_name for c in Car.objects.order_by('brand_name')
            if car_db_ready(c)
        })
        cache.set('kg:brands', brands, CATALOG_CACHE_TTL)
    return JsonResponse(brands, safe=False)


@csrf_exempt
@rate_limited('assist', 60, 60)
def assist_view(request):
    """POST /api/assist/  body: {query, brand?, model?, car?}
       GET  /api/assist/?q=...&brand=...&model=...&car=...

    Runs the local RAG + relationship-graph retrieval entirely against our own
    sidecar index (no external service). Returns ranked manual excerpts, each
    with a real in-app URL plus graph-related and cross-vehicle context. The
    AI assistant uses this as grounding; it is NOT the language generator.
    """
    if request.method == 'POST':
        try:
            body = json.loads(request.body or '{}')
        except (ValueError, TypeError):
            body = {}
        query = (body.get('query') or body.get('q') or '').strip()
        brand = body.get('brand') or None
        model = body.get('model') or None
        car = body.get('car') or body.get('car_stem') or None
    else:
        query = (request.GET.get('q') or request.GET.get('query') or '').strip()
        brand = request.GET.get('brand') or None
        model = request.GET.get('model') or None
        car = request.GET.get('car') or None

    if not query:
        return JsonResponse({'error': 'query is required'}, status=400)

    _user, deny = _guard_car_content(request, car or model, brand=brand)
    if deny:
        return deny

    try:
        from .rag import service
        result = service.assist(query, brand=brand, model=model, car_stem=car)
        return JsonResponse(result)
    except FileNotFoundError as e:
        return JsonResponse(
            {'error': 'RAG index not built yet. Run: python manage.py build_rag',
             'detail': str(e)}, status=503)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@rate_limited('diagnose', 60, 60)
def diagnose_view(request):
    """POST /api/diagnose/  body: {query, brand?, model?, car?}
       GET  /api/diagnose/?q=...&car=...

    The deterministic per-car diagnostic rule engine: maps a Persian symptom or a
    DTC code to ranked candidate DTCs with their inheritance scope, ordered
    diagnostic steps, repair procedure + labor time and cross-vehicle matches.
    All processing happens here; the language model only phrases the result.
    """
    if request.method == 'POST':
        try:
            body = json.loads(request.body or '{}')
        except (ValueError, TypeError):
            body = {}
        query = (body.get('query') or body.get('q') or '').strip()
        brand = body.get('brand') or None
        model = body.get('model') or None
        car = body.get('car') or body.get('car_stem') or None
    else:
        query = (request.GET.get('q') or request.GET.get('query') or '').strip()
        brand = request.GET.get('brand') or None
        model = request.GET.get('model') or None
        car = request.GET.get('car') or None

    if not query:
        return JsonResponse({'error': 'query is required'}, status=400)

    _user, deny = _guard_car_content(request, car or model, brand=brand)
    if deny:
        return deny

    try:
        from .rag import service
        result = service.diagnose(query, brand=brand, model=model, car_stem=car)
        return JsonResponse(result)
    except FileNotFoundError as e:
        return JsonResponse(
            {'error': 'Diagnostic index not built yet. Run: python manage.py build_diag',
             'detail': str(e)}, status=503)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@rate_limited('click', 120, 60)
def assist_feedback_view(request):
    """POST /api/assist/feedback/  body: {query, blob_id, app_url}
    Records which result the user actually opened — a relevance signal used to
    improve ranking over time. Best-effort; always returns ok."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)
    if not portal_user(request):
        return _unauthorized()
    try:
        body = json.loads(request.body or '{}')
    except (ValueError, TypeError):
        body = {}
    try:
        from .rag import feedback
        feedback.log_click(body.get('query') or '', body.get('blob_id'), body.get('app_url') or '')
    except Exception:
        pass
    return JsonResponse({'ok': True})


ALLOWED_DOC_TYPES = {'parts', 'manual', 'standard_time', 'special_tools', 'full_spec'}


@csrf_exempt
@rate_limited('purchase', 10, 60)
def purchase_request_view(request):
    """POST /api/purchase-request/  body:
       {brand, model, year, documents[], company, landline, mobile, reg_no, note?}

    Stores a legal-entity documentation purchase request so the sales team can
    follow up. Returns {ok: true, id}. Validates the required fields server-side
    (never trust the client) and keeps only known document ids.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)
    try:
        body = json.loads(request.body or '{}')
    except (ValueError, TypeError):
        return JsonResponse({'error': 'بدنه درخواست نامعتبر است.'}, status=400)

    def _clean(v, limit):
        return (str(v or '')).strip()[:limit]

    brand = _clean(body.get('brand'), 120)
    model = _clean(body.get('model'), 200)
    year = _clean(body.get('year'), 20)
    company = _clean(body.get('company'), 200)
    landline = _clean(body.get('landline'), 40)
    mobile = _clean(body.get('mobile'), 40)
    reg_no = _clean(body.get('reg_no'), 60)
    note = _clean(body.get('note'), 2000)

    def _int_or_none(v):
        try:
            n = int(v)
            return n if 0 < n < 1_000_000 else None
        except (TypeError, ValueError):
            return None

    employees_count = _int_or_none(body.get('employees_count'))
    seats_count = _int_or_none(body.get('seats_count'))
    wants_demo = bool(body.get('wants_demo'))
    wants_ai_assistant = bool(body.get('wants_ai_assistant'))

    from .access import parse_seat_plan
    seat_plan_raw = body.get('seat_plan')
    seat_plan, seat_plan_err = parse_seat_plan(seat_plan_raw)
    if seat_plan is None:
        return JsonResponse({'error': seat_plan_err}, status=400)
    plan_total = sum(r['count'] for r in seat_plan)
    if seats_count and seats_count != plan_total:
        return JsonResponse(
            {'error': 'تعداد صندلی با جمع نقش‌های سازمانی همخوانی ندارد.'}, status=400)
    seats_count = plan_total

    raw_docs = body.get('documents') or []
    if not isinstance(raw_docs, list):
        raw_docs = []
    documents = [d for d in raw_docs if d in ALLOWED_DOC_TYPES]

    if not (brand and model and year):
        return JsonResponse({'error': 'برند، مدل و سال خودرو الزامی است.'}, status=400)
    if not documents:
        return JsonResponse({'error': 'حداقل یک نوع مستند را انتخاب کنید.'}, status=400)
    if not (company and landline and mobile and reg_no):
        return JsonResponse(
            {'error': 'برای اشخاص حقوقی، نام شرکت، تلفن ثابت، تلفن همراه و شماره ثبتی الزامی است.'},
            status=400)
    if not employees_count or not seats_count:
        return JsonResponse(
            {'error': 'تعداد پرسنل شرکت و تعداد کاربران مورد نیاز را وارد کنید.'},
            status=400)

    try:
        pr = PurchaseRequest.objects.create(
            brand=brand, model=model, year=year, documents=documents,
            company=company, landline=landline, mobile=mobile, reg_no=reg_no, note=note,
            employees_count=employees_count, seats_count=seats_count,
            seat_plan=seat_plan,
            wants_demo=wants_demo, wants_ai_assistant=wants_ai_assistant,
        )
    except Exception as e:
        return JsonResponse({'error': f'ثبت درخواست ناموفق بود: {e}'}, status=500)

    return JsonResponse({'ok': True, 'id': pr.id})


def _post_body(request):
    try:
        return json.loads(request.body or '{}')
    except (ValueError, TypeError):
        return {}


@csrf_exempt
@rate_limited('rate', 20, 60)
def feedback_rate_view(request):
    """POST /api/feedback/rate/  body: {query, verdict(+1/-1), mode?, top_blobs?,
    blob_id?, reason?, comment?, brand?, model?, car?}
    Records a 👍/👎 verdict (human-in-the-loop). Best-effort; always ok."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)
    if not portal_user(request):
        return _unauthorized()
    b = _post_body(request)
    scope = {'brand': b.get('brand'), 'model': b.get('model'),
             'car_stem': b.get('car') or b.get('car_stem')}
    try:
        from .rag import feedback, service
        feedback.rate(
            b.get('query') or '', scope, b.get('mode') or 'assist',
            b.get('top_blobs') or [], b.get('verdict', -1),
            blob_id=b.get('blob_id'), reason=b.get('reason'), comment=b.get('comment'))
        # A verdict shifts the feedback boost map, so any cached answer is now
        # stale (the boost map alone is invalidated inside rate(); the answer
        # and semantic caches must be dropped too or they serve the old ranking
        # until TTL).
        service.clear_cache()
    except Exception:
        pass
    return JsonResponse({'ok': True})


@csrf_exempt
@require_admin_token
@rate_limited('pin', 30, 60)
def feedback_pin_view(request):
    """POST /api/feedback/pin/  body: {pattern_query, app_url, blob_id?, title?,
    note?, by?}  — expert "pinned / verified answer". Embeds pattern_query so it
    can be matched against future queries. Returns {ok}."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)
    b = _post_body(request)
    pattern = (b.get('pattern_query') or b.get('query') or '').strip()
    if not pattern:
        return JsonResponse({'error': 'pattern_query is required'}, status=400)
    try:
        from .rag import retrieve, feedback, service
        qvec = retrieve.embed_query(pattern)
        qlist = qvec.tolist() if hasattr(qvec, 'tolist') else list(qvec)
        ok = feedback.add_override(
            pattern, qlist, b.get('app_url') or '', source_blob_id=b.get('blob_id'),
            title=b.get('title'), note=b.get('note'), created_by=b.get('by'))
        # A new pin should take effect immediately, not after the cache TTL.
        if ok:
            service.clear_cache()
        return JsonResponse({'ok': bool(ok)})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@require_admin_token
def feedback_recent_view(request):
    """GET /api/feedback/recent/?limit=50  -> recent 👎 verdicts for the admin
    review queue (so an expert can pin a correction). Admin-only: the queue
    exposes raw user queries + which sources were shown."""
    try:
        limit = max(1, min(int(request.GET.get('limit', 50) or 50), 200))
    except (TypeError, ValueError):
        limit = 50
    try:
        from .rag import feedback
        rows = feedback.recent_downvotes(limit=limit)
    except Exception:
        rows = []
    return JsonResponse({'count': len(rows), 'items': rows})


def eval_report_view(request):
    """GET /api/eval/report/  -> the latest offline evaluation run (+ trend)."""
    try:
        from .rag import evalreport
        return JsonResponse(evalreport.latest_report())
    except Exception as e:
        return JsonResponse({'error': str(e), 'runs': []}, status=200)


@rate_limited('search', 90, 60)
def search_view(request):
    """GET /api/search/?q=&car=&brand=&model=&limit=
    Semantic, cross-lingual site search over the unified RAG index, scoped to one
    car. A Persian query matches the English manual (the naive SQL LIKE it
    replaces was English-only). Returns the same lightweight navigation shape the
    old per-car search did — [{title, segments, path, ...}] — so the frontend is
    unchanged. Falls back to per-car SQL LIKE if the index isn't built yet."""
    q = (request.GET.get('q') or request.GET.get('query') or '').strip()
    brand = request.GET.get('brand') or None
    model = request.GET.get('model') or None
    car = request.GET.get('car') or request.GET.get('car_stem') or None
    if not q:
        return JsonResponse([], safe=False)
    _user, deny = _guard_car_content(request, car or model, brand=brand)
    if deny:
        return deny
    try:
        limit = int(request.GET.get('limit', 30) or 30)
    except (TypeError, ValueError):
        limit = 30
    limit = max(1, min(limit, 50))
    try:
        from .rag import service
        results = service.search(q, brand=brand, model=model, car_stem=car, limit=limit)
        return JsonResponse(results, safe=False)
    except FileNotFoundError:
        # Index not built yet -> degrade gracefully to the old keyword search so
        # the box keeps working (English-only, but better than a hard error).
        try:
            return _search_like_fallback(brand, model, car, q, limit)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


def _search_like_fallback(brand, model, car, q, limit):
    """Per-car SQL LIKE search (the previous behaviour), used only when the
    semantic index is absent. Mirrors car_view's ?q branch."""
    stem = car or model
    qs = Car.objects.all()
    if brand:
        qs = qs.filter(brand_name__iexact=brand)
    car_obj = qs.filter(car_name__iexact=stem).first() if stem else None
    if car_obj is None:
        return JsonResponse([], safe=False)
    conn = get_car_db(car_obj.db_address)
    cur = conn.cursor()
    like = f'%{q}%'
    cur.execute(f"""
        SELECT {NODE_COLUMNS},
               CASE WHEN title LIKE ? THEN 0 ELSE 1 END AS rank
        FROM nodes
        WHERE (title LIKE ? OR content LIKE ?)
              AND (href IS NULL OR href != '404.html')
        ORDER BY rank, depth, sort_order
        LIMIT ?
    """, (like, like, like, limit))
    results = []
    for row in cur.fetchall():
        results.append({
            'title': row['title'], 'path': row['path'],
            'node_type': row['node_type'],
            'is_leaf': row['content'] is not None,
            'segments': cardb.breadcrumbs(conn, row['id']),
        })
    return JsonResponse(results, safe=False)

def get_car_db(db_address):
    """Pooled, read-only connection to a car-specific database.

    Callers must NOT close it — the pool owns the connection (see cardb)."""
    main_dir = Path(settings.DATABASES['default']['NAME']).parent
    # db_address may carry Windows separators (rows seeded on Windows); normalize
    # so it resolves on POSIX/macOS too.
    abs_path = main_dir / db_address.replace('\\', '/')
    try:
        return cardb.connect(abs_path)
    except FileNotFoundError:
        raise FileNotFoundError(f"Database not found: {abs_path}")

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

    # Case 1: Only brand name. Public catalog (the sales/purchase page lists the
    # vehicles we cover); intentionally exposes no manual content and no internal
    # db_address path.
    if brand_name and not year:
        cars = [
            c for c in Car.objects.filter(brand_name__iexact=brand_name).order_by('car_name', 'year')
            if car_db_ready(c)
        ]
        return JsonResponse([
            {'brand_name': c.brand_name, 'car_name': c.car_name, 'year': c.year}
            for c in cars
        ], safe=False)

    # Case 2: Brand and year. Public catalog, same rationale as Case 1.
    if brand_name and year and not model_name:
        cars = [
            c for c in Car.objects.filter(brand_name__iexact=brand_name, year=year).order_by('car_name')
            if car_db_ready(c)
        ]
        return JsonResponse([
            {'brand_name': c.brand_name, 'car_name': c.car_name, 'year': c.year}
            for c in cars
        ], safe=False)

    # Case 3: Brand, year, and car_name
    if brand_name and year and model_name:
        try:
            # Get the car from main db
            car = Car.objects.get(
                brand_name__iexact=brand_name,
                year=year,
                car_name__iexact=model_name
            )

            # A specific vehicle's manual is paid content: require a logged-in
            # portal user who has this car in their effective grants — checked
            # BEFORE anything else so readiness/existence isn't revealed to
            # anonymous callers. (The brand and year listings above stay public
            # for the sales catalog; opening a vehicle does not.)
            _content_user = portal_user(request)
            if not _content_user:
                return _unauthorized()
            if not user_can_open_car(_content_user, car):
                return _forbidden_car()

            if not car_db_ready(car):
                return JsonResponse({'error': 'vehicle database not available on server'}, status=404)

            # Pooled read-only connection to the car database (never closed
            # here — the pool owns it; see api/cardb.py).
            conn = get_car_db(car.db_address)
            cur = conn.cursor()

            path_segments = request.GET.getlist('seg')
            href_lookup = request.GET.get('href')
            page_file = request.GET.get('page')
            search_q = request.GET.get('q')

            if search_q is not None:
                # Full-text-ish search over this car's tree: match the query
                # against node titles AND raw content, English input against
                # English data (sqlite's default LIKE is ASCII case-insensitive).
                # Title matches rank ahead of content-only matches. Each result
                # carries its segment chain (walked up via parent_id, same as
                # the href branch) so the frontend can build a navigation URL.
                q = search_q.strip()
                if not q:
                    return JsonResponse([], safe=False)
                try:
                    limit = int(request.GET.get('limit', 30) or 30)
                except (TypeError, ValueError):
                    limit = 30
                limit = max(1, min(limit, 50))
                like = f'%{q}%'
                cur.execute(f"""
                    SELECT {NODE_COLUMNS},
                           CASE WHEN title LIKE ? THEN 0 ELSE 1 END AS rank
                    FROM nodes
                    WHERE (title LIKE ? OR content LIKE ?)
                          AND (href IS NULL OR href != '404.html')
                    ORDER BY rank, depth, sort_order
                    LIMIT ?
                """, (like, like, like, limit))

                results = []
                for row in cur.fetchall():
                    results.append({
                        'title': row['title'],
                        'path': row['path'],
                        'node_type': row['node_type'],
                        'is_leaf': row['content'] is not None,
                        'segments': cardb.breadcrumbs(conn, row['id']),
                    })

                return JsonResponse(results, safe=False)

            if page_file:
                # Serve a raw manual page that has no node (orphan cross-link
                # target). Read straight from this car's own source folder.
                result = read_page_content(cur, car.car_name, page_file.rstrip('/').split('/')[-1])
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

                return JsonResponse({
                    'brand': car.brand_name,
                    'year': car.year,
                    'model': car.car_name,
                    'segments': cardb.breadcrumbs(conn, node['id']),
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
                    return JsonResponse(nodes, safe=False)

                cur.execute(f"""
                    SELECT {NODE_COLUMNS}
                    FROM nodes
                    WHERE parent_id = ?
                    ORDER BY sort_order
                """, (matched['id'],))

            nodes = [node_to_dict(row, car.car_name) for row in cur.fetchall()]
            return JsonResponse(nodes, safe=False)

        except Car.DoesNotExist:
            return JsonResponse({'error': 'Car not found'}, status=404)
        except FileNotFoundError as e:
            return JsonResponse({'error': str(e)}, status=404)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'error': 'Invalid URL'}, status=400)
