"""Input rules for anonymous visitors: what we accept, normalised."""
import re
import unicodedata

from api.models import normalize_phone

MAX_BODY = 2000
INTENTS = ('sales', 'demo', 'technical', 'other')

_CLIENT_ID = re.compile(r'^[A-Za-z0-9_-]{1,40}$')


def valid_email(value):
    """True for ``local@domain.tld``-shaped text: exactly one '@', a non-empty local
    part, no whitespace anywhere, and a domain containing a dot with at least one
    character on each side.

    Same acceptance as the regex it replaced (``^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$``), which
    CodeQL flagged as polynomial on user input; this is a single linear scan with no
    backtracking. Shape only: it does not claim the address exists."""
    if not isinstance(value, str) or any(ch.isspace() for ch in value):
        return False
    local, at, domain = value.partition('@')
    if not at or not local or not domain or '@' in domain:
        return False
    # A dot at index 1..len-2 of the domain: something before it and after it.
    return domain.find('.', 1, len(domain) - 1) != -1


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


def clean_page(raw):
    """A site path with no query string or fragment: those can carry personal
    data (a phone number in a form URL) and the page alone is what staff need."""
    raw = str(raw or '').strip()
    if not raw.startswith('/') or raw.startswith('//'):
        return ''
    return raw.split('?', 1)[0].split('#', 1)[0][:200]


def clean_referrer(raw):
    """scheme://host/path of an http(s) referrer, without query or fragment."""
    raw = str(raw or '').strip()
    if not re.match(r'^https?://[^/\s]+', raw, re.I):
        return ''
    return raw.split('?', 1)[0].split('#', 1)[0][:200]


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
        if len(email) > 254 or not valid_email(email):
            return {}, 'ایمیل معتبر نیست.'
        out['contact_email'] = email
    return out, None
