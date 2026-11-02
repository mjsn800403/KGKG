"""The general feedback channel.

Before this module the only digital feedback surface in the product was the
thumb on an assistant answer (api/chatlog.py ``feedback_view``). An opinion
about any other page — a confusing screen, a slow search, a suggestion — had
nowhere to go but a telephone call, which is the "traditional and manual
customer feedback collection" the evaluation found. See
audit-evidence/16-improvement-programme/ROOT_CAUSE_ANALYSIS.md, Finding 4.

This is deliberately NOT a ticket. A ticket asks for something to be done and
carries an SLA; feedback is an observation. Keeping them apart keeps both
measurable: support metrics are not diluted by opinions, and feedback volume is
not inflated by support load.

    POST /api/feedback/submit/   {page?, rating? 1..5, comment?}   any seat
    GET  /api/admin/feedback/?days=30                              admin
"""
from datetime import timedelta

from django.db.models import Avg, Count, Q
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from . import events
from .admin_auth import require_admin_token
from .models import Feedback
from .portal import _body
from .portal_auth import require_portal_user
from .ratelimit import rate_limited

MAX_COMMENT = 2000


def _rating(raw):
    """(rating, error). Absent is fine; present and not 1..5 is not."""
    if raw is None:
        return None, None
    if isinstance(raw, bool) or not isinstance(raw, int):
        return None, 'امتیاز باید عددی بین ۱ تا ۵ باشد.'
    if not 1 <= raw <= 5:
        return None, 'امتیاز باید عددی بین ۱ تا ۵ باشد.'
    return raw, None


@csrf_exempt
@rate_limited('feedback', 30, 60)
@require_portal_user
def submit_view(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)
    user = request.portal_user
    b = _body(request)
    rating, err = _rating(b.get('rating'))
    if err:
        return JsonResponse({'error': err}, status=400)
    comment = (str(b.get('comment') or '')).strip()[:MAX_COMMENT]
    if rating is None and not comment:
        return JsonResponse({'error': 'امتیاز یا توضیح لازم است.'}, status=400)
    f = Feedback.objects.create(user=user, company_id=user.company_id,
                                page=(str(b.get('page') or '')).strip()[:200],
                                rating=rating, comment=comment)
    # Admins see it arrive on their dashboard the moment it is sent; nobody has
    # to remember to look.
    events.emit('feedback.created',
                {'id': f.id, 'page': f.page, 'rating': f.rating,
                 'comment': f.comment[:300],
                 'company': {'id': user.company_id,
                             'name': user.company.name if user.company_id else ''}},
                audience='admin')
    return JsonResponse({'ok': True, 'id': f.id})


def _days(request, default=30):
    try:
        return max(1, min(int(request.GET.get('days') or default), 365))
    except (TypeError, ValueError):
        return default


def summary(since):
    """The aggregate the admin feed and the support-metrics endpoint share, so
    both report the same number from the same query."""
    qs = Feedback.objects.filter(created_at__gte=since)
    agg = qs.aggregate(submissions=Count('id'), avg_rating=Avg('rating'),
                       rated=Count('id', filter=Q(rating__isnull=False)),
                       with_comment=Count('id', filter=~Q(comment='')))
    return qs, agg


@require_admin_token
def admin_feedback_view(request):
    days = _days(request)
    since = timezone.now() - timedelta(days=days)
    qs, agg = summary(since)
    items = [{'id': f.id, 'page': f.page, 'rating': f.rating, 'comment': f.comment,
              'handled': f.handled,
              'user': (f.user.display_name or f.user.username) if f.user_id else None,
              'company': f.company.name if f.company_id else None,
              'created_at': f.created_at.isoformat()}
             for f in qs.select_related('user', 'company')[:300]]
    by_page = [{'page': r['page'], 'submissions': r['n'], 'avg_rating': r['avg']}
               for r in (qs.values('page').annotate(n=Count('id'), avg=Avg('rating'))
                         .order_by('-n')[:50])]
    return JsonResponse({'days': days, 'totals': agg, 'items': items, 'by_page': by_page})
