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


@skipUnless((CRAWL / 'pages' / 'groups.html').is_file(), 'no partsouq crawl on this machine')
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
