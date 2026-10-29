"""Create the deterministic accounts the E2E, load and DAST suites sign in with.

Runs only inside the isolated QA stack (qa/stack.sh): that stack serves a
sanitized copy of the production database in which no real account can log
in. This command adds a small, clearly named set of test accounts to that copy:

  qa_e2e_manager     company "QA-E2E-A", manager, AI on, one car granted
  qa_e2e_specialist  company "QA-E2E-A", specialist, no car granted
  qa_e2e_locked      company "QA-E2E-A", locked account
  qa_e2e_other       company "QA-E2E-B", manager (cross-tenant probes)

None has a phone, so they sign in with password only (no SMS). The password
comes from KG_QA_PASSWORD, which qa/stack.sh generates per run. Password login
still needs a Cloudflare Turnstile pass, which automation cannot (and must not)
produce, so the command also prints one session token per account (and a spare
for the logout journey); qa/stack.sh stores them mode 600 for the suites.

Three independent guards keep it off production: KG_QA_STACK=1 must be set,
the data directory must hold the `.qa-stack` marker that only qa/stack.sh
writes, and on PostgreSQL the database itself must be a QA copy (its name ends
in `_qa`). The last one matters because the QA backend reads production's
.env.prod: a marker in the QA directory says nothing about which database the
connection actually reaches.
"""
import json
import os
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.core.management.base import BaseCommand, CommandError

from api.access import VALID_DOCS
from api.models import AuthToken, Car, Company, CompanyCarAccess, PortalUser, UserCarAccess

CAR = ('Toyota', 2025, 'Corolla Cross Hybrid S')
MARKER = '.qa-stack'


def db_dir():
    return Path(settings.KG_DATA_DIR)


def db_target():
    """(engine, database name) of the connection the command would write to."""
    engine = 'postgres' if connection.vendor == 'postgresql' else connection.vendor
    return engine, str(connection.settings_dict.get('NAME') or '')


def qa_guard():
    db_dir_ = db_dir()
    if os.environ.get('KG_QA_STACK') != '1':
        raise CommandError('refusing: KG_QA_STACK=1 is not set (QA stack only)')
    if not (db_dir_ / MARKER).is_file():
        raise CommandError(f'refusing: {db_dir_}/{MARKER} is missing (not a QA stack database)')
    engine, name = db_target()
    if engine == 'postgres' and not name.endswith('_qa'):
        raise CommandError(f'refusing: database {name!r} is not a QA copy (name must end in _qa)')
    password = os.environ.get('KG_QA_PASSWORD', '')
    if len(password) < 16:
        raise CommandError('KG_QA_PASSWORD must be set (16+ characters)')
    return password


class Command(BaseCommand):
    help = 'Seed E2E/load/DAST test accounts into the QA stack database (never production).'

    def handle(self, *args, **opts):
        password = qa_guard()
        car = (Car.objects.filter(brand_name__iexact=CAR[0], year=CAR[1],
                                  car_name__iexact=CAR[2]).first())
        if car is None:
            raise CommandError(f'car {CAR} not in the catalog copy')
        docs = sorted(VALID_DOCS)
        a, _ = Company.objects.update_or_create(
            name='QA-E2E-A', defaults={'active': True, 'ai_assistant_enabled': True,
                                       'seats_count': 10, 'note': 'qa/stack.sh fixture'})
        b, _ = Company.objects.update_or_create(
            name='QA-E2E-B', defaults={'active': True, 'seats_count': 2,
                                       'note': 'qa/stack.sh fixture'})
        CompanyCarAccess.objects.update_or_create(company=a, car=car, defaults={'documents': docs})

        def user(username, company, role, **extra):
            u = PortalUser.objects.filter(username=username).first() or PortalUser(username=username)
            u.company, u.role, u.phone, u.otp_enabled = company, role, '', False
            u.display_name, u.active, u.locked = f'QA {username}', True, False
            u.password_set, u.invite_status, u.access_expires_at = True, 'active', None
            for k, v in extra.items():
                setattr(u, k, v)
            u.set_password(password)
            u.save()
            return u

        accounts = {}
        mgr = accounts['manager'] = user('qa_e2e_manager', a, 'after_sales_manager', can_manage_team=True,
                   can_view_analytics=True, ai_assistant_enabled=True)
        accounts['specialist'] = user('qa_e2e_specialist', a, 'after_sales_specialist', reports_to=mgr)
        user('qa_e2e_locked', a, 'after_sales_specialist', locked=True)
        accounts['other'] = user('qa_e2e_other', b, 'after_sales_manager', can_manage_team=True)
        UserCarAccess.objects.update_or_create(
            user=mgr, car=car, defaults={'documents': docs, 'admin_granted': True})
        tokens = {k: AuthToken.issue(u).key for k, u in accounts.items()}
        tokens['manager_logout'] = AuthToken.issue(mgr).key
        self.stdout.write(json.dumps({
            'tokens': tokens,
            'companies': ['QA-E2E-A', 'QA-E2E-B'],
            'users': ['qa_e2e_manager', 'qa_e2e_specialist', 'qa_e2e_locked', 'qa_e2e_other'],
            'car': {'brand': car.brand_name, 'year': car.year, 'model': car.car_name},
        }))
