"""Assistant usage behaviour: what people ask, how long they spend, and whether
the answers helped.

Signals per ChatLog row (api/chatlog.py fills them):
* ``feedback`` +1 / -1 (with reason/comment) from the 👍/👎 bar,
* ``copied`` — the user copied text out of the answer,
* ``source_clicks`` — links in the answer / its sources that were opened,
* ``rephrased`` — the next question in the same conversation came quickly and
  looked like the same question reworded (a strong "not what I wanted" hint).

GET /api/admin/insights/assistant/?days=30          — dashboard payload
GET /api/admin/insights/assistant/?session=<id>     — one conversation
GET /api/admin/insights/assistant/?log=<id>         — a single exchange
"""
from collections import Counter, defaultdict
from datetime import timedelta

from django.db.models import Count, Q
from django.http import JsonResponse
from django.utils import timezone

from .admin_auth import require_admin_token
from .models import ChatLog

FIELDS = ('id', 'session_id', 'created_at', 'question', 'answer', 'vehicle', 'mode', 'grounded',
          'degraded', 'latency_ms', 'feedback', 'feedback_reason', 'feedback_comment', 'copied',
          'source_clicks', 'rephrased', 'user_id', 'user__username', 'user__display_name',
          'company__name')


def _days(request):
    try:
        return max(1, min(int(request.GET.get('days', 30)), 365))
    except ValueError:
        return 30


def _msg(r, full=True):
    return {'id': r['id'], 'at': r['created_at'].isoformat(), 'question': r['question'],
            'answer': r['answer'] if full else r['answer'][:300], 'vehicle': r['vehicle'],
            'mode': r['mode'], 'grounded': r['grounded'], 'degraded': r['degraded'],
            'latency_ms': r['latency_ms'], 'feedback': r['feedback'],
            'reason': r['feedback_reason'], 'comment': r['feedback_comment'],
            'copied': r['copied'], 'source_clicks': r['source_clicks'],
            'rephrased': r['rephrased'],
            'user': r['user__display_name'] or r['user__username'],
            'company': r['company__name'], 'session': r['session_id']}


def _rate(a, b):
    return round(a / b, 3) if b else None


@require_admin_token
def admin_assistant_view(request):
    if request.GET.get('session') or request.GET.get('log'):
        qs = (ChatLog.objects.filter(session_id=request.GET['session'])
              if request.GET.get('session') else ChatLog.objects.filter(pk=request.GET['log']))
        return JsonResponse({'messages': [_msg(r) for r in qs.order_by('created_at').values(*FIELDS)[:200]]})

    days = _days(request)
    since = timezone.now() - timedelta(days=days)
    every = ChatLog.objects.filter(created_at__gte=since)
    # Rows recovered from ActivityLog have only the question: they count for
    # "what was asked", never for behaviour/satisfaction.
    rows = list(every.exclude(mode='backfill').values(*FIELDS))
    n = len(rows)
    rated = [r for r in rows if r['feedback']]
    up = sum(1 for r in rated if r['feedback'] > 0)

    # Conversations: group by session id; rows without one stand alone.
    sess = defaultdict(list)
    for r in rows:
        sess[r['session_id'] or f"log:{r['id']}"].append(r)
    sessions = []
    for key, rs in sess.items():
        rs.sort(key=lambda r: r['created_at'])
        last = rs[-1]
        span = (last['created_at'] - rs[0]['created_at']).total_seconds() + (last['latency_ms'] or 0) / 1000
        engaged = any(r['feedback'] or r['copied'] or r['source_clicks'] for r in rs)
        sessions.append({
            'key': key, 'user_id': rs[0]['user_id'],
            'user': rs[0]['user__display_name'] or rs[0]['user__username'],
            'company': rs[0]['company__name'], 'vehicle': next((r['vehicle'] for r in rs if r['vehicle']), ''),
            'start': rs[0]['created_at'].isoformat(), 'questions': len(rs), 'seconds': round(span),
            'up': sum(1 for r in rs if (r['feedback'] or 0) > 0),
            'down': sum(1 for r in rs if (r['feedback'] or 0) < 0),
            'rephrased': sum(1 for r in rs if r['rephrased']), 'engaged': engaged,
            'first_question': rs[0]['question'][:200]})
    sessions.sort(key=lambda s: s['start'], reverse=True)
    ns = len(sessions)

    per_user = defaultdict(lambda: {'sessions': 0, 'questions': 0, 'seconds': 0, 'up': 0, 'down': 0})
    for s in sessions:
        u = per_user[(s['user_id'], s['user'], s['company'])]
        u['sessions'] += 1
        u['questions'] += s['questions']
        u['seconds'] += s['seconds']
        u['up'] += s['up']
        u['down'] += s['down']
    users = sorted(({'user_id': k[0], 'user': k[1], 'company': k[2], **v} for k, v in per_user.items()),
                   key=lambda u: -u['questions'])[:50]

    def grouped(key):
        g = defaultdict(lambda: {'questions': 0, 'up': 0, 'down': 0, 'rephrased': 0})
        for r in rows:
            x = g[r[key] or '—']
            x['questions'] += 1
            x['up'] += (r['feedback'] or 0) > 0
            x['down'] += (r['feedback'] or 0) < 0
            x['rephrased'] += r['rephrased']
        return sorted(({'name': k, **v, 'satisfaction': _rate(v['up'], v['up'] + v['down'])}
                       for k, v in g.items()), key=lambda x: -x['questions'])[:30]

    by_day = defaultdict(lambda: {'questions': 0, 'up': 0, 'down': 0})
    for r in rows:
        d = by_day[timezone.localtime(r['created_at']).date().isoformat()]
        d['questions'] += 1
        d['up'] += (r['feedback'] or 0) > 0
        d['down'] += (r['feedback'] or 0) < 0

    asked = Counter(' '.join(q.split()).strip(' ؟?.').lower()
                    for q in every.values_list('question', flat=True))
    top_q = [{'question': q, 'count': c} for q, c in asked.most_common(30) if q]

    total_sec = sum(s['seconds'] for s in sessions)
    return JsonResponse({
        'days': days,
        'totals': {
            'questions': n, 'backfilled': every.filter(mode='backfill').count(),
            'users': len({r['user_id'] for r in rows}), 'sessions': ns,
            'avg_questions_per_session': round(n / ns, 2) if ns else None,
            'avg_session_seconds': round(total_sec / ns) if ns else None,
            'total_minutes': round(total_sec / 60, 1),
            'rated': len(rated), 'up': up, 'down': len(rated) - up,
            'satisfaction': _rate(up, len(rated)),
            'rephrase_rate': _rate(sum(r['rephrased'] for r in rows), n),
            'copy_rate': _rate(sum(r['copied'] for r in rows), n),
            'source_click_rate': _rate(sum(1 for r in rows if r['source_clicks']), n),
            'no_engagement_rate': _rate(sum(1 for s in sessions if not s['engaged']), ns),
            'ungrounded_rate': _rate(sum(1 for r in rows if not r['grounded']), n),
        },
        'by_day': [{'day': k, **v} for k, v in sorted(by_day.items())],
        'by_car': grouped('vehicle'),
        'by_company': grouped('company__name'),
        'users': users,
        'sessions': sessions[:100],
        'downvoted': [_msg(r, full=False) for r in sorted(
            (r for r in rows if (r['feedback'] or 0) < 0), key=lambda r: r['created_at'], reverse=True)[:50]],
        'rephrased': [_msg(r, full=False) for r in sorted(
            (r for r in rows if r['rephrased']), key=lambda r: r['created_at'], reverse=True)[:30]],
        'top_questions': top_q,
    })
