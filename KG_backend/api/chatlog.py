"""Assistant chat logs: record every exchange, let the right people read them.

* POST /api/auth/chat-log/   — the Next chat route (acting as the signed-in
  portal user) records one question + final answer.
* GET  /api/team/chat-logs/  — a company manager: only users in their
  org-graph reach (access.manageable_user_ids, same scope as team analytics).
* GET  /api/admin/chat-logs/ — a platform admin: every company.
"""
from django.db.models import Count, Q
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .access import manageable_user_ids
from .admin_auth import require_admin_token
from .models import ChatLog, PortalUser
from .portal_auth import require_analytics

PAGE = 50


def _clean_sources(raw):
    out = []
    for s in (raw if isinstance(raw, list) else [])[:12]:
        if isinstance(s, dict):
            out.append({'title': str(s.get('title') or '')[:300],
                        'href': str(s.get('href') or s.get('app_url') or '')[:600]})
    return out


@csrf_exempt
def record_view(request):
    from .portal import portal_user
    from .views import _post_body
    if request.method != 'POST':
        return JsonResponse({'error': 'method not allowed'}, status=405)
    user = portal_user(request)
    if not user:
        return JsonResponse({'error': 'unauthorized'}, status=401)
    b = _post_body(request)
    q = str(b.get('question') or '').strip()
    if not q:
        return JsonResponse({'error': 'empty'}, status=400)
    log = ChatLog.objects.create(
        user=user, company_id=user.company_id,
        session_id=str(b.get('session_id') or '')[:100],
        question=q[:4000], answer=str(b.get('answer') or '')[:20000],
        mode=str(b.get('mode') or '')[:20], grounded=bool(b.get('grounded')),
        degraded=bool(b.get('degraded')), vehicle=str(b.get('vehicle') or '')[:200],
        sources=_clean_sources(b.get('sources')))
    return JsonResponse({'id': log.id}, status=201)


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _listing(request, qs, users_qs):
    """Shared filtering + pagination + payload for both readers."""
    uid, cid = _int(request.GET.get('user_id')), _int(request.GET.get('company_id'))
    if cid:
        qs = qs.filter(company_id=cid)
        users_qs = users_qs.filter(company_id=cid)
    users = [{'id': u['user_id'], 'user': u['user__username'],
              'name': u['user__display_name'], 'n': u['n']}
             for u in qs.filter(user__in=users_qs)
             .values('user_id', 'user__username', 'user__display_name')
             .annotate(n=Count('id')).order_by('user__username')]
    if uid:
        qs = qs.filter(user_id=uid)
    text = (request.GET.get('q') or '').strip()
    if text:
        qs = qs.filter(Q(question__icontains=text) | Q(answer__icontains=text))
    page = max(1, _int(request.GET.get('page')) or 1)
    total = qs.count()
    rows = qs.select_related('user', 'company')[(page - 1) * PAGE: page * PAGE]
    items = [{
        'id': r.id, 'user_id': r.user_id, 'user': r.user.username,
        'name': r.user.display_name, 'company_id': r.company_id, 'company': r.company.name,
        'session_id': r.session_id, 'question': r.question, 'answer': r.answer,
        'mode': r.mode, 'grounded': r.grounded, 'degraded': r.degraded,
        'vehicle': r.vehicle, 'sources': r.sources, 'created_at': r.created_at.isoformat(),
    } for r in rows]
    return JsonResponse({'items': items, 'total': total, 'page': page,
                         'pages': max(1, -(-total // PAGE)), 'users': users})


@require_analytics
def team_view(request):
    viewer = request.viewer
    ids = manageable_user_ids(viewer, include_self=True)
    users = PortalUser.objects.filter(id__in=ids, company_id=viewer.company_id)
    # company_id is pinned to the viewer's company, never taken from the query.
    request.GET = request.GET.copy()
    request.GET.pop('company_id', None)
    return _listing(request, ChatLog.objects.filter(user__in=users), users)


@require_admin_token
def admin_view(request):
    return _listing(request, ChatLog.objects.all(), PortalUser.objects.all())
