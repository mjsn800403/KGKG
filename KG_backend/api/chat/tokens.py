"""Visitor bearer tokens. The raw token is shown to the visitor once and kept
only as a SHA-256 hash, so a database leak does not hand out conversations."""
import hashlib
import hmac
import secrets
import uuid

from .models import ChatThread


def _hash(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def new_token():
    """(raw, hash) for a fresh 32-byte token."""
    raw = secrets.token_urlsafe(32)
    return raw, _hash(raw)


def authorise(thread_id, raw):
    """The thread, if ``raw`` is its token; otherwise None. Callers answer 404
    for None so a wrong token and a missing thread look identical."""
    if not raw or not isinstance(raw, str):
        return None
    try:
        key = uuid.UUID(str(thread_id))
    except (ValueError, AttributeError, TypeError):
        return None
    thread = ChatThread.objects.filter(pk=key).first()
    if thread is None or not hmac.compare_digest(thread.token_hash, _hash(raw)):
        return None
    return thread
