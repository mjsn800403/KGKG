"""TIS crawl folders -> parse queue -> car database (ingest + tis_parser)."""
import sqlite3
import tempfile
from pathlib import Path
from unittest import mock

from django.test import TestCase

from api import ingest
from api.models import Car, ZipPackage

PAGE = """<html><head><title>T</title><script>alert(1)</script></head><body>
<table class="side"><tr><td><b>Doc ID: </b>{docid}</td></tr></table>
<h2 class="name">{name}</h2>
<img src="../../../../../_assets/abc123_fig.png"/>
<a href="{link}">see other</a> <a href="javascript:void(0)" onclick="x()">js</a>
</body></html>"""

NAV = """<html><body><h2>Pub</h2>
<details open><summary>Brake _ ABS</summary><div class='grp'>
<a class="leaf" href="../Brake%20_%20ABS/REMOVAL/content.html">REMOVAL</a>
<a class="leaf" href="../Brake%20_%20ABS/INSTALLATION/content.html">INSTALLATION</a>
</div></details></body></html>"""


def make_vehicle(root, name='Test Car_2024'):
    v = Path(root) / name
    pub = v / 'RM' / 'Test Repair Manual (RM1)'
    (pub / '_viewer').mkdir(parents=True)
    (pub / '_viewer' / 'nav.html').write_text(NAV, encoding='utf-8')
    for leaf, docid, other in (('REMOVAL', 'RM0001', 'INSTALLATION'),
                               ('INSTALLATION', 'RM0002', 'REMOVAL')):
        d = pub / 'Brake _ ABS' / leaf
        d.mkdir(parents=True)
        (d / 'content.html').write_text(PAGE.format(
            docid=docid, name=leaf, link=f'../{other}/content.html#s1'), encoding='utf-8')
    sb = v / 'SB_TT' / 'T-SB-0001_ Brake Noise'
    sb.mkdir(parents=True)
    (sb / 'T-SB-0001.pdf').write_bytes(b'%PDF-1.4 test')
    (v / 'Summary' / '_list').mkdir(parents=True)
    assets = Path(root) / '_assets'
    assets.mkdir(exist_ok=True)
    (assets / 'abc123_fig.png').write_bytes(b'\x89PNG test')
    return v


class TisParserTest(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.vehicle = make_vehicle(self.root / 'inbox')
        self.wh = self.root / 'wh'
        self.static = self.root / 'static'
        self.wh.mkdir()
        self.static.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_builds_same_node_schema_with_links_and_images(self):
        tis = ingest.tis_module()
        r = tis.process_vehicle(self.vehicle, self.wh, self.static,
                                stem='Test Car (2024)',
                                publish_images=ingest.parser_module()._publish_images)
        self.assertEqual((r['brand'], r['year'], r['pages']), ('Toyota', 2024, 3))
        con = sqlite3.connect(self.wh / 'Test Car (2024).db')
        rows = {p: (t, ft, h, c) for p, t, ft, h, c in con.execute(
            'SELECT path, title, file_type, href, content FROM nodes')}
        leaf = 'Test Car (2024)/Repair Manual/Test Repair Manual (RM1)/Brake ⁄ ABS/REMOVAL'
        self.assertIn(leaf, rows)
        title, ft, href, content = rows[leaf]
        self.assertEqual((ft, href), ('end_path', 'pages/RM0001.html'))
        self.assertIn('href="pages/RM0002.html#s1"', content)      # cross-link
        self.assertIn('src="../images/abc123_fig.png"', content)   # asset
        for gone in ('<script', 'onclick', 'javascript:', 'Doc ID'):
            self.assertNotIn(gone, content)
        # Sidebar order is kept, and the unambiguous '/' is restored in titles.
        order = [p.rsplit('/', 1)[1] for p, in con.execute(
            "SELECT path FROM nodes WHERE file_type='end_path' AND path LIKE '%ABS/%' "
            "ORDER BY sort_order")]
        self.assertEqual(order, ['REMOVAL', 'INSTALLATION'])
        pdf = [c for p, (t, ft, h, c) in rows.items() if 'Service Bulletins/' in p]
        self.assertEqual(len(pdf), 1)
        self.assertIn('/media/Test%20Car%20%282024%29/', pdf[0])
        self.assertFalse(any('Summary' in p for p in rows))        # listings skipped
        published = {f.name for f in (self.static / 'Test Car (2024)').iterdir()}
        self.assertIn('abc123_fig.png', published)
        self.assertTrue(any(n.endswith('_T-SB-0001.pdf') for n in published))

    def test_scan_registers_ready_folder_and_ignores_empty_one(self):
        (self.root / 'inbox' / 'Empty Car_2025' / 'RM' / '_list').mkdir(parents=True)
        with mock.patch.dict('os.environ', {'KG_TIS_INBOX': str(self.root / 'inbox'),
                                            'KG_ZIP_INBOX': str(self.root / 'none')}), \
                mock.patch.object(ingest.config, 'WAREHOUSE_DIR', self.wh):
            summary = ingest.scan_inbox()
            self.assertEqual(summary['registered'], 1)
            pkg = ZipPackage.objects.get(path=str(self.vehicle))
            self.assertEqual((pkg.zip_name, pkg.stem, pkg.status),
                             ('TIS 2024 Toyota Test Car', 'Test Car (2024)', 'pending'))
            self.assertFalse(ZipPackage.objects.filter(path__contains='Empty Car').exists())
            # Re-scan without changes keeps it; parsing fills the catalog.
            self.assertEqual(ingest.scan_inbox()['registered'], 0)
            with mock.patch.object(ingest.settings, 'BASE_DIR', str(self.root / 'backend')):
                (self.root / 'backend' / 'static_warehouse').mkdir(parents=True)
                self.assertEqual(ingest.parse_zip_package(pkg), 'done')
        pkg.refresh_from_db()
        self.assertEqual((pkg.status, pkg.pages_processed), ('done', 3))
        car = Car.objects.get(car_name='Test Car (2024)')
        self.assertEqual((car.brand_name, car.year), ('Toyota', 2024))
        self.assertTrue((self.wh / 'Test Car (2024).db').exists())
