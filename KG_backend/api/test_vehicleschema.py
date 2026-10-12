"""Tests for the schema.org vehicle-spec derivation engine."""
import sqlite3
import tempfile
from pathlib import Path
from unittest import mock

from django.test import TestCase

from . import dataquality, vehicleschema
from .models import Car, VehicleSpec
from .rag import config


class ParseStemTest(TestCase):
    def test_full_stem(self):
        p = vehicleschema.parse_stem('4Runner Limited, 2.4L Eng VIN A, AWD')
        self.assertEqual(p['model'], '4Runner')
        self.assertEqual(p['trim'], 'Limited')
        self.assertEqual(p['displacement_l'], 2.4)
        self.assertEqual(p['engine_vin'], 'A')
        self.assertEqual(p['drivetrain'], 'AWD')
        self.assertFalse(p['manual_trans'])
        self.assertIsNone(p['year_suffix'])

    def test_compound_model_beats_prefix(self):
        p = vehicleschema.parse_stem('Corolla Cross Hybrid XSE')
        self.assertEqual(p['model'], 'Corolla Cross')
        self.assertEqual(p['trim'], 'Hybrid XSE')
        p2 = vehicleschema.parse_stem('GR Corolla Premium')
        self.assertEqual(p2['model'], 'GR Corolla')

    def test_manual_transmission_token(self):
        p = vehicleschema.parse_stem('GR86 Premium, Standard Trans')
        self.assertEqual(p['model'], 'GR86')
        self.assertTrue(p['manual_trans'])

    def test_lexus(self):
        p = vehicleschema.parse_stem('NX 350h')
        self.assertEqual(p['model'], 'NX')
        self.assertEqual(p['trim'], '350h')

    def test_year_suffix(self):
        p = vehicleschema.parse_stem('Corolla Cross LE, FWD (2023)')
        self.assertEqual(p['year_suffix'], 2023)
        self.assertEqual(p['base'], 'Corolla Cross LE, FWD')
        self.assertEqual(p['model'], 'Corolla Cross')
        self.assertEqual(p['drivetrain'], 'FWD')

    def test_4wd_and_vin_c(self):
        p = vehicleschema.parse_stem('Tundra Limited, 3.4L Eng VIN C, 4WD')
        self.assertEqual(p['drivetrain'], '4WD')
        self.assertEqual(p['engine_vin'], 'C')
        self.assertEqual(p['displacement_l'], 3.4)


class DeriveTest(TestCase):
    def _car(self, stem, brand='Toyota', year=2025):
        return Car.objects.create(brand_name=brand, car_name=stem, year=year,
                                  db_address=f'./Database_warehouse/{stem}.db')

    def test_gas_suv_tier1(self):
        car = self._car('4Runner SR5 4WD')
        data, prov, _ = vehicleschema.derive(car)
        self.assertEqual(data['@type'], 'Car')
        self.assertEqual(data['model'], '4Runner')
        self.assertEqual(data['fuelType'], 'Gasoline')
        self.assertEqual(data['bodyType'], 'SUV')
        self.assertEqual(prov['bodyType']['source'], 'curated')
        # leave-null policy: nothing invented
        for absent in ('weight', 'wheelbase', 'vehicleSeatingCapacity',
                       'seatingCapacity', 'accelerationTime', 'speed'):
            self.assertNotIn(absent, data)
        # provenance covers every non-@ field
        for k in data:
            if not k.startswith('@') and k != 'additionalProperty':
                self.assertIn(k, prov, f'missing provenance for {k}')

    def test_ev_and_hybrid_and_hydrogen(self):
        ev, _, _ = vehicleschema.derive(self._car('bZ4X Nightshade'))
        self.assertEqual(ev['fuelType'], 'Electric')
        self.assertEqual(ev['vehicleEngine']['engineType'], 'Electric motor')
        hy, _, _ = vehicleschema.derive(self._car('Corolla Cross Hybrid S'))
        self.assertIn('Hybrid', hy['fuelType'])
        lex, _, _ = vehicleschema.derive(self._car('NX 350h', brand='Lexus'))
        self.assertIn('Hybrid', lex['fuelType'])
        mirai, prov, _ = vehicleschema.derive(self._car('Mirai Limited'))
        self.assertIn('Hydrogen', mirai['fuelType'])
        self.assertEqual(prov['fuelType']['source'], 'curated')
        prius, _, _ = vehicleschema.derive(self._car('Prius LE'))
        self.assertIn('Hybrid', prius['fuelType'])

    def test_engine_tokens(self):
        data, _, _ = vehicleschema.derive(
            self._car('Camry LE, 2.5L Eng VIN A'))
        eng = data['vehicleEngine']
        self.assertEqual(eng['engineDisplacement']['value'], 2.5)
        self.assertIn('VIN code A', eng['engineType'])

    def test_manual_transmission(self):
        data, prov, _ = vehicleschema.derive(
            self._car('GR86 Premium, Standard Trans'))
        self.assertEqual(data['vehicleTransmission'], 'Manual')
        self.assertEqual(prov['vehicleTransmission']['source'], 'stem')

    def test_year_suffixed_name(self):
        data, _, _ = vehicleschema.derive(
            self._car('Corolla Cross LE, FWD (2023)', year=2023))
        self.assertEqual(data['name'], '2023 Toyota Corolla Cross LE, FWD')
        self.assertEqual(data['vehicleModelDate'], '2023')

    def test_build_for_stem_persists_and_public_subset(self):
        car = self._car('Sienna LE, 2.5L Eng VIN R')
        vehicleschema.build_for_stem(car.car_name)
        sp = VehicleSpec.objects.get(car=car)
        self.assertEqual(sp.builder_version, vehicleschema.BUILDER_VERSION)
        pub = vehicleschema.public_jsonld(sp.data)
        self.assertEqual(pub['@context'], 'https://schema.org')
        self.assertNotIn('additionalProperty', pub)
        # stale_stems no longer reports it
        self.assertNotIn(car.car_name, vehicleschema.stale_stems())


class ManualSpecParseTest(TestCase):
    FLUIDS_HTML = """
    <h1>Fluids</h1><p>FLUID CAPACITIES</p>
    <table class="clsArticleTable"><tbody>
      <tr class="clsTblHead"><th>Fluid</th><th>Capacity</th><th>Type</th></tr>
      <tr><td>Automatic Transmission Fluid</td><td>12.20 QTS. 11.54 L</td><td>Type WS</td></tr>
      <tr><td>Engine Oil (with filter)</td><td>4.6 QTS. 4.4 L</td><td>SAE 0W-16</td></tr>
      <tr><td>A/C Refrigerant</td><td>0.56 KG</td><td>R-1234yf</td></tr>
      <tr><td>Fuel Tank</td><td>14.5 GAL. 55.0 L</td><td>—</td></tr>
      <tr><td>Something Irrelevant</td><td>1</td><td>2</td></tr>
    </tbody></table>
    """
    TIRES_HTML = '<table><tr><td>225/65R17</td><td>P235/55 R 20</td></tr></table>'

    def _make_car_db(self, dirpath, stem):
        db = Path(dirpath) / f'{stem}.db'
        con = sqlite3.connect(db)
        con.execute("""CREATE TABLE nodes (id TEXT PRIMARY KEY, parent_id TEXT,
            path TEXT, title TEXT, node_type TEXT, file_type TEXT, href TEXT,
            source_file TEXT, sort_order INTEGER, depth INTEGER,
            root_order INTEGER, content TEXT, updated_at TEXT)""")
        con.execute(
            "INSERT INTO nodes (id, path, title, file_type, content) VALUES "
            "('f1', 'Toyota: 2025: X/Repair and Diagnosis (Single Page)/"
            "Quick Lookups/Fluids', 'Fluids', 'end_path', ?)",
            (self.FLUIDS_HTML,))
        con.execute(
            "INSERT INTO nodes (id, path, title, file_type, content) VALUES "
            "('t1', 'Toyota: 2025: X/Repair and Diagnosis (Single Page)/"
            "Quick Lookups/Tire Fitment', 'Tire Fitment', 'end_path', ?)",
            (self.TIRES_HTML,))
        con.commit()
        con.close()
        return db

    def test_fluids_and_tires(self):
        with tempfile.TemporaryDirectory() as tmp:
            stem = 'Testcar LE'
            self._make_car_db(tmp, stem)
            with mock.patch.object(config, 'WAREHOUSE_DIR', Path(tmp)):
                specs = vehicleschema.parse_manual_specs(stem)
        self.assertTrue(specs['auto_trans'])
        self.assertEqual(specs['fuel_tank_l'], 55.0)
        names = [f['name'] for f in specs['fluids']]
        self.assertIn('Automatic Transmission Fluid', names)
        self.assertIn('A/C Refrigerant', names)
        self.assertNotIn('Something Irrelevant', names)
        self.assertIn('225/65R17', specs['tires'])
        self.assertEqual(len(specs['sections']), 2)

    def test_missing_db_is_empty(self):
        specs = vehicleschema.parse_manual_specs('No Such Car Whatsoever')
        self.assertEqual(specs['fluids'], [])
        self.assertIsNone(specs['fuel_tank_l'])

    def test_manual_signal_feeds_transmission(self):
        with tempfile.TemporaryDirectory() as tmp:
            stem = 'Testcar LE'
            self._make_car_db(tmp, stem)
            car = Car.objects.create(brand_name='Toyota', car_name=stem,
                                     year=2025, db_address='x')
            with mock.patch.object(config, 'WAREHOUSE_DIR', Path(tmp)):
                data, prov, sections = vehicleschema.derive(car)
        self.assertEqual(data['vehicleTransmission'], 'Automatic')
        self.assertEqual(prov['vehicleTransmission']['source'], 'manual')
        self.assertEqual(data['fuelCapacity']['value'], 55.0)
        self.assertTrue(any('Fluids' in s for s in sections))
        block = vehicleschema.compact_block(data)
        self.assertIn('Fuel tank: 55.0 L', block)


class PowertrainDetectionTest(TestCase):
    def test_whole_model_electrified(self):
        for stem in ('Prius LE', 'Prius Prime SE', 'Sienna XLE',
                     'Venza Limited', 'Crown Platinum', 'Crown Signia XLE',
                     'RAV4 Prime SE', 'Mirai Limited'):
            self.assertTrue(dataquality.is_electrified(stem), stem)

    def test_pure_ev(self):
        self.assertTrue(dataquality.is_pure_ev('bZ4X Nightshade'))
        self.assertTrue(dataquality.is_pure_ev('Mirai Limited'))
        self.assertFalse(dataquality.is_pure_ev('Prius LE'))

    def test_gas_unchanged(self):
        self.assertFalse(dataquality.is_electrified('Camry LE, 2.5L Eng VIN A'))
        self.assertFalse(dataquality.is_electrified('4Runner TRD Pro'))
