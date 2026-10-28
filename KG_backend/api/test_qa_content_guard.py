"""The per-car content gate cannot be sidestepped with a mismatched brand.

Found on the QA stack after the ZAP API scan: /api/diagnose/ with
car=<a vehicle the user is not entitled to> and brand=<anything else>
returned that vehicle's diagnostic results and manual links (200), while the
same request with the right brand was refused (403). The gate looked the car
up by name AND brand; no match meant no access check, but the car name still
selected the vehicle's data. The same gate fronts assist and search.
"""
import json

from django.test import Client, TestCase

from . import test_qa_catalog as catalog
from .test_qa_catalog import CAMRY, QAUsersMixin


# The catalog suite's module fixtures: temp warehouse, throttles off.
def setUpModule():
    catalog.setUpModule()


def tearDownModule():
    catalog.tearDownModule()


class BrandMismatchGateTests(QAUsersMixin, TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.make_world()

    def setUp(self):
        self.make_rows()
        self.c = Client()

    def _all(self, user, car, brand):
        h = self.auth(user)
        q = {'q': 'P0300', 'car': car, 'brand': brand}
        yield 'diagnose GET', self.c.get('/api/diagnose/', q, **h)
        yield 'diagnose POST', self.c.post('/api/diagnose/', json.dumps(
            {'query': 'P0300', 'car': car, 'brand': brand}), content_type='application/json', **h)
        yield 'assist POST', self.c.post('/api/assist/', json.dumps(
            {'query': 'oil', 'car': car, 'brand': brand}), content_type='application/json', **h)
        yield 'search GET', self.c.get('/api/search/', {'q': 'oil', 'car': car, 'brand': brand}, **h)

    def test_ungranted_car_is_refused_whatever_the_brand(self):
        # bob may open Supra only; Camry belongs to company A.
        for brand in ('Toyota', 'Nope', 'toyota', ''):
            for name, r in self._all(self.bob, CAMRY, brand):
                self.assertEqual(r.status_code, 403, (name, brand, r.content[:200]))

    def test_granted_car_still_works_with_a_wrong_brand(self):
        for name, r in self._all(self.alice, CAMRY, 'Nope'):
            self.assertNotIn(r.status_code, (401, 403), (name, r.content[:200]))

    def test_path_like_or_huge_car_names_never_500(self):
        for car in ('../../../etc/passwd', 'a/b', 'x' * 400, '..', '\x00'):
            for name, r in self._all(self.alice, car, 'Toyota'):
                # 503 = the documented 'search index unavailable' answer; 500 = a crash.
                self.assertNotEqual(r.status_code, 500, (name, repr(car)[:40], r.content[:200]))
