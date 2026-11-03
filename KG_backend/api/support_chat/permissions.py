"""The one place views ask what a signed-in staff member may do in support.

This is a thin facade over :mod:`rbac`, which owns the matrix and the rollout mode
(``KG_SUPPORT_RBAC``: ``off`` is the default and keeps today's flat admin model).
The loopback script token is never a person and holds no support permission.
"""
from .rbac import (  # noqa: F401  (re-exported for the views)
    ALL, ASSIGN, AVAILABILITY, CLOSE, EXCLUDE, INTENT, METRICS, NOTIFY_HEALTH, PRIORITY, READ,
    REOPEN, REPLY, REVEAL_CONTACT, ROLES, SPAM, TAKE, can, denial_code, scoped_threads)


def visible(admin, thread):
    """Whether ``thread`` is inside the person's read scope. Out-of-scope threads must
    look absent (404, no existence oracle)."""
    from . import rbac
    if rbac.mode() != 'enforce':
        return admin is not None and bool(admin.active)
    return rbac.strict_allows(admin, rbac.READ, thread)
