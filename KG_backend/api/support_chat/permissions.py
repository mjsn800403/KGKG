"""The one place that decides what a signed-in staff member may do in support.

Today every signed-in platform admin PERSON may do everything here (the loopback
script token never may), which is the existing flat admin model. Role-based
permissions (docs/superpowers/specs/2026-11-03-phase3-architecture-reconciliation.md
section 2) replace the body of :func:`can` once the role table is approved; the
views already ask this function, so they do not change.
"""

READ = 'support.read'
REPLY = 'support.reply'
MANAGE = 'support.manage'
REVEAL_CONTACT = 'support.reveal_contact'

ALL = (READ, REPLY, MANAGE, REVEAL_CONTACT)


def can(admin, permission, thread=None):
    """True when ``admin`` (a PlatformAdmin, or None for a non-person) holds
    ``permission``, optionally for a specific thread's intent."""
    if permission not in ALL:
        raise ValueError(f'unknown permission {permission!r}')
    return admin is not None and bool(admin.active)
