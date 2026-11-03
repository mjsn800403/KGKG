"""Role-based access for the support chat: the matrix, the three rollout modes,
bootstrap owners and query scope. Design: docs/superpowers/specs/
2026-11-03-phase3-migration-and-rbac-design.md (sections 3.1-3.3).

Rollout mode (``KG_SUPPORT_RBAC``, default and fallback ``off``):

* ``off``     today's behaviour: every signed-in platform admin PERSON may do
              everything in support. Nothing changes until a person sets another mode.
* ``audit``   same access, but each request that enforcement WOULD have denied
              writes an id-only audit row, so mappings can be proven first.
* ``enforce`` default deny. No implicit allow, no degraded mode, no fallback to
              ``audit``. If no active owner can be resolved, support endpoints answer
              403 ``rbac_no_owner`` (this can lock out support, never any other admin
              feature); recovery is explicit: fix ``KG_SUPPORT_OWNERS``, run the
              ``support_roles`` command on the server, or set ``KG_SUPPORT_RBAC=off``.

The loopback ``KG_ADMIN_TOKEN`` is never a person and holds no support permission in
any mode. Only support code asks this module; no other admin feature reads it.

Roles come from ``KG_SUPPORT_OWNERS`` (bootstrap owners, matched case-insensitively
against ACTIVE admins at call time) and, once migration B exists, the
``SupportStaffRole`` table. Until then the table contributes nothing.
"""
import os
import re

from django.apps import apps
from django.db.models import Q

# --- permissions -----------------------------------------------------------
READ = 'support.read'
REPLY = 'support.reply'
TAKE = 'support.take'                      # assign a thread to yourself
ASSIGN = 'support.assign'                  # assign to others / unassign others
PRIORITY = 'support.priority'
INTENT = 'support.intent'
CLOSE = 'support.close'
REOPEN = 'support.reopen'
SPAM = 'support.spam'                      # spam and restore
REVEAL_CONTACT = 'support.reveal_contact'
EXCLUDE = 'support.exclude'                # QA marker (needs the excluded column: migration A)
METRICS = 'support.metrics'
NOTIFY_HEALTH = 'support.notify_health'
AVAILABILITY = 'support.availability'      # declare yourself available / count toward live
ROLES = 'support.roles'

ALL = (READ, REPLY, TAKE, ASSIGN, PRIORITY, INTENT, CLOSE, REOPEN, SPAM, REVEAL_CONTACT,
       EXCLUDE, METRICS, NOTIFY_HEALTH, AVAILABILITY, ROLES)

ALL_INTENTS = ('sales', 'demo', 'technical', 'other')

# --- scopes ----------------------------------------------------------------
EVERYTHING = 'all'
OWN = 'own'                                # threads assigned to the person
OWN_OR_UNASSIGNED = 'own_or_unassigned'

# --- roles -----------------------------------------------------------------
SUPPORT_AGENT, SALES_AGENT = 'support_agent', 'sales_agent'
SUPPORT_LEAD, SUPPORT_AUDITOR, SUPPORT_OWNER = 'support_lead', 'support_auditor', 'support_owner'
ROLE_NAMES = (SUPPORT_AGENT, SALES_AGENT, SUPPORT_LEAD, SUPPORT_AUDITOR, SUPPORT_OWNER)

ROLE_INTENTS = {
    SUPPORT_AGENT: ('technical', 'other'),
    SALES_AGENT: ('sales', 'demo'),
    SUPPORT_LEAD: ALL_INTENTS,
    SUPPORT_AUDITOR: ALL_INTENTS,
    SUPPORT_OWNER: ALL_INTENTS,
}

_AGENT = {READ: OWN_OR_UNASSIGNED, REPLY: OWN_OR_UNASSIGNED, TAKE: OWN_OR_UNASSIGNED,
          PRIORITY: OWN, INTENT: OWN, CLOSE: OWN, REOPEN: OWN, REVEAL_CONTACT: OWN,
          AVAILABILITY: EVERYTHING}
_LEAD = {p: EVERYTHING for p in (READ, REPLY, TAKE, ASSIGN, PRIORITY, INTENT, CLOSE, REOPEN, SPAM,
                                 REVEAL_CONTACT, EXCLUDE, METRICS, NOTIFY_HEALTH, AVAILABILITY)}

MATRIX = {
    SUPPORT_AGENT: _AGENT,
    SALES_AGENT: _AGENT,
    SUPPORT_LEAD: _LEAD,
    SUPPORT_AUDITOR: {READ: EVERYTHING, METRICS: EVERYTHING, NOTIFY_HEALTH: EVERYTHING},
    SUPPORT_OWNER: {**_LEAD, ROLES: EVERYTHING},
}

MODES = ('off', 'audit', 'enforce')


# --- mode and bootstrap owners ----------------------------------------------
def raw_mode():
    return os.environ.get('KG_SUPPORT_RBAC', '').strip().lower()


def mode():
    """The rollout mode. An unrecognised value is ``off``, never ``enforce``."""
    value = raw_mode()
    return value if value in MODES else 'off'


def bootstrap_owner_names():
    """Lower-cased usernames from KG_SUPPORT_OWNERS (commas, semicolons or spaces)."""
    raw = os.environ.get('KG_SUPPORT_OWNERS', '')
    return {n.lower() for n in re.split(r'[,;\s]+', raw) if n}


# --- roles ------------------------------------------------------------------
def _table_roles(admin):
    """Role names stored for ``admin``; empty while migration B does not exist."""
    try:
        model = apps.get_model('api', 'SupportStaffRole')
    except LookupError:
        return set()
    return set(model.objects.filter(admin=admin).values_list('role', flat=True))


def table_available():
    """Whether the role table exists (migration B). Until it does, only the
    bootstrap owners from the environment hold any role."""
    try:
        apps.get_model('api', 'SupportStaffRole')
    except LookupError:
        return False
    return True


def roles_for(admin):
    """Known role names held by ``admin`` (unknown names in the table are ignored)."""
    if admin is None:
        return set()
    roles = set(_table_roles(admin))
    if admin.username.lower() in bootstrap_owner_names():
        roles.add(SUPPORT_OWNER)
    return roles & set(ROLE_NAMES)


def active_owner_exists():
    """True when at least one ACTIVE admin resolves as a support owner."""
    from api.models import PlatformAdmin
    # Same code path as every decision (roles_for), over the few active admins, so
    # "an owner exists" can never disagree with "this person is an owner".
    return any(SUPPORT_OWNER in roles_for(a) for a in PlatformAdmin.objects.filter(active=True))


def denial_code():
    """The error code to send with a 403."""
    return 'rbac_no_owner' if mode() == 'enforce' and not active_owner_exists() else 'forbidden'


# --- decisions --------------------------------------------------------------
def _within(level, admin, thread):
    if level == EVERYTHING:
        return True
    mine = thread.assignee_id == admin.id
    if level == OWN:
        return mine
    return mine or thread.assignee_id is None            # OWN_OR_UNASSIGNED


def strict_allows(admin, permission, thread=None):
    """The enforcement answer, ignoring the mode. ``thread=None`` asks only whether
    any of the person's roles holds the permission."""
    if admin is None or not admin.active:
        return False
    for role in roles_for(admin):
        level = MATRIX[role].get(permission)
        if level is None:
            continue
        if thread is None:
            return True
        if thread.intent in ROLE_INTENTS[role] and _within(level, admin, thread):
            return True
    return False


def _record_would_deny(admin, permission, thread):
    from api.audit import audit
    from api.models import AuditLog
    audit('support_chat.rbac_would_deny', actor_type=AuditLog.ADMIN, actor_id=admin.id,
          actor_label=admin.username, target_type='support_thread' if thread else '',
          target_id=str(thread.pk) if thread else '',
          detail={'permission': permission, **({'intent': thread.intent} if thread else {})})


def can(admin, permission, thread=None):
    if permission not in ALL:
        raise ValueError(f'unknown permission {permission!r}')
    if admin is None or not admin.active:
        return False                                     # the loopback token is never a person
    current = mode()
    if current == 'off':
        return True
    if strict_allows(admin, permission, thread):
        return True
    if current == 'audit':
        _record_would_deny(admin, permission, thread)
        return True
    return False


def allows(admin, permission, thread=None):
    """Like :func:`can` but side-effect free: records nothing in ``audit``. For
    telling the UI what to offer; the real check still happens on every request."""
    if admin is None or not admin.active:
        return False
    return True if mode() != 'enforce' else strict_allows(admin, permission, thread)


def scoped_threads(admin, queryset):
    """Backend query scope: in ``enforce``, only the threads the person may read.
    ``off`` and ``audit`` do not narrow anything."""
    if admin is None or not admin.active:
        return queryset.none()
    if mode() != 'enforce':
        return queryset
    scope = Q(pk__in=[])
    for role in roles_for(admin):
        level = MATRIX[role].get(READ)
        if level is None:
            continue
        part = Q(intent__in=ROLE_INTENTS[role])
        if level == OWN:
            part &= Q(assignee=admin)
        elif level == OWN_OR_UNASSIGNED:
            part &= Q(assignee__isnull=True) | Q(assignee=admin)
        scope |= part
    return queryset.filter(scope)


def event_intents(admin):
    """Intents whose ``support_chat.*`` events this person's stream may carry, or
    ``None`` when events are not narrowed (``off`` and ``audit``). A person with no
    read role, and the loopback token, get an empty set."""
    if mode() != 'enforce':
        return None
    intents = set()
    for role in roles_for(admin):
        if READ in MATRIX[role]:
            intents |= set(ROLE_INTENTS[role])
    return frozenset(intents)


def can_reply_intent(admin, intent):
    """Whether ``admin`` counts toward live availability for ``intent`` (or for any
    intent when ``intent`` is None). Only ``enforce`` consults roles."""
    if admin is None or not admin.active:
        return False
    if mode() != 'enforce':
        return True
    for role in roles_for(admin):
        grants = MATRIX[role]
        if REPLY in grants and AVAILABILITY in grants and (intent is None or intent in ROLE_INTENTS[role]):
            return True
    return False
