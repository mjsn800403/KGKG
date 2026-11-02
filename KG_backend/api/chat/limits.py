"""Input rules for anonymous visitors: what we accept, normalised."""
import re
import unicodedata

from api.models import normalize_phone

MAX_BODY = 2000
MAX_PER_THREAD_PER_HOUR = 30
INTENTS = ('sales', 'demo', 'technical', 'other')

_EMAIL = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
_CLIENT_ID = re.compile(r'^[A-Za-z0-9_-]{1,40}$')


def clean_body(raw):
    """(text, error). The text keeps the visitor's own characters (RTL marks,
    emoji) but is rejected when nothing a person could read is left: only
    whitespace and invisible format characters count as empty."""
    if not isinstance(raw, str):
        return '', 'پیام خالی است.'
    text = ''.join(ch for ch in raw
                   if ch in '\n\t' or unicodedata.category(ch) != 'Cc').strip()
    visible = [ch for ch in text if not ch.isspace() and unicodedata.category(ch) != 'Cf']
    if not visible:
        return '', 'پیام خالی است.'
    if len(text) > MAX_BODY:
        return '', f'پیام نباید بیشتر از {MAX_BODY} نویسه باشد.'
    return text, None


def clean_client_id(raw):
    raw = raw if isinstance(raw, str) else ''
    return raw if _CLIENT_ID.match(raw) else ''


def clean_intent(raw):
    return raw if raw in INTENTS else 'other'


def clean_contact(raw):
    """({name, phone, email} with only the fields supplied, error)."""
    if not isinstance(raw, dict):
        return {}, None
    out = {}
    if 'name' in raw:
        out['contact_name'] = str(raw.get('name') or '').strip()[:120]
    if raw.get('phone'):
        phone = normalize_phone(raw['phone'])
        digits = phone.lstrip('+')
        if not (10 <= len(digits) <= 15) or not digits.isdigit():
            return {}, 'شمارهٔ تلفن معتبر نیست.'
        out['contact_phone'] = phone
    if raw.get('email'):
        email = str(raw['email']).strip()
        if len(email) > 254 or not _EMAIL.match(email):
            return {}, 'ایمیل معتبر نیست.'
        out['contact_email'] = email
    return out, None
