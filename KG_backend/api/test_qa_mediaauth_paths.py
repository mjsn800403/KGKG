"""Path normalization of the media gate (api/mediaauth.py).

The gate must judge the folder nginx will actually serve. nginx decodes %XX,
resolves dot-segments and merges slashes before serving, so the gate does too.
These cases were a confirmed bypass: a user entitled to one car fetched paid
images of another (audit-evidence/07-security, media-gate reproduction).
"""
from django.test import SimpleTestCase

from api.mediaauth import _folder

CAR = '4Runner%20Platinum'


class MediaFolderTest(SimpleTestCase):
    def test_plain_paths(self):
        self.assertEqual(_folder(f'/kg-api/media/{CAR}/a.png'), '4Runner Platinum')
        self.assertEqual(_folder(f'/kg-api/media/{CAR}/a.png?v=2'), '4Runner Platinum')
        self.assertEqual(_folder('/kg-api/media/_parts_assets/x.gif'), '_parts_assets')

    def test_dot_segments_resolve_to_the_served_folder(self):
        for uri in (f'/kg-api/media/_parts_assets/../{CAR}/a.png',
                    f'/kg-api/media/_parts_assets/%2e%2e/{CAR}/a.png',
                    f'/kg-api/media/_parts_assets/%2E%2E/{CAR}/a.png',
                    f'/kg-api/media/nonexistent/../{CAR}/a.png',
                    f'/kg-api/media/./{CAR}/a.png',
                    f'/kg-api/media//{CAR}/a.png',
                    f'//kg-api//media///{CAR}/a.png'):
            self.assertEqual(_folder(uri), '4Runner Platinum', uri)

    def test_escaping_the_media_root_is_not_a_media_path(self):
        for uri in ('/kg-api/media/../api/health/', '/kg-api/media/%2e%2e/%2e%2e/etc/passwd',
                    '/media/x/a.png', '', None, '/kg-api/media/a\x00.png'):
            self.assertIsNone(_folder(uri), uri)

    def test_media_root(self):
        self.assertEqual(_folder('/kg-api/media/'), '')
        self.assertEqual(_folder('/kg-api/media'), '')

    def test_query_string_cannot_smuggle_a_folder(self):
        self.assertEqual(_folder('/kg-api/media/_store/x.png?/../4Runner/'), '_store')
        # Dot-segments after '?' belong to the query, which nginx never serves
        # from: they must not re-target the folder (found by mutation testing:
        # without the split this resolved to the car folder).
        self.assertEqual(_folder(f'/kg-api/media/_parts_assets/x.png?/../../{CAR}/a.png'),
                         '_parts_assets')

    def test_only_paths_rooted_at_the_media_prefix_count(self):
        for uri in (f'X/kg-api/media/{CAR}/a.png', f'XX/kg-api/media/{CAR}/a.png',
                    f'/X/kg-api/media/{CAR}/a.png'):
            self.assertIsNone(_folder(uri), uri)
