"""Payloads behind the shared vehicle filter.

The filter itself is client-side (kg_frontend/src/components/VehicleFilter.jsx),
but it can only facet on what the API sends: brand/model/year apart from any
joined label, and — for the admin catalogue — the per-vehicle health indicators
the super-admin filters and sorts the fleet by.
"""
import json

from django.test import TestCase, Client
from django.utils import timezone

from .dataquality import latest_health_by_car
from .models import (
    AdminAuthToken, AuthToken, Car, Company, CompanyCarAccess, DataQualityRun,
    PlatformAdmin, PortalUser, VehicleSpec,
)
from . import orggraph as og


def _admin_headers():
    admin = PlatformAdmin.objects.create(username='boss')
    admin.set_password('pw')
    admin.save()
    return {'HTTP_AUTHORIZATION': f'Bearer {AdminAuthToken.issue(admin).key}'}


class AdminCatalogPayloadTests(TestCase):
    def setUp(self):
        self.c = Client()
        self.headers = _admin_headers()
        self.car = Car.objects.create(brand_name='Toyota', car_name='RAV4 Hybrid SE',
                                      year=2025, db_address='rav4.db')
        self.other = Car.objects.create(brand_name='Lexus', car_name='NX 350h',
                                        year=2024, db_address='nx.db')

    def _cars(self):
        r = self.c.get('/api/admin/cars/', **self.headers)
        self.assertEqual(r.status_code, 200)
        return r.json()

    def test_catalog_is_gated(self):
        self.assertEqual(Client().get('/api/admin/cars/').status_code, 401)

    def test_rows_carry_the_facet_fields(self):
        """brand / model / year must arrive as separate fields — the filter
        facets on them and cannot take them apart from a joined string."""
        body = self._cars()
        row = next(x for x in body['items'] if x['id'] == self.car.id)
        self.assertEqual(row['brand'], 'Toyota')
        self.assertEqual(row['model'], 'RAV4 Hybrid SE')
        self.assertEqual(row['year'], 2025)

    def test_health_is_null_before_any_audit(self):
        body = self._cars()
        self.assertIsNone(body['audited_at'])
        self.assertTrue(all(x['health'] is None for x in body['items']))
        self.assertEqual(latest_health_by_car(), ({}, None))

    def test_health_joins_the_latest_finished_audit(self):
        DataQualityRun.objects.create(
            status='done', finished_at=timezone.now(),
            summary={}, vehicles=[{
                'stem': 'RAV4 Hybrid SE', 'car_id': self.car.id, 'status': 'incomplete',
                'sections': [{'normalized': 'a'}, {'normalized': 'b'}, {'normalized': 'c'}],
                'missing_sections': ['d'], 'empty_sections': ['c'],
                'rag_indexed': True, 'diag_indexed': False, 'static_assets': True,
                'size_mb': 410.5, 'integrity': 'ok', 'is_duplicate': False,
                'pending_processes': ['diag_build'],
            }])

        body = self._cars()
        self.assertIsNotNone(body['audited_at'])
        row = next(x for x in body['items'] if x['id'] == self.car.id)
        h = row['health']
        self.assertEqual(h['status'], 'incomplete')
        # 3 sections present, 1 of them empty, 1 required section missing:
        # 2 filled of 4 required = 50%.
        self.assertEqual(h['completeness'], 50)
        self.assertEqual(h['missing_sections'], 1)
        self.assertEqual(h['empty_sections'], 1)
        self.assertTrue(h['rag_indexed'])
        self.assertFalse(h['diag_indexed'])
        self.assertEqual(h['pending_processes'], ['diag_build'])
        # A car the audit never saw stays null rather than looking healthy.
        self.assertIsNone(next(x for x in body['items'] if x['id'] == self.other.id)['health'])

    def test_running_or_failed_audits_are_ignored(self):
        DataQualityRun.objects.create(
            status='done', finished_at=timezone.now(),
            vehicles=[{'stem': 'x', 'car_id': self.car.id, 'status': 'complete',
                       'sections': [{'normalized': 'a'}]}])
        DataQualityRun.objects.create(
            status='failed', finished_at=timezone.now(),
            vehicles=[{'stem': 'x', 'car_id': self.car.id, 'status': 'corrupt',
                       'sections': []}])
        health, _ = latest_health_by_car()
        self.assertEqual(health[self.car.id]['status'], 'complete')

    def test_audit_rows_without_a_catalog_row_are_skipped(self):
        DataQualityRun.objects.create(
            status='done', finished_at=timezone.now(),
            vehicles=[{'stem': 'orphan', 'car_id': None, 'status': 'incomplete',
                       'sections': []}])
        health, _ = latest_health_by_car()
        self.assertEqual(health, {})

    def test_spec_presence_and_field_count(self):
        VehicleSpec.objects.create(
            car=self.car, data={'@type': 'Car', 'name': 'RAV4', 'modelDate': '2025'})
        body = self._cars()
        row = next(x for x in body['items'] if x['id'] == self.car.id)
        self.assertTrue(row['has_spec'])
        self.assertEqual(row['spec_fields'], 2)      # @-keys are not fields
        self.assertFalse(next(x for x in body['items'] if x['id'] == self.other.id)['has_spec'])


class OrgGraphCarPayloadTests(TestCase):
    """The seat access panel filters the company's cars, so the graph document
    has to ship the parts, not only the pre-joined label."""

    def setUp(self):
        self.c = Client()
        self.company = Company.objects.create(name='Acme', seats_count=3, active=True)
        self.car = Car.objects.create(brand_name='Toyota', car_name='Corolla Cross Hybrid S',
                                      year=2025, db_address='cc.db')
        CompanyCarAccess.objects.create(company=self.company, car=self.car,
                                        documents=['manual'])
        self.root = PortalUser.objects.create(
            company=self.company, username='root', role='after_sales_manager',
            password_hash='x', active=True)
        og.seed_graph_for_company(self.company)
        og.reassign_root(self.company, self.root)

    def test_company_cars_expose_model_and_year(self):
        tok = AuthToken.issue(self.root)
        r = self.c.get('/api/org/graph/', HTTP_AUTHORIZATION=f'Bearer {tok.key}')
        self.assertEqual(r.status_code, 200)
        row = r.json()['company_cars'][0]
        self.assertEqual(row['brand'], 'Toyota')
        self.assertEqual(row['model'], 'Corolla Cross Hybrid S')
        self.assertEqual(row['year'], 2025)
        # the joined label stays, existing UI still renders it
        self.assertEqual(row['label'], 'Toyota Corolla Cross Hybrid S 2025')
