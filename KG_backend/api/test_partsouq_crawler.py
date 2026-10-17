"""Partsouq crawler panel: URL validation and the host daemon allow-list."""
import os
from unittest import mock

from django.test import SimpleTestCase

from api import partsouq_crawler as ps

GOOD = ('https://partsouq.com/en/catalog/toyota/vehicle/GENERAL/2019/LAND-CRUISER/'
        'GRJ200L-GNTAKV/category/groups/vin/JTMHU01J6L5165492')


class ParseUrlTests(SimpleTestCase):
    def test_groups_url_gives_existing_folder_name(self):
        url, name = ps.parse_url(GOOD + '?ssd=x#top')
        self.assertEqual(url, GOOD)
        self.assertEqual(name, 'LandCruiser_2019_GRJ200L-GNTAKV_JTMHU01J6L5165492')

    def test_rejects_other_sites_and_injection(self):
        for bad in ('https://evil.com/en/catalog/toyota/vehicle/A/2019/B/C/category/groups/vin/JTMHU01J6L5165492',
                    GOOD.replace('JTMHU01J6L5165492', 'JTMHU01J6L516549'),
                    GOOD + '; reboot', GOOD.replace('GENERAL', '..'), '', None):
            self.assertEqual(ps.parse_url(bad), (None, None), bad)

    def test_spawn_rejects_mismatched_folder_or_unit(self):
        with self.assertRaises(ValueError):
            ps.spawn_crawl('kgkg-ps-crawl-1', GOOD, '../../etc')
        with self.assertRaises(ValueError):
            ps.spawn_crawl('cron.service', GOOD, ps.parse_url(GOOD)[1])

    def test_start_refuses_bad_url_first(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('KG_HOSTJOBS_DIR', None)
            pid, err = ps.start('https://partsouq.com/whatever')
        self.assertIsNone(pid)
        self.assertIn('آدرس', err)
