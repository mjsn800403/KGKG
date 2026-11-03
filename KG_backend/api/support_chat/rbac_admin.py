"""Granting and revoking support roles: the rules, behind a store interface.

Used by ``manage.py support_roles grant|revoke``. A change is a DRY RUN unless
``apply`` is True, every applied change writes an id-only audit row (the role and the
person's id, never contact or message text), and the last support owner can never be
revoked: an owner only counts while the administrator is ACTIVE, and a bootstrap owner
from ``KG_SUPPORT_OWNERS`` counts only if that name matches an active administrator.

The store is an interface because the role table (migration B) does not exist yet.
``TableStore`` is the thin adapter over that table; until the migration is applied it
reports itself unavailable and every change is refused with ``table_missing``.
Design: docs/superpowers/specs/2026-11-03-phase3-migration-and-rbac-design.md.
"""
from typing import NamedTuple

from django.apps import apps
from django.db import transaction

from api.audit import audit
from api.models import AuditLog, PlatformAdmin

from . import rbac


class Result(NamedTuple):
    ok: bool
    changed: bool
    code: str
    message: str


class TableStore:
    """Adapter over ``SupportStaffRole`` (admin, role, granted_by_admin_id, granted_at)."""

    def _model(self):
        try:
            return apps.get_model('api', 'SupportStaffRole')
        except LookupError:
            return None

    def available(self):
        return self._model() is not None

    def roles(self, admin):
        return set(self._model().objects.filter(admin=admin).values_list('role', flat=True))

    def add(self, admin, role, granted_by):
        _, created = self._model().objects.get_or_create(
            admin=admin, role=role, defaults={'granted_by_admin_id': granted_by})
        return created

    def remove(self, admin, role):
        return self._model().objects.filter(admin=admin, role=role).delete()[0] > 0

    def owner_ids(self):
        """Ids of administrators holding support_owner in the table, locked so two
        simultaneous revocations cannot both pass the last-owner check."""
        rows = (self._model().objects.select_for_update()
                .filter(role=rbac.SUPPORT_OWNER).values_list('admin_id', flat=True))
        return set(rows)


def get_store():
    return TableStore()


def _find(username):
    return PlatformAdmin.objects.filter(username__iexact=(username or '').strip()).first()


def _active_owner_ids_after(store, removing):
    """Ids of ACTIVE administrators who would still be support owners if ``removing``
    (an admin id or None) lost the table role."""
    ids = {i for i in store.owner_ids() if i != removing}
    for admin in PlatformAdmin.objects.filter(active=True):
        if admin.username.lower() in rbac.bootstrap_owner_names():
            ids.add(admin.id)
    return {a.id for a in PlatformAdmin.objects.filter(pk__in=ids, active=True)}


def _audit(action, admin, role):
    audit(action, actor_type=AuditLog.SYSTEM, actor_label='support_roles command',
          target_type='platform_admin', target_id=str(admin.id), detail={'role': role})


def _refuse(code, message):
    return Result(False, False, code, message)


def _check(store, username, role, *, allow_inactive):
    """(admin, None) or (None, Result) for the validation shared by grant and revoke."""
    if role not in rbac.ROLE_NAMES:
        return None, _refuse('unknown_role', f'unknown role {role!r}; one of: {", ".join(rbac.ROLE_NAMES)}')
    admin = _find(username)
    if admin is None:
        return None, _refuse('unknown_admin', f'{username!r} matches no administrator')
    if not admin.active and not allow_inactive:
        return None, _refuse('inactive_admin', f'{admin.username!r} is deactivated; a role would do nothing')
    if not store.available():
        return None, _refuse('table_missing', 'the role table does not exist yet (migration B is not applied)')
    return admin, None


def grant(store, username, role, *, apply=False):
    admin, refused = _check(store, username, role, allow_inactive=False)
    if refused:
        return refused
    with transaction.atomic():
        if role in store.roles(admin):
            return Result(True, False, 'already_held', f'{admin.username} already holds {role}')
        if not apply:
            return Result(True, False, 'would_grant', f'would grant {role} to {admin.username}')
        store.add(admin, role, None)             # granted by the operator, not a person
        _audit('support_chat.role_granted', admin, role)
    return Result(True, True, 'granted', f'granted {role} to {admin.username}')


def revoke(store, username, role, *, apply=False):
    admin, refused = _check(store, username, role, allow_inactive=True)
    if refused:
        return refused
    with transaction.atomic():
        if role not in store.roles(admin):
            return Result(True, False, 'not_held', f'{admin.username} does not hold {role} (not held)')
        if role == rbac.SUPPORT_OWNER and not _active_owner_ids_after(store, admin.id):
            return _refuse('last_owner',
                           f'{admin.username} is the last active support owner; add another owner '
                           '(or a valid KG_SUPPORT_OWNERS name) first')
        if not apply:
            return Result(True, False, 'would_revoke', f'would revoke {role} from {admin.username}')
        store.remove(admin, role)
        _audit('support_chat.role_revoked', admin, role)
    return Result(True, True, 'revoked', f'revoked {role} from {admin.username}')
