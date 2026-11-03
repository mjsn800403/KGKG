"""Tunable defaults for the support chat, read from the environment at call time.

Every limit is an initial default, not a constant: an operator changes it with
``KG_SC_<NAME>="N/seconds"`` (``0/0`` switches that limit off). Nothing here
makes a promise to customers; the reply target is unset unless the owner sets it.
"""
import os

#: name -> (requests, window seconds)
DEFAULT_LIMITS = {
    'poll': (30, 60),            # per thread; 3 s polling is 20 / min
    'send': (20, 60),            # per thread
    'send_hour': (30, 3600),     # per thread, enforced against the stored messages
    'contact': (10, 60),         # per thread
    'csat': (5, 60),             # per thread
    'reopen': (5, 60),           # per thread
    'create_ip': (20, 600),      # per IP: an office behind one NAT may start several chats
    'bad_token_ip': (30, 60),    # per IP, counting FAILED token checks only
    'status_ip': (60, 60),       # per IP
}


def limit(name):
    """(count, window_seconds) for ``name``; (0, 0) means unlimited."""
    default = DEFAULT_LIMITS[name]
    raw = os.environ.get(f'KG_SC_{name.upper()}', '').strip()
    if not raw:
        return default
    try:
        count, _, window = raw.partition('/')
        count, window = int(count), float(window)
    except ValueError:
        return default
    if count <= 0 or window <= 0:
        return (0, 0)
    return (count, window)


def _int(name, default, minimum=1):
    try:
        value = int(os.environ.get(name, '').strip())
    except ValueError:
        return default
    return value if value >= minimum else default


def reopen_days():
    """How long after closing a visitor may reopen their own thread."""
    return _int('KG_SUPPORT_REOPEN_DAYS', 14)


def reply_target_minutes():
    """The response time the owner has chosen to publish, or None (no promise)."""
    try:
        value = int(os.environ.get('KG_SUPPORT_REPLY_TARGET_MINUTES', '').strip())
    except ValueError:
        return None
    return value if value > 0 else None


def presence_window_seconds():
    return _int('KG_SUPPORT_PRESENCE_WINDOW_S', 60)


def retention():
    """Proposed retention periods in days. Used to REPORT what enforcement would
    do; deletion additionally needs KG_SUPPORT_RETENTION_ENABLED=1 and --apply."""
    return {
        'no_contact': _int('KG_SUPPORT_RETENTION_NO_CONTACT_DAYS', 30),
        'contact': _int('KG_SUPPORT_RETENTION_CONTACT_DAYS', 180),
        'spam': _int('KG_SUPPORT_RETENTION_SPAM_DAYS', 7),
        'promoted': _int('KG_SUPPORT_RETENTION_PROMOTED_DAYS', 30),
    }


def retention_enabled():
    return os.environ.get('KG_SUPPORT_RETENTION_ENABLED', '').strip() == '1'
