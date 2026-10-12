"""AI-assistant question allowance per user (the plans' promise, enforced).

Allowances mirror kg_frontend/src/lib/pricing.js PLANS[*].aiPerSeat:
demo 5 and 2-day 20 for the whole access window; monthly 150 and annual 200
per rolling 30 days. Every answered question is one ``ask_assistant``
ActivityLog row, so usage is also visible in the activity report and
analytics (which used to miss assistant use entirely).
"""
from datetime import timedelta

from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse

from .models import ActivityLog

ACTION = 'ask_assistant'
# plan -> (questions per user, window in days; None = whole access window)
PLAN_AI = {'demo': (5, None), 'pass': (20, None), 'monthly': (150, 30), 'annual': (200, 30)}
# PurchaseRequest.year carries the plan code for subscription requests.
REQUEST_PLAN = {'demo': 'demo', '2day': 'pass', 'monthly': 'monthly', 'annual': 'annual'}


def company_plan(company):
    """The company's plan id. Stored on Company.plan for companies provisioned
    from a request; older companies are inferred from the demo flag / the
    admin's subscription note."""
    plan = (getattr(company, 'plan', '') or '').strip()
    if plan in PLAN_AI:
        return plan
    if company.is_demo:
        return 'demo'
    note = company.note or ''
    if '۲ روزه' in note or '2 روزه' in note:
        return 'pass'
    if 'ماهانه' in note:
        return 'monthly'
    return 'annual'


def usage(user):
    plan = company_plan(user.company)
    limit, days = PLAN_AI[plan]
    qs = ActivityLog.objects.filter(user=user, action=ACTION)
    if days:
        qs = qs.filter(created_at__gte=timezone.now() - timedelta(days=days))
    used = qs.count()
    return {'plan': plan, 'limit': limit, 'used': used,
            'remaining': max(0, limit - used), 'period_days': days}


def exhausted_message(u):
    per = 'در ۳۰ روز اخیر' if u['period_days'] else 'در این دوره'
    return (f'سهمیهٔ پرسش از دستیار هوشمند شما ({u["limit"]} پرسش {per}) تمام شده است. '
            f'برای افزایش سهمیه با مدیر شرکت یا پشتیبانی تماس بگیرید.')


@csrf_exempt
def ai_usage_view(request):
    """GET  /api/auth/ai-usage/ -> {plan, limit, used, remaining, period_days}
    POST /api/auth/ai-usage/ {detail?, car?} -> consume one question, or 429
    with a Persian message when the allowance is used up."""
    from .portal import portal_user
    user = portal_user(request)
    if not user:
        return JsonResponse({'error': 'unauthorized'}, status=401)
    u = usage(user)
    if request.method != 'POST':
        return JsonResponse(u)
    if u['remaining'] <= 0:
        return JsonResponse({'error': exhausted_message(u), 'quota': u}, status=429)
    from .views import _post_body
    b = _post_body(request)
    ActivityLog.objects.create(user=user, action=ACTION,
                               detail=str(b.get('detail') or '')[:400])
    u['used'] += 1
    u['remaining'] -= 1
    return JsonResponse({'ok': True, 'quota': u})
