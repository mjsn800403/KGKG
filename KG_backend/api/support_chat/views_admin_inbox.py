"""Staff inbox (read side): list and detail of visitor threads.

    GET /api/admin/support-chat/threads/        list with filters, counts, cursor paging
    GET /api/admin/support-chat/threads/<id>/   one thread with every message

Both need a signed-in staff PERSON (the loopback script token is 403) and ask
``permissions.can``. Neither writes anything except the audit row for revealing
contact details, which carries ids only. Phone and email are masked unless the
caller asks for ``reveal_contact=1``. Searching matches the id prefix and contact
fields, never message text.
"""
import base64
import uuid

from django.db.models import Count, F, OuterRef, Q, Subquery
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from api.admin_auth import acting_admin, require_admin_token

from . import mask, permissions, rbac
from .models import SupportMessage, SupportThread
from .views_admin import audit_action

ACTIVE = ('open', 'waiting_staff', 'waiting_customer')
PRIORITIES = ('low', 'normal', 'high', 'urgent')
SNIPPET = 120
DETAIL_CAP = 500


def _deny():
    return JsonResponse({'error': 'a staff session is required'}, status=403)


def _deny_for(request):
    """403 for a non-person (the loopback token) or for a person without the permission;
    the code says whether enforcement has no owner at all (see rbac.denial_code)."""
    if acting_admin(request) is None:
        return _deny()
    return JsonResponse({'error': 'forbidden', 'code': permissions.denial_code()}, status=403)


def _bad(msg):
    return JsonResponse({'error': msg}, status=400)


def _admin(request, permission):
    admin = acting_admin(request)
    if admin is None or not permissions.can(admin, permission):
        return None
    return admin


def _contact(thread, reveal):
    return {'name': thread.contact_name,
            'has_phone': bool(thread.contact_phone), 'has_email': bool(thread.contact_email),
            'phone': thread.contact_phone if reveal else mask.phone(thread.contact_phone),
            'email': thread.contact_email if reveal else mask.email(thread.contact_email)}


def _person(admin):
    return {'id': admin.id, 'username': admin.username} if admin else None


def _annotated():
    msgs = SupportMessage.objects.filter(thread=OuterRef('pk'))
    return SupportThread.objects.select_related('assignee').annotate(
        last_visitor_at=Subquery(msgs.filter(author_kind='visitor', internal=False)
                                 .order_by('-id').values('created_at')[:1]),
        last_kind=Subquery(msgs.order_by('-id').values('author_kind')[:1]),
        last_body=Subquery(msgs.order_by('-id').values('body')[:1]),
        last_internal=Subquery(msgs.order_by('-id').values('internal')[:1]),
        last_at=Subquery(msgs.order_by('-id').values('created_at')[:1]),
        message_count=Count('messages'),
    )


def _unread_q():
    """A visitor message newer than the last time any staff member opened the thread."""
    return Q(last_visitor_at__isnull=False) & (
        Q(staff_seen_at__isnull=True) | Q(last_visitor_at__gt=F('staff_seen_at')))


def _item(t):
    return {
        'id': str(t.pk), 'intent': t.intent, 'status': t.status, 'priority': t.priority,
        'assignee': _person(t.assignee), 'contact': _contact(t, False),
        'source_page': t.source_page,
        'created_at': t.created_at.isoformat(), 'last_activity_at': t.last_activity_at.isoformat(),
        'unread': bool(t.last_visitor_at and (t.staff_seen_at is None
                                              or t.last_visitor_at > t.staff_seen_at)),
        'message_count': t.message_count, 'reopen_count': t.reopen_count,
        'last_message': None if t.last_kind is None else {
            'author_kind': t.last_kind, 'internal': bool(t.last_internal),
            'snippet': (t.last_body or '')[:SNIPPET], 'created_at': t.last_at.isoformat()},
    }


def _cursor_encode(t):
    raw = f'{t.last_activity_at.isoformat()}|{t.pk}'
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip('=')


def _cursor_decode(raw):
    try:
        text = base64.urlsafe_b64decode(raw + '=' * (-len(raw) % 4)).decode()
        stamp, _, pk = text.partition('|')
        from django.utils.dateparse import parse_datetime
        when = parse_datetime(stamp)
        return (when, uuid.UUID(pk)) if when else None
    except Exception:
        return None


def _filters(request, admin):
    """(Q, error) from the query string."""
    p = request.GET
    q = Q()
    status = p.get('status', 'active')
    if status == 'active':
        q &= Q(status__in=ACTIVE)
    elif status == 'all':
        q &= ~Q(status='spam')
    elif status in ('open', 'waiting_staff', 'waiting_customer', 'closed', 'spam'):
        q &= Q(status=status)
    else:
        return None, 'unknown status'
    if p.get('intent'):
        if p['intent'] not in dict(SupportThread.INTENT_CHOICES):
            return None, 'unknown intent'
        q &= Q(intent=p['intent'])
    if p.get('priority'):
        if p['priority'] not in PRIORITIES:
            return None, 'unknown priority'
        q &= Q(priority=p['priority'])
    who = p.get('assignee')
    if who:
        if who == 'me':
            q &= Q(assignee=admin)
        elif who == 'none':
            q &= Q(assignee__isnull=True)
        elif who.isdigit():
            q &= Q(assignee_id=int(who))
        else:
            return None, 'unknown assignee'
    if p.get('unread') == '1':
        q &= _unread_q()
    term = (p.get('q') or '').strip()
    if term:
        q &= (Q(contact_name__icontains=term) | Q(contact_phone__icontains=term)
              | Q(contact_email__icontains=term)
              | (Q(pk__istartswith=term.lower()) if _hexish(term) else Q(pk__in=[])))
    return q, None


def _hexish(term):
    return len(term) >= 4 and all(c in '0123456789abcdefABCDEF-' for c in term)


def _counts(admin):
    base = permissions.scoped_threads(admin, _annotated())
    unread = _unread_q()
    active = Q(status__in=ACTIVE)
    rows = permissions.scoped_threads(admin, SupportThread.objects.all()).aggregate(
        all=Count('pk', filter=~Q(status='spam')),
        active=Count('pk', filter=active),
        closed=Count('pk', filter=Q(status='closed')),
        spam=Count('pk', filter=Q(status='spam')),
        unassigned=Count('pk', filter=active & Q(assignee__isnull=True)),
        mine=Count('pk', filter=active & Q(assignee=admin)),
    )
    rows['unread'] = base.filter(active & unread).count()
    return rows


@csrf_exempt
@require_admin_token
def list_view(request):
    if request.method != 'GET':
        return JsonResponse({'error': 'GET only'}, status=405)
    admin = _admin(request, permissions.READ)
    if admin is None:
        return _deny_for(request)
    try:
        limit = int(request.GET.get('limit', 30))
    except ValueError:
        return _bad('limit must be a number')
    if not 1 <= limit <= 100:
        return _bad('limit must be between 1 and 100')
    flt, err = _filters(request, admin)
    if err:
        return _bad(err)
    qs = permissions.scoped_threads(admin, _annotated()).filter(flt)
    raw = request.GET.get('cursor')
    if raw:
        cur = _cursor_decode(raw)
        if cur is None:
            return _bad('bad cursor')
        when, pk = cur
        qs = qs.filter(Q(last_activity_at__lt=when) | Q(last_activity_at=when, pk__lt=pk))
    rows = list(qs.order_by('-last_activity_at', '-pk')[:limit + 1])
    more = len(rows) > limit
    rows = rows[:limit]
    return JsonResponse({'threads': [_item(t) for t in rows],
                         'next_cursor': _cursor_encode(rows[-1]) if more else None,
                         'counts': _counts(admin),
                         'server_time': timezone.now().isoformat()})


# What the caller may do to this thread, so the console offers only those actions. The server
# re-checks every request; this is a convenience, never the control.
_CAPS = {'reply': permissions.REPLY, 'take': permissions.TAKE, 'assign': permissions.ASSIGN,
         'priority': permissions.PRIORITY, 'intent': permissions.INTENT, 'close': permissions.CLOSE,
         'reopen': permissions.REOPEN, 'spam': permissions.SPAM,
         'reveal_contact': permissions.REVEAL_CONTACT}


def _capabilities(admin, thread):
    return {name: rbac.allows(admin, perm, thread) for name, perm in _CAPS.items()}


def _message(m):
    return {'id': m.id, 'author_kind': m.author_kind, 'internal': m.internal, 'body': m.body,
            'author': _person(m.author_admin), 'created_at': m.created_at.isoformat()}


@csrf_exempt
@require_admin_token
def detail_view(request, thread_id):
    if request.method != 'GET':
        return JsonResponse({'error': 'GET only'}, status=405)
    admin = _admin(request, permissions.READ)
    if admin is None:
        return _deny_for(request)
    try:
        key = uuid.UUID(str(thread_id))
    except ValueError:
        return JsonResponse({'error': 'not found'}, status=404)
    # Out-of-scope threads are filtered here, so they are a plain 404 (no existence oracle).
    thread = (permissions.scoped_threads(admin, SupportThread.objects.select_related('assignee'))
              .filter(pk=key).first())
    if thread is None:
        return JsonResponse({'error': 'not found'}, status=404)
    reveal = False
    if request.GET.get('reveal_contact') == '1' and (thread.contact_phone or thread.contact_email):
        if not permissions.can(admin, permissions.REVEAL_CONTACT, thread):
            return _deny_for(request)
        reveal = True
        audit_action(request, admin, 'reveal_contact', thread)
    try:
        after = int(request.GET.get('after') or 0)
    except ValueError:
        after = 0
    msgs = list(thread.messages.select_related('author_admin').filter(id__gt=after)
                .order_by('id')[:DETAIL_CAP])
    ratings = thread.ratings.order_by('closure', 'id')
    return JsonResponse({
        'capabilities': _capabilities(admin, thread),
        'thread': {
            'id': str(thread.pk), 'intent': thread.intent, 'status': thread.status,
            'priority': thread.priority, 'assignee': _person(thread.assignee),
            'contact': _contact(thread, reveal), 'source_page': thread.source_page,
            'referrer': thread.referrer, 'created_at': thread.created_at.isoformat(),
            'last_activity_at': thread.last_activity_at.isoformat(),
            'closed_at': thread.closed_at.isoformat() if thread.closed_at else None,
            'reopen_count': thread.reopen_count,
            'staff_seen_at': thread.staff_seen_at.isoformat() if thread.staff_seen_at else None,
        },
        'messages': [_message(m) for m in msgs],
        'ratings': [{'closure': r.closure, 'score': r.score, 'at': r.created_at.isoformat()}
                    for r in ratings],
    })
