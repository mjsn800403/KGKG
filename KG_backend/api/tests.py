"""Behavioural tests for the browse API.

These exercise the ORM-backed endpoints and the health probe. Endpoints that
open a per-car SQLite warehouse DB (the model-level node tree) are not covered
here because that data is not present in CI — only the relational Car list is.
"""
import json

from django.test import TestCase
from django.urls import reverse

from .models import Car


class CarFixtureTests(TestCase):
    """The committed fixture is the source of truth for the Car list now that
    db.sqlite3 is no longer in git."""
    fixtures = ['cars.json']

    def test_fixture_loads_expected_cars(self):
        self.assertEqual(Car.objects.count(), 3)
        self.assertTrue(Car.objects.filter(brand_name='Toyota').exists())
        self.assertTrue(Car.objects.filter(car_name='NX 350h', brand_name='Lexus').exists())

    def test_car_table_name(self):
        # Model is mapped to the legacy table; guard against accidental change.
        self.assertEqual(Car._meta.db_table, 'main_db')


class HealthEndpointTests(TestCase):
    def test_healthz_ok(self):
        res = self.client.get('/healthz')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['status'], 'ok')


class BrandsListViewTests(TestCase):
    fixtures = ['cars.json']

    def test_returns_distinct_sorted_brands(self):
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        brands = res.json()
        # Two Toyota + one Lexus -> distinct, alphabetical.
        self.assertEqual(brands, ['Lexus', 'Toyota'])

    def test_empty_db_returns_empty_list(self):
        Car.objects.all().delete()
        res = self.client.get('/')
        self.assertEqual(res.json(), [])


class CarViewTests(TestCase):
    fixtures = ['cars.json']

    def test_brand_level_lists_that_brands_cars(self):
        res = self.client.get('/Toyota/')
        self.assertEqual(res.status_code, 200)
        cars = res.json()
        self.assertEqual(len(cars), 2)
        self.assertTrue(all(c['brand_name'] == 'Toyota' for c in cars))
        self.assertIn('db_address', cars[0])

    def test_brand_match_is_case_insensitive(self):
        res = self.client.get('/toYOta/')
        self.assertEqual(len(res.json()), 2)

    def test_unknown_brand_returns_empty_list(self):
        res = self.client.get('/Peugeot/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), [])

    def test_brand_and_year_filters_by_year(self):
        res = self.client.get('/Toyota/2025/')
        self.assertEqual(res.status_code, 200)
        cars = res.json()
        self.assertTrue(cars)
        self.assertTrue(all(c['year'] == 2025 for c in cars))

    def test_brand_and_wrong_year_is_empty(self):
        res = self.client.get('/Toyota/1990/')
        self.assertEqual(res.json(), [])
