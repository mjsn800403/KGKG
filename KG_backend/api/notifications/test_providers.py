"""Mode switch and provider interface. Nothing here may reach a real provider."""
import os
from unittest import mock

from django.test import SimpleTestCase

from . import config, providers


class ModeTests(SimpleTestCase):
    def test_unset_and_garbage_mode_is_off(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('KG_NOTIFY_SMS', None)
            self.assertEqual(config.mode('sms'), 'off')
        for raw in ('', 'LIVE!!', 'on', 'true', '1'):
            with mock.patch.dict(os.environ, {'KG_NOTIFY_SMS': raw}):
                self.assertEqual(config.mode('sms'), 'off', raw)

    def test_valid_modes_are_read_per_channel_case_insensitively(self):
        with mock.patch.dict(os.environ, {'KG_NOTIFY_SMS': ' Live ', 'KG_NOTIFY_EMAIL': 'dry_run'}):
            self.assertEqual(config.mode('sms'), 'live')
            self.assertEqual(config.mode('email'), 'dry_run')

    def test_unknown_channel_is_off(self):
        self.assertEqual(config.mode('pigeon'), 'off')


class ProviderSelectionTests(SimpleTestCase):
    def test_get_provider_is_fake_under_tests_even_when_live(self):
        with mock.patch.dict(os.environ, {'KG_NOTIFY_SMS': 'live'}):
            self.assertIsInstance(providers.get_provider('sms'), providers.FakeProvider)

    def test_dry_run_provider_never_touches_the_network(self):
        r = providers.DryRunProvider().send('09120000000', '', 'x')
        self.assertTrue(r.accepted)
        self.assertEqual(r.provider_ref, 'dry')

    def test_fake_provider_records_and_can_fail(self):
        p = providers.FakeProvider()
        self.assertTrue(p.send('a', 's', 'b').accepted)
        p.fail_with = 'boom'
        r = p.send('a', 's', 'b')
        self.assertFalse(r.accepted)
        self.assertEqual(r.error, 'boom')
        self.assertEqual(len(p.sent), 2)


class MelipayamakTests(SimpleTestCase):
    def test_wrapper_passes_text_unchanged_and_maps_result(self):
        with mock.patch('api.portal._post_sms', return_value=(True, '12345678901')) as m:
            r = providers.MelipayamakSMS().send('09120000000', '', 'سلام\nلغو11')
        m.assert_called_once_with('09120000000', 'سلام\nلغو11')
        self.assertTrue(r.accepted)
        self.assertEqual(r.provider_ref, '12345678901')

    def test_rejected_by_operator_is_not_accepted_and_carries_code(self):
        with mock.patch('api.portal._post_sms', return_value=(False, '11')):
            r = providers.MelipayamakSMS().send('09120000000', '', 'x')
        self.assertFalse(r.accepted)
        self.assertIn('11', r.error)

    def test_transport_exception_becomes_a_failed_result_not_a_raise(self):
        with mock.patch('api.portal._post_sms', side_effect=OSError('down')):
            r = providers.MelipayamakSMS().send('09120000000', '', 'x')
        self.assertFalse(r.accepted)
        self.assertIn('down', r.error)


class SmtpTests(SimpleTestCase):
    def test_not_configured_returns_error_result_never_raises(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('EMAIL_HOST', None)
            r = providers.SMTPEmail().send('a@example.com', 'subj', 'body')
        self.assertFalse(r.accepted)
        self.assertIn('not configured', r.error)


class SmsBodyTests(SimpleTestCase):
    def test_ok_body_passes(self):
        self.assertIsNone(providers.check_sms_body('خدمات گستر\nپاسخ پشتیبانی آماده است.\nلغو11'))

    def test_link_rejected(self):
        self.assertIsNotNone(providers.check_sms_body('see https://x.ir\nلغو11'))
        self.assertIsNotNone(providers.check_sms_body('see kgtechvault.com\nلغو11'))

    def test_persian_body_without_optout_footer_rejected(self):
        self.assertIsNotNone(providers.check_sms_body('پاسخ آماده است'))

    def test_ascii_body_needs_no_footer(self):
        self.assertIsNone(providers.check_sms_body('Reply ready'))
