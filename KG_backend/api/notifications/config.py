"""Per-channel delivery mode.

``off`` (the default) records nothing as sent and contacts nobody. ``dry_run``
renders and logs. ``live`` contacts the provider. Anything unrecognised is
``off``: a typo in a server env file must never start spending money.
"""
import os

MODES = ('off', 'dry_run', 'live')
CHANNELS = {'sms': 'KG_NOTIFY_SMS', 'email': 'KG_NOTIFY_EMAIL'}


def mode(channel):
    var = CHANNELS.get(channel)
    if var is None:
        return 'off'
    raw = os.environ.get(var, '').strip().lower()
    return raw if raw in MODES else 'off'
