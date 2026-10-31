"""Per-viewer read state for support tickets, and who spoke last.

Nothing here stores a count. `unread_count` asks the question each time, from
`TicketRead.last_read_at` and the messages after it. A stored counter is what
produces a badge that survives the work it was reporting — the defect this
module exists to make impossible.

A viewer is a `PortalUser` (the customer side) or a `PlatformAdmin` (the desk).
Exactly one is passed. A customer never sees internal notes, so they never
count toward a customer's unread.
"""
from django.db.models import Max, Q
from django.utils import timezone

from .models import TicketMessage, TicketRead


def _viewer_filter(*, user, admin):
    if (user is None) == (admin is None):
        raise ValueError('pass exactly one of user= / admin=')
    return {'user': user, 'admin': admin}


def mark_read(request_obj, *, user=None, admin=None):
    """Move this viewer's mark to now. Idempotent, and safe from two tabs at
    once: `update_or_create` either inserts or moves the existing row, so the
    unique constraint is never a 500."""
    who = _viewer_filter(user=user, admin=admin)
    TicketRead.objects.update_or_create(
        request=request_obj, user=who['user'], admin=who['admin'],
        defaults={'last_read_at': timezone.now()})


def _unseen_q(*, user, admin):
    """Messages this viewer did not write and is allowed to see."""
    if user is not None:
        return ~Q(author_user_id=user.id) & Q(internal=False)
    return ~Q(author_admin_id=admin.id)


def unread_count(request_obj, *, user=None, admin=None):
    """Messages newer than the viewer's mark that they did not write. With no
    mark, everything they did not write is unread — a ticket nobody opened is
    wholly unread, which is true."""
    who = _viewer_filter(user=user, admin=admin)
    qs = request_obj.messages.filter(_unseen_q(user=user, admin=admin))
    mark = TicketRead.objects.filter(request=request_obj, user=who['user'],
                                     admin=who['admin']).values_list(
                                         'last_read_at', flat=True).first()
    if mark is not None:
        qs = qs.filter(created_at__gt=mark)
    return qs.count()


def unread_counts(request_ids, *, user=None, admin=None):
    """`{request_id: unread}` for a whole page in two queries rather than one
    per row. Only non-zero entries are returned."""
    ids = list(request_ids)
    if not ids:
        return {}
    who = _viewer_filter(user=user, admin=admin)
    marks = dict(TicketRead.objects
                 .filter(request_id__in=ids, user=who['user'], admin=who['admin'])
                 .values_list('request_id', 'last_read_at'))
    rows = (TicketMessage.objects
            .filter(request_id__in=ids)
            .filter(_unseen_q(user=user, admin=admin))
            .values('request_id', 'created_at'))
    out = {}
    for row in rows:
        mark = marks.get(row['request_id'])
        if mark is None or row['created_at'] > mark:
            out[row['request_id']] = out.get(row['request_id'], 0) + 1
    return out


def last_message(request_obj):
    """`{'at': iso, 'by': 'customer' | 'platform'}` for the newest PUBLIC
    message, or None. Internal notes are excluded: they are not a turn in the
    conversation, so they must not reorder a list sorted by activity."""
    m = (request_obj.messages.filter(internal=False)
         .order_by('-created_at', '-id')
         .values('created_at', 'author_user_id', 'author_admin_id', 'author_label')
         .first())
    if m is None:
        return None
    platform = bool(m['author_admin_id']) or m['author_label'] == 'admin'
    return {'at': m['created_at'].isoformat(),
            'by': 'platform' if platform else 'customer'}


def last_activity_map(request_ids):
    """`{request_id: datetime}` of the newest public message, for sorting a
    list by activity instead of creation."""
    ids = list(request_ids)
    if not ids:
        return {}
    rows = (TicketMessage.objects.filter(request_id__in=ids, internal=False)
            .values('request_id').annotate(at=Max('created_at')))
    return {r['request_id']: r['at'] for r in rows}
