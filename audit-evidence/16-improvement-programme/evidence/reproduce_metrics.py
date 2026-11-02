"""Build a throwaway database, exercise the service desk through real HTTP, and
print what GET /api/admin/support/metrics/ answers.

This exists so that the numbers quoted in IMPLEMENTATION_PHASE1.md can be
reproduced by anyone, from a clean database, without touching production.

    cd KG_backend
    DJANGO_SECRET_KEY=x python ../audit-evidence/16-improvement-programme/evidence/reproduce_metrics.py

It creates and destroys its own test database (sqlite, in a temp file) and
writes nothing anywhere else.
"""
import json
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'KG_backend.settings')
os.environ.setdefault('DJANGO_SECRET_KEY', 'reproduce-only')
os.environ.setdefault('KG_ADMIN_TOKEN', 'reproduce-only')

import django                                                   # noqa: E402

django.setup()

from django.test.runner import DiscoverRunner                   # noqa: E402
from django.test.utils import setup_test_environment            # noqa: E402

setup_test_environment()
runner = DiscoverRunner(verbosity=0, interactive=False)
old_config = runner.setup_databases()

from django.test import Client                                  # noqa: E402
from django.utils import timezone                               # noqa: E402

from api.models import (AdminAuthToken, AuthToken, Company, CompanyRequest,
                        PlatformAdmin, PortalUser)              # noqa: E402

try:
    c = Client()
    co = Company.objects.create(name='Reproduce Co')
    mgr = PortalUser.objects.create(company=co, username='repro_mgr',
                                    role='after_sales_manager', can_manage_team=True)
    spec = PortalUser.objects.create(company=co, username='repro_spec',
                                     role='after_sales_specialist')
    admin = PlatformAdmin.objects.create(username='repro_admin', password_hash='x')
    h_spec = {'HTTP_AUTHORIZATION': f'Bearer {AuthToken.issue(spec).key}'}
    h_mgr = {'HTTP_AUTHORIZATION': f'Bearer {AuthToken.issue(mgr).key}'}
    h_admin = {'HTTP_AUTHORIZATION': f'Bearer {AdminAuthToken.issue(admin).key}'}

    def post(url, body, hdr):
        return c.post(url, json.dumps(body), content_type='application/json', **hdr)

    # 1. a specialist files a support ticket — the thing that was a 403 before
    t1 = post('/api/company/requests/',
              {'kind': 'support', 'subject': 'Brake chapter will not open',
               'body': 'It returns an empty page on the 2020 Hilux.'},
              h_spec).json()['request']
    # 2. the platform side replies (stamps first_response_at), then resolves it
    post(f"/api/admin/company-requests/{t1['id']}/",
         {'message': 'Reproduced; a fix ships today.', 'assignee_id': admin.id}, h_admin)
    post(f"/api/admin/company-requests/{t1['id']}/", {'status': 'completed'}, h_admin)
    # 3. the filer rates it
    post(f"/api/company/requests/{t1['id']}/", {'csat': {'score': 5, 'comment': 'quick'}},
         h_spec)

    # 4. a second ticket, answered late: backdate the target so the breach is real
    t2 = post('/api/company/requests/', {'kind': 'support', 'subject': 'Slow search'},
              h_spec).json()['request']
    CompanyRequest.objects.filter(id=t2['id']).update(
        sla_response_due_at=timezone.now() - timedelta(hours=3))

    # 5. a telephone call, logged by the admin so the channel is measurable
    post('/api/admin/company-requests/',
         {'company_id': co.id, 'subject': 'Rang about seat count',
          'body': 'Wants two more seats.', 'source': 'phone'}, h_admin)

    # 6. product feedback from a seat
    post('/api/feedback/submit/', {'page': '/browse', 'rating': 4,
                                   'comment': 'search is slow on long manuals'}, h_mgr)

    # 7. the resolved ticket becomes a draft article, then is published
    art = post(f"/api/admin/company-requests/{t1['id']}/promote-to-article/",
               {'slug': 'brake-chapter-empty', 'category': 'manuals'},
               h_admin).json()['article']
    post(f"/api/admin/kb/{art['id']}/", {'status': 'published'}, h_admin)
    # 8. two knowledge searches: one hit, one miss
    c.get('/api/kb/?q=brake', **h_spec)
    c.get('/api/kb/?q=gearbox oil capacity', **h_spec)

    out = c.get('/api/admin/support/metrics/?days=30', **h_admin).json()
    out.pop('generated_at', None)        # so two runs diff cleanly
    print(json.dumps(out, indent=2, ensure_ascii=False))
finally:
    runner.teardown_databases(old_config)
