"""Cursor pagination and literal text search for ticket lists.

Two things here are deliberate and easy to get wrong the other way.

**The cursor is opaque and untrusted.** It encodes `(created_at, id)`, which is
the list's own ordering, so a row inserted between two page fetches cannot
duplicate or hide a row already returned — the thing offset pagination gets
wrong. `decode_cursor` returns None for anything it cannot parse, and the
caller answers 400; a cursor is client input, not state.

**A search is literal, and the ORM already makes it so.** `icontains` emits
`LIKE %term% ESCAPE '\\'` with the term's `%` and `_` escaped. We therefore do
NOT escape again — doing so turns a search for `100%` into a search for a
backslash and matches nothing. `text_query` says this where someone would
otherwise be tempted to add it, and two tests pin the behaviour.
"""
import base64
import binascii
from datetime import datetime

from django.db.models import Q
from django.utils.dateparse import parse_datetime

LIMIT_DEFAULT = 30
LIMIT_MAX = 100

# A conversation is fetched newest-first and capped. An uncapped thread means
# one pathological ticket can time out the page it appears on.
MAX_THREAD = 200


def clamp_limit(raw):
    """A limit the client asked for, bounded. Anything unparsable or <1 is the
    default; anything above the maximum is the maximum, never an error — a
    rejected page size helps nobody."""
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return LIMIT_DEFAULT
    if n < 1:
        return LIMIT_DEFAULT
    return min(n, LIMIT_MAX)


def encode_cursor(created_at, row_id):
    raw = f'{created_at.isoformat()}|{int(row_id)}'
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip('=')


def decode_cursor(raw):
    """`(datetime, int)` or None. Never raises: every malformed input — wrong
    padding, wrong separator, an unparsable timestamp — is None, and the
    endpoint turns that into a 400."""
    if not raw:
        return None
    try:
        pad = '=' * (-len(raw) % 4)
        text = base64.urlsafe_b64decode(raw + pad).decode()
        stamp, _, row_id = text.rpartition('|')
        if not stamp or not row_id:
            return None
        when = parse_datetime(stamp)
        if when is None:
            return None
        return when, int(row_id)
    except (ValueError, TypeError, binascii.Error, UnicodeDecodeError):
        return None


def apply_cursor(qs, cursor):
    """Rows strictly after `cursor` in `('-created_at', '-id')` order."""
    when, row_id = cursor
    return qs.filter(Q(created_at__lt=when)
                     | Q(created_at=when, id__lt=row_id))


def page(qs, limit, cursor=None):
    """`(rows, next_cursor)`. Fetches one extra row to know whether another
    page exists, rather than issuing a second count query."""
    if cursor:
        qs = apply_cursor(qs, cursor)
    rows = list(qs[:limit + 1])
    if len(rows) > limit:
        last = rows[limit - 1]
        return rows[:limit], encode_cursor(last.created_at, last.id)
    return rows, None


def text_query(term, fields):
    """An OR over `fields` matching `term` literally, case-insensitively.

    No escaping here, and that is checked rather than assumed: Django's
    `icontains` already emits `LIKE %term% ESCAPE '\\'` with `%` and `_` in
    the term escaped for us. Escaping again would turn a search for `100%`
    into a search for a backslash followed by a percent, and match nothing —
    breaking the exact case the escaping was meant to protect. The literal-`%`
    and literal-`_` tests in test_helpdesk_desk.py are what keep this honest
    if the ORM's behaviour ever changes.
    """
    q = Q()
    for field in fields:
        q |= Q(**{f'{field}__icontains': term})
    return q


def qs_int(raw):
    """A positive integer from a query string, or None.

    Query parameters are always strings, so `requests_api._int_or_none` — which
    rejects anything not already an `int` because it guards JSON bodies — turns
    every `?car_id=3` into None and the filter silently matches everything. A
    filter that quietly returns every row is worse than one that errors, so
    query-string parsing gets its own function rather than loosening that one.
    """
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None
