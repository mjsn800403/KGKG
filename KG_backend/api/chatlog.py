"""Assistant chat logs: record every exchange, let the right people read them.

* POST /api/auth/chat-log/   — the Next chat route (acting as the signed-in
  portal user) records one question + final answer.
* GET  /api/team/chat-logs/  — a company manager: only users in their
  org-graph reach (access.manageable_user_ids, same scope as team analytics).
* GET  /api/admin/chat-logs/ — a platform admin: every company.
"""
from django.db.models import Avg, Count, Q, Sum
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
    from .flags import clean_flags
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
        sources=_clean_sources(b.get('sources')),
        latency_ms=_int(b.get('latency_ms')), llm_latency_ms=_int(b.get('llm_latency_ms')),
        input_tokens=_int(b.get('input_tokens')), output_tokens=_int(b.get('output_tokens')),
        llm_cost=_float(b.get('llm_cost')),
        llm_usage=b.get('llm_usage') if isinstance(b.get('llm_usage'), dict) else {},
        client_key=str(b.get('client_key') or '')[:40],
        flags=clean_flags(b.get('flags')))
    _mark_rephrase(log)
    return JsonResponse({'id': log.id}, status=201)


REPHRASE_WINDOW_S = 150


def _words(text):
    import re
    return {w for w in re.findall(r'\w+', text.lower()) if len(w) > 1}


def _mark_rephrase(log):
    """A quick follow-up that mostly repeats the previous question means the
    previous answer missed: flag that previous row."""
    from datetime import timedelta
    prev = (ChatLog.objects.filter(user_id=log.user_id, session_id=log.session_id,
                                   created_at__gte=log.created_at - timedelta(seconds=REPHRASE_WINDOW_S))
            .exclude(pk=log.pk).order_by('-id').first())
    if not prev:
        return
    a, b = _words(prev.question), _words(log.question)
    if a and b and len(a & b) / len(a | b) >= 0.35:
        ChatLog.objects.filter(pk=prev.pk).update(rephrased=True)


@csrf_exempt
def feedback_view(request):
    """POST /api/auth/chat-feedback/ {key, kind: vote|copy|source, verdict, reason, comment}
    — the signed-in user's own exchange only."""
    from django.db.models import F
    from django.utils import timezone
    from .portal import portal_user
    from .views import _post_body
    if request.method != 'POST':
        return JsonResponse({'error': 'method not allowed'}, status=405)
    user = portal_user(request)
    if not user:
        return JsonResponse({'error': 'unauthorized'}, status=401)
    b = _post_body(request)
    key = str(b.get('key') or '')[:40]
    qs = ChatLog.objects.filter(client_key=key, user=user) if key else ChatLog.objects.none()
    if not qs.exists():
        return JsonResponse({'error': 'not found'}, status=404)
    kind = b.get('kind')
    if kind == 'vote':
        v = _int(b.get('verdict')) or 0
        qs.update(feedback=1 if v > 0 else -1, feedback_reason=str(b.get('reason') or '')[:20],
                  feedback_comment=str(b.get('comment') or '')[:1000], feedback_at=timezone.now())
    elif kind == 'copy':
        qs.update(copied=True)
    elif kind == 'source':
        qs.update(source_clicks=F('source_clicks') + 1)
    else:
        return JsonResponse({'error': 'bad kind'}, status=400)
    return JsonResponse({'ok': True})


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _float(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _listing(request, qs, users_qs, with_cost=False):
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
        'latency_ms': r.latency_ms,
        **({'llm_latency_ms': r.llm_latency_ms, 'input_tokens': r.input_tokens,
            'output_tokens': r.output_tokens, 'llm_cost': r.llm_cost} if with_cost else {}),
    } for r in rows]
    out = {'items': items, 'total': total, 'page': page,
           'pages': max(1, -(-total // PAGE)), 'users': users}
    if with_cost:
        # Totals over the whole filtered set, not just this page. Cost is Metis's
        # own reported figure (its billing currency), platform-admin only.
        out['totals'] = qs.aggregate(
            input_tokens=Sum('input_tokens'), output_tokens=Sum('output_tokens'),
            llm_cost=Sum('llm_cost'), avg_latency_ms=Avg('latency_ms'),
            avg_llm_latency_ms=Avg('llm_latency_ms'))
    return JsonResponse(out)


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
    return _listing(request, ChatLog.objects.all(), PortalUser.objects.all(), with_cost=True)
