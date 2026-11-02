"""Delivery providers behind one interface.

``send`` never raises: a provider that is down, unconfigured or rejecting is a
failed ``SendResult`` the worker can retry, not a crash. ``accepted`` means the
provider took the message (SMS ``Value > 1000``, SMTP 250). It is not proof the
handset or mailbox received it; neither Melipayamak receipts nor email bounces
are observed yet.
"""
import logging
import os
import re
from dataclasses import dataclass

from . import config

log = logging.getLogger('kgkg.notify')

OPT_OUT_FOOTER = 'لغو11'
_PERSIAN = re.compile('[؀-ۿ]')
# The SMS operator treats dotted names and dotted numbers as links (code 14).
_LINKISH = re.compile(r'(https?://|www\.|[A-Za-z0-9-]+\.[A-Za-z]{2,}|\d+\.\d+)', re.I)


@dataclass
class SendResult:
    accepted: bool
    provider_ref: str = ''
    error: str = ''


def check_sms_body(text):
    """None when the operator will accept ``text``, else why it will not."""
    if _LINKISH.search(text):
        return 'body contains a link or dotted name (operator code 14)'
    if _PERSIAN.search(text) and OPT_OUT_FOOTER not in text:
        return f'Persian body needs the {OPT_OUT_FOOTER} footer (operator code 11)'
    return None


class FakeProvider:
    """Test double: records every call; ``fail_with`` makes the next sends fail."""
    def __init__(self):
        self.sent = []
        self.fail_with = ''

    def send(self, to, subject, body):
        self.sent.append((to, subject, body))
        if self.fail_with:
            return SendResult(False, error=self.fail_with)
        return SendResult(True, provider_ref=f'fake-{len(self.sent)}')


class DryRunProvider:
    def send(self, to, subject, body):
        log.info('notify dry-run to %s: %r', to[-4:], body[:80])
        return SendResult(True, provider_ref='dry')


class MelipayamakSMS:
    def send(self, to, subject, body):
        from api import portal
        try:
            ok, value = portal._post_sms(to, body)
        except Exception as exc:
            return SendResult(False, error=f'transport: {exc}'[:300])
        if ok:
            return SendResult(True, provider_ref=str(value))
        return SendResult(False, error=f'operator refused (Value={value or "none"})')


class SMTPEmail:
    def send(self, to, subject, body):
        host = os.environ.get('EMAIL_HOST', '')
        sender = os.environ.get('KG_NOTIFY_FROM_EMAIL', '')
        if not host or not sender:
            return SendResult(False, error='email not configured (EMAIL_HOST/KG_NOTIFY_FROM_EMAIL)')
        try:
            from django.core.mail import EmailMessage, get_connection
            conn = get_connection(
                backend='django.core.mail.backends.smtp.EmailBackend', host=host,
                port=int(os.environ.get('EMAIL_PORT', '587')),
                username=os.environ.get('EMAIL_HOST_USER', ''),
                password=os.environ.get('EMAIL_HOST_PASSWORD', ''),
                use_tls=os.environ.get('EMAIL_USE_TLS', '1') != '0',
                timeout=10, fail_silently=False)
            sent = EmailMessage(subject, body, sender, [to], connection=conn).send()
        except Exception as exc:
            return SendResult(False, error=f'smtp: {exc}'[:300])
        return SendResult(bool(sent), provider_ref='smtp' if sent else '',
                          error='' if sent else 'smtp accepted nothing')


_fake = FakeProvider()


def get_provider(channel):
    """The provider the current mode allows. Under the test runner this is
    always the shared fake, whatever the environment says."""
    from api.monitoring import TESTING
    if TESTING:
        return _fake
    if config.mode(channel) == 'dry_run':
        return DryRunProvider()
    return MelipayamakSMS() if channel == 'sms' else SMTPEmail()
