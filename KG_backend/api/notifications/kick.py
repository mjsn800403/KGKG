"""Opportunistic send: a short-lived thread that drains the outbox right after
a notification is written, so staff hear about a message in seconds instead of
at the next timer tick. The timer remains the guaranteed path; losing this
thread (a worker restart) costs latency, never a notification.
"""
import threading

from django.db import close_old_connections

from . import config

_lock = threading.Lock()
_running = False


def _release():
    global _running
    with _lock:
        _running = False


def _drain():
    try:
        from . import worker
        worker.process_due()
    except Exception:
        import logging
        logging.getLogger('kgkg.notify').exception('opportunistic outbox drain failed')
    finally:
        close_old_connections()
        _release()


def _spawn():
    threading.Thread(target=_drain, name='kg-outbox-kick', daemon=True).start()


def kick(_testing=None):
    """Start a drain unless one is running. Returns True if one was started.
    A no-op when both channels are ``off`` and under the test runner (a daemon
    thread writing to the test database races the test transactions)."""
    global _running
    if _testing is None:
        from api.monitoring import TESTING as _testing
    if _testing:
        return False
    if config.mode('sms') == 'off' and config.mode('email') == 'off':
        return False
    with _lock:
        if _running:
            return False
        _running = True
    _spawn()
    return True
