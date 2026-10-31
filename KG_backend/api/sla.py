"""Service-level targets for the support desk.

The desk had no clock at all before this module: `CompanyRequest.resolved_at`
recorded *when* a ticket closed but nothing said when it was *supposed* to, so
SLA compliance was undefined and therefore unmeasurable (see
audit-evidence/16-improvement-programme/ROOT_CAUSE_ANALYSIS.md, Finding 4).

Two targets per priority:

  * **response** — the first public reply from the platform side. Internal
    notes do not count; the customer cannot see them.
  * **resolution** — the ticket reaching a closed status. Reopening restarts
    this clock (the response clock is not restarted: it has already happened).

The targets are **calendar** hours, not business hours. That is a deliberate
simplification and it is stated rather than hidden: a working-calendar
implementation needs an agreed timetable and holiday list, which the
organisation has not defined. Calendar hours make every figure reproducible
from two timestamps and never flatter the result.
"""
from datetime import timedelta

#: priority -> (first response target, resolution target)
POLICY = {
    'high':   (timedelta(hours=2),  timedelta(hours=8)),
    'normal': (timedelta(hours=8),  timedelta(hours=48)),
    'low':    (timedelta(hours=24), timedelta(hours=120)),
}

DEFAULT_PRIORITY = 'normal'


def targets(priority):
    """(response, resolution) targets; an unknown priority falls back to normal."""
    return POLICY.get(priority, POLICY[DEFAULT_PRIORITY])


def due_dates(priority, start):
    """(response_due_at, resolve_due_at) for a ticket whose clock starts at ``start``."""
    response, resolution = targets(priority)
    return start + response, start + resolution


def state(due_at, happened_at, now):
    """One of 'met', 'breached', 'pending' — or None when no target is set.

    ``happened_at`` is the event the target is about (first response, or
    resolution). Nothing having happened yet is only a breach once the due
    date has passed.
    """
    if due_at is None:
        return None
    if happened_at is not None:
        return 'met' if happened_at <= due_at else 'breached'
    return 'breached' if now > due_at else 'pending'
