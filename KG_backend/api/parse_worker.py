"""Subprocess entrypoint for parallel ZIP parsing.

The HTML crawl uses html5lib (pure Python, GIL-bound), so thread pools can't
use more than one core for it. Real parallelism needs separate PROCESSES, one
per ZIP. This module is the process target — kept deliberately free of
module-level Django imports so a ``spawn``-started child can import it BEFORE
``django.setup()`` runs (``spawn`` is used, not ``fork``, because the parent
worker is multithreaded — forking under a held lock could deadlock the child).

``worker_init`` runs once per pool process: it detaches the inherited SIGTERM
handling (a child killed when the job is cancelled just terminates; the
parser's incremental crawl checkpoints make the ZIP resumable) and boots
Django. ``parse_one`` parses a single queued ZIP and returns a small result
dict — no references to the parent's Runner cross the process boundary.
"""


def worker_init():
    import os
    import signal
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'KG_backend.settings')
    import django
    django.setup()


def parse_one(pkg_id):
    """Parse one ZipPackage in this subprocess. Returns
    {id, outcome, name, error, elapsed}. Never raises across the boundary."""
    import time
    result = {'id': pkg_id, 'outcome': 'failed', 'name': str(pkg_id),
              'error': '', 'elapsed': 0.0}
    t0 = time.monotonic()
    try:
        from api.models import ZipPackage
        from api import ingest
        pkg = ZipPackage.objects.filter(id=pkg_id).first()
        if pkg is None:
            result['outcome'] = 'skipped'
            return result
        result['name'] = pkg.zip_name
        if pkg.status != 'pending':
            result['outcome'] = 'skipped'
            return result
        # cancel_event is intraprocess only; cross-process cancel is handled by
        # SIGTERM to the whole cgroup, so we pass None here.
        outcome = ingest.parse_zip_package(pkg, cancel_event=None, log=None)
        result['outcome'] = outcome
        if outcome == 'failed':
            try:
                pkg.refresh_from_db()
                result['error'] = (pkg.error or '')[:150]
            except Exception:
                pass
    except Exception as e:
        result['outcome'] = 'failed'
        result['error'] = f'{e.__class__.__name__}: {e}'[:200]
    finally:
        result['elapsed'] = round(time.monotonic() - t0, 1)
    return result
