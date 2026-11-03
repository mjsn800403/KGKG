"""Masking of visitor contact details shown to staff by default."""

DOT = '•'


def phone(value):
    value = value or ''
    if len(value) <= 6:
        return DOT * len(value)
    return value[:4] + DOT * (len(value) - 6) + value[-2:]


def email(value):
    value = value or ''
    local, at, domain = value.partition('@')
    if not at:
        return DOT * len(value)
    return (local[:1] + DOT * 3 if local else DOT * 3) + at + domain
