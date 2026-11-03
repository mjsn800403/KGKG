"""Visitor bearer tokens.

A token is 32 random bytes, URL-safe base64 without padding: exactly 43
characters. The server keeps only its SHA-256, so a database leak does not
hand out conversations. A client may generate its own token and send it when
creating a thread; that makes the create idempotent (the same token always
maps to the same thread), which a server-generated token shown once cannot.
Anything that is not exactly that shape is rejected before any query runs.
"""
import hashlib
import hmac
import re
import secrets
import uuid

from .models import SupportThread

_FORMAT = re.compile(r'^[A-Za-z0-9_-]{43}$')


def valid_format(raw):
    return isinstance(raw, str) and bool(_FORMAT.match(raw))


def hash_token(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def new_token():
    """(raw, hash) for a fresh token."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def find_by_token(raw):
    """The thread owned by ``raw``, or None. No query for a malformed token."""
    if not valid_format(raw):
        return None
    return SupportThread.objects.filter(token_hash=hash_token(raw)).first()


def authorise(thread_id, raw):
    """The thread, if ``raw`` is its token; otherwise None. Callers answer 404
    for None so a wrong token and a missing thread look identical."""
    if not valid_format(raw):
        return None
    try:
        key = uuid.UUID(str(thread_id))
    except (ValueError, AttributeError, TypeError):
        return None
    thread = SupportThread.objects.filter(pk=key).first()
    if thread is None or not hmac.compare_digest(thread.token_hash, hash_token(raw)):
        return None
    return thread
