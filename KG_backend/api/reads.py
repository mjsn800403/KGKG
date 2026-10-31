"""Per-viewer read state for support tickets, and who spoke last.

Nothing here stores a count. `unread_count` asks the question each time, from
`TicketRead.last_read_at` and the messages after it. A stored counter is what
produces a badge that survives the work it was reporting — the defect this
module exists to make impossible.

A viewer is a `PortalUser` (the customer side) or a `PlatformAdmin` (the desk).
Exactly one is passed. A customer never sees internal notes, so they never
count toward a customer's unread.
"""
from django.db.models import Count, Q
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
    """`{request_id: unread}` for a whole page, counted IN the database.

    Two queries, and neither transfers message rows: the earlier version
    pulled one Python row per unseen message — 150 rows to produce one integer
    on a modest page — and ran on every navigation, because the sidebar badge
    reads this endpoint. Only non-zero entries are returned.
    """
    ids = list(request_ids)
    if not ids:
        return {}
    who = _viewer_filter(user=user, admin=admin)
    marks = dict(TicketRead.objects
                 .filter(request_id__in=ids, user=who['user'], admin=who['admin'])
                 .values_list('request_id', 'last_read_at'))
    unseen = _unseen_q(user=user, admin=admin)
    # One aggregate for the rows with no mark (everything unseen counts) and a
    # per-mark condition for the rest, expressed as a single CASE sum.
    when_newer = Q()
    for req_id, mark in marks.items():
        when_newer |= Q(request_id=req_id, created_at__gt=mark)
    unmarked = [i for i in ids if i not in marks]
    scope = Q()
    if unmarked:
        scope |= Q(request_id__in=unmarked)
    if when_newer:
        scope |= when_newer
    if not scope:
        return {}
    rows = (TicketMessage.objects
            .filter(request_id__in=ids)
            .filter(unseen)
            .filter(scope)
            .values('request_id')
            .annotate(n=Count('id')))
    return {r['request_id']: r['n'] for r in rows if r['n']}


def last_messages(request_ids):
    """`{request_id: {'at': iso, 'by': ...}}` for a whole page in one query.

    `last_message` per row was costing a query each inside the serialiser; a
    ten-row page spent twenty on this and on awaiting-a-reply together.
    """
    ids = list(request_ids)
    if not ids:
        return {}
    newest = {}
    for m in (TicketMessage.objects
              .filter(request_id__in=ids, internal=False)
              .order_by('request_id', '-created_at', '-id')
              .values('request_id', 'created_at', 'author_admin_id', 'author_label')):
        newest.setdefault(m['request_id'], m)
    out = {}
    for req_id, m in newest.items():
        platform = bool(m['author_admin_id']) or m['author_label'] == 'admin'
        out[req_id] = {'at': m['created_at'].isoformat(),
                       'by': 'platform' if platform else 'customer'}
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

