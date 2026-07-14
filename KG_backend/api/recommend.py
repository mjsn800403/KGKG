"""Behavioural recommendation engine.

Turns the usage signal (ActivityLog) + the vehicle grants + the RAG relationship
graph into meaningful, clickable suggestions:

  * continue      — pick up exactly where the user left off (their last views);
  * related       — graph-neighbour manual sections of what they've been reading,
                    restricted to vehicles they may open (leverages the RAG
                    edge graph that already powers the assistant's "related");
  * focus_areas   — the technical categories the user actually engages with, and
                    popular-but-untouched sections in those areas across their
                    fleet (content-based affinity);
  * popular       — what peers in their company use most (collaborative signal);
  * explore       — granted vehicles they have not opened yet.

For managers there is a team-level view (seat utilisation, top/idle members,
category coverage) that the manager dashboard and reports consume.

Everything degrades gracefully: if the RAG index is absent the graph section is
simply empty; the content/collaborative sections need only the main DB.
"""
from collections import Counter, defaultdict

from django.http import JsonResponse
from django.utils import timezone

from .models import ActivityLog, Car, PortalUser
from .access import CONTENT_CATEGORIES


def _category_label(cid, lang='fa'):
    for c, meta in CONTENT_CATEGORIES:
        if c == cid:
            return meta.get(lang) or meta.get('en') or cid
    return cid


def _granted_car_ids(user):
    return set(user.car_accesses.values_list('car_id', flat=True))


def _granted_stems(user):
    ids = _granted_car_ids(user)
    if not ids:
        return {}, set()
    id_to_stem = dict(Car.objects.filter(id__in=ids).values_list('id', 'car_name'))
    return id_to_stem, set(id_to_stem.values())


# ---------------------------------------------------------------------------
# Per-user recommendations
# ---------------------------------------------------------------------------

def recommend_for_user(user, limit=6, days=60):
    since = timezone.now() - timezone.timedelta(days=days)
    my_logs = list(ActivityLog.objects.filter(user=user, created_at__gte=since)
                   .select_related('car').order_by('-created_at')[:400])

    id_to_stem, my_stems = _granted_stems(user)
    granted_ids = set(id_to_stem)

    seen_urls = {l.app_url for l in my_logs if l.app_url}
    seen_titles = {(l.car_id, (l.node_title or '').strip().lower())
                   for l in my_logs if l.node_title}

    return {
        'continue': _continue(my_logs, limit),
        'related': _related_via_graph(my_logs, my_stems, seen_urls, limit),
        'focus_areas': _focus_areas(user, my_logs, granted_ids, seen_titles, limit),
        'popular': _popular_in_company(user, granted_ids, seen_urls, limit),
        'explore': _explore_untouched(user, id_to_stem, my_logs, limit),
        'generated_at': timezone.now().isoformat(),
    }


def _continue(my_logs, limit):
    """The user's most recent distinct content views, newest first."""
    out, seen = [], set()
    for l in my_logs:
        if l.action not in ('view_node', 'view_section') or not l.app_url:
            continue
        if l.app_url in seen:
            continue
        seen.add(l.app_url)
        out.append({
            'title': l.node_title or (l.detail or '').split('—')[-1].strip(),
            'app_url': l.app_url,
            'car': (f'{l.car.brand_name} {l.car.car_name}' if l.car_id else None),
            'category': l.category,
            'category_label': _category_label(l.category) if l.category else '',
            'last_seen': l.created_at.isoformat(),
        })
        if len(out) >= limit:
            break
    return out


def _related_via_graph(my_logs, my_stems, seen_urls, limit):
    """Graph-neighbour sections of what the user has recently read.

    Maps recent (car_stem, node_title) views to occurrence blob_ids, expands via
    the RAG relationship graph, and returns neighbour sections that occur inside
    the user's own vehicles (never leaks a car they can't open). Best-effort —
    empty if the index is missing."""
    if not my_stems:
        return []
    try:
        from .rag import store
        index = store.get_index_ro()
    except Exception:
        return []

    # Recent viewed nodes (title within a car) -> seed blob_ids.
    seeds = []
    for l in my_logs[:40]:
        if not l.car_id or not l.node_title:
            continue
        stem = l.car.car_name if l.car else None
        if not stem or stem not in my_stems:
            continue
        seeds.append((stem, l.node_title.strip()))
    if not seeds:
        return []

    seed_blobs = []
    try:
        for stem, title in seeds[:20]:
            row = index.execute(
                "SELECT blob_id FROM occurrences WHERE car_stem=? AND title=? LIMIT 1",
                (stem, title)).fetchone()
            if row:
                seed_blobs.append(row['blob_id'])
    except Exception:
        return []
    if not seed_blobs:
        return []

    # Expand to graph neighbours (labor/crosslink/semantic edges).
    neighbours = Counter()
    try:
        for bid in seed_blobs[:20]:
            for e in index.execute(
                    "SELECT dst_blob, weight FROM edges WHERE src_blob=? "
                    "ORDER BY weight DESC LIMIT 6", (bid,)).fetchall():
                neighbours[e['dst_blob']] += (e['weight'] or 1.0)
    except Exception:
        return []
    for bid in seed_blobs:
        neighbours.pop(bid, None)

    out = []
    from .rag.retrieve import _app_url
    for bid, _score in neighbours.most_common(limit * 4):
        try:
            occs = index.execute(
                "SELECT car_stem, brand, model, variant, year, title, title_path, href "
                "FROM occurrences WHERE blob_id=?", (bid,)).fetchall()
        except Exception:
            continue
        occ = next((o for o in occs if o['car_stem'] in my_stems), None)
        if not occ:
            continue
        url, segs = _app_url(occ)
        if url in seen_urls:
            continue
        out.append({
            'title': occ['title'],
            'app_url': url,
            'car': f"{occ['brand']} {occ['model']}",
            'title_path': occ['title_path'],
            'reason': 'مرتبط با آنچه اخیراً مطالعه کرده‌اید',
        })
        if len(out) >= limit:
            break
    return out


def _focus_areas(user, my_logs, granted_ids, seen_titles, limit):
    """The user's strongest technical categories + popular untouched sections in
    them across the user's fleet (content-based affinity)."""
    cat_counts = Counter(l.category for l in my_logs if l.category)
    top_cats = [c for c, _ in cat_counts.most_common(4)]
    areas = [{'category': c, 'label': _category_label(c), 'events': cat_counts[c]}
             for c in top_cats]

    suggestions = []
    if top_cats and granted_ids:
        # Popular sections (company-wide) in the user's focus categories, in cars
        # the user can open, that the user hasn't viewed yet.
        peer_logs = (ActivityLog.objects
                     .filter(category__in=top_cats, car_id__in=granted_ids)
                     .exclude(app_url='')
                     .exclude(user=user)
                     .select_related('car'))
        pop = Counter()
        meta = {}
        for l in peer_logs[:2000]:
            key = l.app_url
            title_key = (l.car_id, (l.node_title or '').strip().lower())
            if title_key in seen_titles:
                continue
            pop[key] += 1
            meta.setdefault(key, l)
        for url, n in pop.most_common(limit):
            l = meta[url]
            suggestions.append({
                'title': l.node_title,
                'app_url': url,
                'car': (f'{l.car.brand_name} {l.car.car_name}' if l.car_id else None),
                'category_label': _category_label(l.category),
                'peers': n,
            })
    return {'areas': areas, 'suggestions': suggestions}


def _popular_in_company(user, granted_ids, seen_urls, limit, days=30):
    since = timezone.now() - timezone.timedelta(days=days)
    qs = (ActivityLog.objects
          .filter(user__company_id=user.company_id, created_at__gte=since)
          .exclude(app_url='')
          .exclude(user=user)
          .select_related('car'))
    if granted_ids:
        qs = qs.filter(car_id__in=granted_ids)   # only what this user could open
    pop = Counter()
    meta = {}
    for l in qs[:3000]:
        if l.app_url in seen_urls:
            continue
        pop[l.app_url] += 1
        meta.setdefault(l.app_url, l)
    out = []
    for url, n in pop.most_common(limit):
        l = meta[url]
        out.append({
            'title': l.node_title,
            'app_url': url,
            'car': (f'{l.car.brand_name} {l.car.car_name}' if l.car_id else None),
            'category_label': _category_label(l.category) if l.category else '',
            'views': n,
        })
    return out


def _explore_untouched(user, id_to_stem, my_logs, limit):
    """Granted vehicles the user has not opened yet — a nudge to use their full
    entitlement."""
    opened = {l.car_id for l in my_logs if l.car_id}
    out = []
    cars = Car.objects.filter(id__in=[cid for cid in id_to_stem if cid not in opened])
    for c in cars[:limit]:
        out.append({
            'car': f'{c.brand_name} {c.car_name} {c.year}',
            'app_url': f'/{c.brand_name}/{c.year}/{c.car_name}',
        })
    return out


# ---------------------------------------------------------------------------
# Manager-level insights (seat utilisation, coverage, momentum)
# ---------------------------------------------------------------------------

def insights_for_manager(manager, days=30):
    from .access import manageable_user_ids, user_rank, display_role_label
    since = timezone.now() - timezone.timedelta(days=days)
    ids = manageable_user_ids(manager, include_self=False)
    members = list(PortalUser.objects.filter(id__in=ids).select_related('org_role'))

    ev_by_user = Counter()
    last_by_user = {}
    cat_by_user = defaultdict(Counter)
    for l in (ActivityLog.objects.filter(user_id__in=ids, created_at__gte=since)
              .values('user_id', 'category', 'created_at')):
        ev_by_user[l['user_id']] += 1
        if l['user_id'] not in last_by_user or l['created_at'] > last_by_user[l['user_id']]:
            last_by_user[l['user_id']] = l['created_at']
        if l['category']:
            cat_by_user[l['user_id']][l['category']] += 1

    rows = []
    for u in members:
        rows.append({
            'id': u.id, 'name': u.display_name or u.username,
            'role_label': display_role_label(u),
            'events': ev_by_user.get(u.id, 0),
            'last_active': last_by_user[u.id].isoformat() if u.id in last_by_user else None,
            'active': u.active,
            'top_category': (cat_by_user[u.id].most_common(1)[0][0]
                             if cat_by_user[u.id] else None),
        })
    rows.sort(key=lambda r: r['events'], reverse=True)

    idle = [r for r in rows if r['active'] and r['events'] == 0]
    top = [r for r in rows if r['events'] > 0][:5]

    # Company category coverage: which technical areas are under-used.
    company_cat = Counter()
    for l in (ActivityLog.objects
              .filter(user__company_id=manager.company_id, created_at__gte=since)
              .exclude(category='')
              .values_list('category', flat=True)):
        company_cat[l] += 1
    covered = {c for c, _ in CONTENT_CATEGORIES}
    coverage = [{'category': c, 'label': _category_label(c), 'events': company_cat.get(c, 0)}
                for c in covered]
    coverage.sort(key=lambda x: x['events'], reverse=True)
    gaps = [c for c in coverage if c['events'] == 0]

    return {
        'range_days': days,
        'members': rows,
        'idle_members': idle,
        'top_members': top,
        'seat_utilisation': {
            'total': len(rows),
            'active': sum(1 for r in rows if r['events'] > 0),
            'idle': len(idle),
        },
        'category_coverage': coverage,
        'category_gaps': gaps,
        'generated_at': timezone.now().isoformat(),
    }


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------

def recommendations_view(request):
    """GET /api/recommendations/ -> personalised suggestions for the logged-in
    portal user (continue / related / focus areas / popular / explore)."""
    from .portal import portal_user
    user = portal_user(request)
    if not user:
        return JsonResponse({'error': 'unauthorized'}, status=401)
    try:
        limit = max(1, min(int(request.GET.get('limit') or 6), 20))
    except (TypeError, ValueError):
        limit = 6
    return JsonResponse(recommend_for_user(user, limit=limit))


def manager_insights_view(request):
    """GET /api/team/insights/ -> team behavioural insights for a manager
    (seat utilisation, idle/top members, category coverage + gaps)."""
    from .portal import portal_user
    user = portal_user(request)
    if not user:
        return JsonResponse({'error': 'unauthorized'}, status=401)
    if not (user.can_view_analytics or user.can_manage_team):
        return JsonResponse({'error': 'دسترسی لازم را ندارید.'}, status=403)
    try:
        days = max(1, min(int(request.GET.get('range') or 30), 365))
    except (TypeError, ValueError):
        days = 30
    return JsonResponse(insights_for_manager(user, days=days))
