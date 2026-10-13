"""Product insights: what people search for, what they can't find, and where
companies drop out of the adoption funnel.

  * ``record_search``      — called by views.search_view after every search;
                             one SearchLog row (best-effort, never raises).
  * ``admin_search_view``  — GET /api/admin/insights/search/?days=30&car=
  * ``admin_funnel_view``  — GET /api/admin/insights/funnel/?days=30

The funnel is computed from data the platform already keeps (VisitorSeen,
PurchaseRequest, Company, PortalUser, ActivityLog, ChatLog), so it is exact
for everything after the first visit and needs no client-side tracking.
"""
import logging
import time
from datetime import timedelta

from django.db.models import Avg, Count, Max, Q
from django.http import JsonResponse
from django.utils import timezone

from .admin_auth import require_admin_token
from .models import (ActivityLog, ChatLog, Company, PortalUser, PurchaseRequest,
                     SearchLog, VisitorSeen)

log = logging.getLogger('kgkg.insights')

_DEDUPE_S = 60   # a re-render of the same results page is not a new search


def record_search(user, query, car, results, started):
    try:
        q = (query or '').strip()[:300]
        if not q:
            return
        n = len(results) if isinstance(results, list) else 0
        top = ''
        if n and isinstance(results[0], dict):
            top = str(results[0].get('title') or '')[:300]
        recent = SearchLog.objects.filter(
            user_id=getattr(user, 'id', None), car=(car or '')[:200], query=q,
            created_at__gte=timezone.now() - timedelta(seconds=_DEDUPE_S))
        if recent.exists():
            return
        SearchLog.objects.create(
            user_id=getattr(user, 'id', None), company_id=getattr(user, 'company_id', None),
            query=q, query_norm=q.lower(), car=(car or '')[:200], results=n,
            top_title=top, latency_ms=int((time.monotonic() - started) * 1000))
    except Exception:
        log.exception('search log write failed')


def _days(request, default=30):
    try:
        return max(1, min(int(request.GET.get('days') or default), 365))
    except ValueError:
        return default


@require_admin_token
def admin_search_view(request):
    days = _days(request)
    since = timezone.now() - timedelta(days=days)
    qs = SearchLog.objects.filter(created_at__gte=since)
    if request.GET.get('car'):
        qs = qs.filter(car=request.GET['car'])
    if request.GET.get('company_id'):
        qs = qs.filter(company_id=request.GET['company_id'])
    total = qs.count()
    zero = qs.filter(results=0)

    def top(q, n=50):
        return [{'query': r['query_norm'], 'count': r['n'], 'users': r['u'],
                 'last': r['last'].isoformat()}
                for r in (q.values('query_norm')
                          .annotate(n=Count('id'), u=Count('user_id', distinct=True),
                                    last=Max('created_at'))
                          .order_by('-n')[:n])]

    # Assistant questions answered without any grounding source = the same
    # "content gap" signal from the chat side.
    ungrounded = (ChatLog.objects.filter(created_at__gte=since, grounded=False)
                  .values('question', 'vehicle', 'created_at').order_by('-created_at')[:50])
    return JsonResponse({
        'days': days,
        'total_searches': total,
        'searchers': qs.values('user_id').distinct().count(),
        'zero_result_searches': zero.count(),
        'zero_result_rate': round(zero.count() / total, 3) if total else None,
        'avg_latency_ms': qs.aggregate(a=Avg('latency_ms'))['a'],
        'top_queries': top(qs),
        'top_zero_result_queries': top(zero),
        'by_car': [{'car': r['car'], 'searches': r['n'],
                    'zero_results': r['z']}
                   for r in (qs.values('car').annotate(n=Count('id'),
                                                       z=Count('id', filter=Q(results=0)))
                             .order_by('-n')[:30])],
        'assistant_ungrounded': [{'question': r['question'][:300], 'vehicle': r['vehicle'],
                                  'at': r['created_at'].isoformat()} for r in ungrounded],
    })


@require_admin_token
def admin_funnel_view(request):
    """Adoption funnel over the window. Visitors are daily-unique (summed per
    day, so a returning visitor counts once per day); later stages are exact."""
    days = _days(request)
    now = timezone.now()
    since = now - timedelta(days=days)
    act = ActivityLog.objects.filter(created_at__gte=since)

    pr = PurchaseRequest.objects.filter(created_at__gte=since)
    companies_new = Company.objects.filter(created_at__gte=since) \
        if hasattr(Company, 'created_at') else Company.objects.none()
    users_new = PortalUser.objects.filter(created_at__gte=since) \
        if hasattr(PortalUser, 'created_at') else PortalUser.objects.none()

    logged_in = set(act.filter(action='login').values_list('user_id', flat=True))
    viewed = set(act.filter(action__in=('view_node', 'view_section', 'parts_view'))
                 .values_list('user_id', flat=True))
    asked = set(act.filter(action='ask_assistant').values_list('user_id', flat=True))
    # "Retained": active on 3+ distinct days in the window.
    from django.db.models.functions import TruncDate
    retained = (act.annotate(d=TruncDate('created_at')).values('user_id')
                .annotate(nd=Count('d', distinct=True)).filter(nd__gte=3).count())

    stages = [
        ('visitors', 'بازدیدکنندهٔ یکتای روزانه',
         VisitorSeen.objects.filter(day__gte=since.date()).count()),
        ('purchase_requests', 'درخواست خرید', pr.count()),
        ('purchase_approved', 'درخواست تأییدشده', pr.filter(status='approved').count()),
        ('companies_created', 'شرکت جدید', companies_new.count()),
        ('users_created', 'کاربر جدید', users_new.count()),
        ('active_users', 'کاربر واردشده', len(logged_in)),
        ('content_users', 'کاربر بازدیدکنندهٔ محتوا', len(viewed)),
        ('assistant_users', 'کاربر دستیار هوشمند', len(asked)),
        ('retained_users', 'کاربر فعال در ۳+ روز', retained),
    ]
    return JsonResponse({
        'days': days,
        'stages': [{'key': k, 'label': lbl, 'count': n} for k, lbl, n in stages],
        'purchase_requests_by_status': dict(pr.values_list('status').annotate(n=Count('id'))),
        'dormant_accounts': PortalUser.objects.filter(
            Q(last_login_at__lt=since) | Q(last_login_at__isnull=True),
            active=True, password_set=True).count(),
        'invited_not_accepted': PortalUser.objects.filter(password_set=False).count(),
    })


@require_admin_token
def admin_ai_cost_view(request):
    """GET /api/admin/insights/ai-cost/?days=30 — assistant spend and speed.

    Cost is Metis's own reported figure (its billing currency); answers from
    before usage tracking (or no-LLM fallbacks) carry no cost and are counted
    separately so averages are not diluted."""
    from django.db.models import Sum
    from django.db.models.functions import TruncDate
    days = _days(request)
    qs = ChatLog.objects.filter(created_at__gte=timezone.now() - timedelta(days=days))
    agg = dict(answers=Count('id'), cost=Sum('llm_cost'), input_tokens=Sum('input_tokens'),
               output_tokens=Sum('output_tokens'), avg_latency_ms=Avg('latency_ms'),
               avg_llm_latency_ms=Avg('llm_latency_ms'),
               degraded=Count('id', filter=Q(degraded=True)),
               ungrounded=Count('id', filter=Q(grounded=False)))
    totals = qs.aggregate(**agg)
    totals['priced_answers'] = qs.filter(llm_cost__isnull=False).count()
    by_company = [{'company_id': r['company_id'], 'company': r['company__name'],
                   'answers': r['answers'], 'cost': r['cost'],
                   'avg_latency_ms': r['avg_latency_ms']}
                  for r in (qs.values('company_id', 'company__name')
                            .annotate(answers=Count('id'), cost=Sum('llm_cost'),
                                      avg_latency_ms=Avg('latency_ms'))
                            .order_by('-cost', '-answers')[:30])]
    by_day = [{'day': r['d'].isoformat(), 'answers': r['answers'], 'cost': r['cost']}
              for r in (qs.annotate(d=TruncDate('created_at')).values('d')
                        .annotate(answers=Count('id'), cost=Sum('llm_cost')).order_by('d'))]
    top_users = [{'user': r['user__username'], 'company': r['company__name'],
                  'answers': r['answers'], 'cost': r['cost']}
                 for r in (qs.values('user__username', 'company__name')
                           .annotate(answers=Count('id'), cost=Sum('llm_cost'))
                           .order_by('-cost', '-answers')[:15])]
    return JsonResponse({'days': days, 'totals': totals, 'by_company': by_company,
                         'by_day': by_day, 'top_users': top_users})
