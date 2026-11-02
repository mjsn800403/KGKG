"""partsouq_build: input validation, and a real build of the crawl on this server (if present)."""
import sqlite3
import tempfile
from pathlib import Path
from unittest import mock, skipUnless

from django.test import TestCase

from api import partsouq_build as pb, partsouq_crawler

CRAWL = partsouq_crawler.OUT_ROOT / 'LandCruiser_2019_GRJ200L-GNTAKV_JTMHU01J6L5165492'


class ValidationTests(TestCase):
    def test_rejects_bad_folder_and_car_name(self):
        self.assertIn('پوشه', pb.build_and_register('../../etc', 'Car (2019)')[1])
        self.assertIn('نام خودرو', pb.build_and_register(CRAWL.name, '../x')[1])
        self.assertIn('نام خودرو', pb.build_and_register(CRAWL.name, 'x')[1])


class ParseFolderTests(TestCase):
    """parse_folder replaced a regex CodeQL reported as polynomial; same accepted names."""
    OK = 'LandCruiser_2019_GRJ200L-GNTAKV_JTMHU01J6L5165492'

    def test_accepts_a_real_crawl_folder(self):
        self.assertEqual(pb.parse_folder(self.OK), {
            'model': 'LandCruiser', 'year': '2019', 'frame': 'GRJ200L-GNTAKV',
            'vin': 'JTMHU01J6L5165492'})

    def test_rejects_malformed_names(self):
        bad = ['', '../../etc', 'a_b_c', self.OK + '_x', 'LandCruiser_19_F_JTMHU01J6L5165492',
               'LandCruiser_2019__JTMHU01J6L5165492', '_2019_F_JTMHU01J6L5165492',
               'LandCruiser_2019_F_JTMHU01J6L516549',          # 16-char VIN
               'LandCruiser_2019_F_JTMHU01J6L5165492X',        # 18-char VIN
               'LandCruiser_2019_F_ITMHU01J6L5165492',         # I is not in a VIN
               'Land Cruiser_2019_F_JTMHU01J6L5165492', 'Land/Cruiser_2019_F_JTMHU01J6L5165492',
               'LandCruiser_٢٠١٩_F_JTMHU01J6L5165492', None, 42]
        for name in bad:
            with self.subTest(name=name):
                self.assertIsNone(pb.parse_folder(name))

    def test_long_runs_are_rejected_fast(self):
        import time
        t = time.perf_counter()
        self.assertIsNone(pb.parse_folder('0' * 100_000))
        self.assertIsNone(pb.parse_folder('0_' * 50_000))
        self.assertLess(time.perf_counter() - t, 1.0)


def _crawl_present():
    try:   # an unreadable /root (CI runners) means "not on this machine"
        return (CRAWL / 'pages' / 'groups.html').is_file()
    except OSError:
        return False


@skipUnless(_crawl_present(), 'no partsouq crawl on this machine')
class RealCrawlBuildTests(TestCase):
    def test_builds_a_servable_db_into_a_scratch_backend(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(pb, 'load_fa_terms', return_value={}):
            counts = pb.build_db(CRAWL, 'Test Cruiser (2019)', 'GXR', backend=tmp)
            db = Path(tmp, 'Database_warehouse', '_parts', 'Test Cruiser (2019).db')
            c = sqlite3.connect(db)
            self.assertEqual(c.execute('select count(*) from groups').fetchone()[0], counts['groups'])
            self.assertGreater(counts['groups'], 100)
            self.assertGreater(counts['rows'], 1000)
            self.assertEqual(c.execute('select grade from frames').fetchone()[0], 'GXR')
            img = c.execute('select image_url from sections limit 1').fetchone()[0]
            self.assertTrue(img.startswith('/media/_parts_assets/ps_jtmhu01j6l5165492_c_'), img)
            self.assertEqual(counts['uncleaned'], 0)
            from PIL import Image
            with Image.open(Path(tmp, 'static_warehouse', '_parts_assets', Path(img).name)) as im:
                # only pure black and white left: the grey watermark is gone
                self.assertEqual({v for _, v in im.convert('L').getcolors()}, {0, 255})
