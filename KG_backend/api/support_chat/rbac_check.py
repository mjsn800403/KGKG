"""Read-only readiness checks behind ``manage.py support_roles check``.

Nothing here writes, sends or changes a setting. It answers one question: would
switching ``KG_SUPPORT_RBAC`` to ``enforce`` now lock support out? Findings are
``block`` (must be fixed before enforcing), ``warn`` (worth knowing) or ``info``.
Design: docs/superpowers/specs/2026-11-03-phase3-migration-and-rbac-design.md 3.3.
"""
from collections import Counter
from datetime import timedelta
from typing import NamedTuple

from django.utils import timezone

from api.models import AdminAuthToken, AuditLog, PlatformAdmin

from . import rbac

WOULD_DENY_WINDOW_DAYS = 14


class Finding(NamedTuple):
    level: str        # 'block' | 'warn' | 'info'
    code: str
    message: str


def run():
    """Every finding, in a stable order."""
    out = []
    out += _mode()
    out += _owners()
    out += _table()
    out += _coverage()
    out += _would_deny()
    return out


def blocking(findings):
    return [f for f in findings if f.level == 'block']


def _mode():
    raw = rbac.raw_mode()
    if raw and raw not in rbac.MODES:
        return [Finding('block', 'mode_unrecognised',
                        f'KG_SUPPORT_RBAC={raw!r} is not one of off|audit|enforce; it is treated as off, '
                        'never as enforce')]
    return [Finding('info', 'mode', f'KG_SUPPORT_RBAC is {rbac.mode()}'
                    + (' (unset: the default)' if not raw else ''))]


def _owners():
    out = []
    names = sorted(rbac.bootstrap_owner_names())
    for name in names:
        admin = PlatformAdmin.objects.filter(username__iexact=name).first()
        if admin is None:
            out.append(Finding('block', 'owner_name_unknown',
                               f'KG_SUPPORT_OWNERS names {name!r}, which matches no administrator '
                               '(a misspelling is the usual lockout cause)'))
        elif not admin.active:
            out.append(Finding('warn', 'owner_inactive',
                               f'bootstrap owner {admin.username!r} is deactivated and holds no access'))
    if not names:
        out.append(Finding('info', 'owners_env', 'KG_SUPPORT_OWNERS is empty'))
    if rbac.active_owner_exists():
        out.append(Finding('info', 'owner_present', 'at least one active support owner resolves'))
    else:
        out.append(Finding('block', 'no_active_owner',
                           'no ACTIVE administrator resolves as a support owner; in enforce, support '
                           'would answer 403 rbac_no_owner until one is configured'))
    return out


def _table():
    if rbac.table_available():
        return [Finding('info', 'role_table', 'the role table exists')]
    return [Finding('block', 'role_table_missing',
                    'the role table does not exist (migration B is not applied): only bootstrap owners '
                    'would have any access in enforce')]


def _coverage():
    out = []
    admins = list(PlatformAdmin.objects.filter(active=True))
    held = {a.username: rbac.roles_for(a) for a in admins}
    everyone = set().union(*held.values()) if held else set()
    for role, label in ((rbac.SALES_AGENT, 'sales'), (rbac.SUPPORT_AGENT, 'technical/other')):
        if role not in everyone:
            out.append(Finding('warn', f'no_{role}',
                               f'no active administrator holds {role}: {label} conversations would '
                               'never make the widget live for that intent'))
    without = sorted(u for u, r in held.items() if not r)
    if without:
        out.append(Finding('warn', 'admins_without_role',
                           f'{len(without)} active administrator(s) hold no support role and would be '
                           f'denied in enforce: {", ".join(without)}'))
    return out


def _would_deny():
    since = timezone.now() - timedelta(days=WOULD_DENY_WINDOW_DAYS)
    rows = AuditLog.objects.filter(action='support_chat.rbac_would_deny', created_at__gte=since)
    counts = Counter((r.actor_id, (r.detail or {}).get('permission', '?')) for r in rows)
    if not counts:
        return [Finding('info', 'would_deny', f'no would-be denials recorded in the last '
                                              f'{WOULD_DENY_WINDOW_DAYS} days')]
    out = [Finding('warn', 'would_deny', f'{sum(counts.values())} request(s) in the last '
                                         f'{WOULD_DENY_WINDOW_DAYS} days would be denied in enforce')]
    for (actor, perm), n in counts.most_common(10):
        out.append(Finding('info', 'would_deny_detail', f'  admin id {actor}: {perm} x{n}'))
    return out


def report_rows():
    """One dict per administrator: no secrets, no message content."""
    last_use = {}
    for admin_id, when in AdminAuthToken.objects.values_list('admin_id', 'last_used_at'):
        if when and (admin_id not in last_use or when > last_use[admin_id]):
            last_use[admin_id] = when
    activity = Counter(AuditLog.objects.filter(actor_type=AuditLog.ADMIN, action__startswith='support_chat.')
                       .exclude(action='support_chat.rbac_would_deny')
                       .values_list('actor_id', flat=True))
    owners = rbac.bootstrap_owner_names()
    rows = []
    for a in PlatformAdmin.objects.order_by('username'):
        table = rbac._table_roles(a) & set(rbac.ROLE_NAMES)
        rows.append({
            'id': a.id, 'username': a.username, 'active': a.active,
            'env_owner': a.username.lower() in owners, 'table_roles': sorted(table),
            'last_token_use': last_use[a.id].isoformat() if a.id in last_use else None,
            'phone_on_file': bool(a.phone), 'support_actions': activity.get(a.id, 0),
        })
    return rows
