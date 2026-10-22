"""Partsouq VIN crawler status and start/stop for the admin pipeline page.

The crawler (``ops/partsouq/partsouq_vin_crawl.py``) drives the same server
Chrome as the TIS crawler (CDP on 127.0.0.1:9222): plain HTTP gets a
Cloudflare 403, a real browser passes. One vehicle = one VIN catalog URL; it
is polite (one tab, 4-8 s per page), resumable, and stops by itself on a
persistent Cloudflare challenge. Output: ``KG_PS_DIR/<vehicle>/`` with pages/,
images/, parts.json and parts.csv.

Like tis_crawler, this module is Django-free so the host-job daemon can import it.
"""
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from . import hostjobs, tis_crawler

OUT_ROOT = Path(os.environ.get('KG_PS_DIR', '/root/partsouq_crawl'))
# On the host (the backend container has no ops/ tree; it asks the host to run it).
SCRIPT = Path(os.environ.get('KG_PS_SCRIPT', '/opt/KGKG/ops/partsouq/partsouq_vin_crawl.py'))
PYTHON = tis_crawler.PYTHON          # the crawler venv (has nodriver)
PROC = r'partsouq_vin_crawl\.py'
UNIT = re.compile(r'kgkg-ps-crawl-\d+')

# https://partsouq.com/en/catalog/toyota/vehicle/<market>/<year>/<model>/<code>/category/groups/vin/<VIN>
START_URL = re.compile(
    r'https://partsouq\.com/en/catalog/toyota/vehicle/'
    r'(?P<market>[A-Za-z0-9_-]+)/(?P<year>\d{4})/(?P<model>[A-Za-z0-9_-]+)/(?P<code>[A-Za-z0-9_-]+)/'
    r'category/groups/vin/(?P<vin>[A-HJ-NPR-Z0-9]{17})')


def parse_url(url):
    """(clean url, output folder name) for a partsouq VIN groups URL, or (None, None)."""
    url = (url or '').strip().split('?')[0].split('#')[0]
    m = START_URL.fullmatch(url)
    if not m:
        return None, None
    model = ''.join(w.title() for w in m['model'].split('-'))
    return url, f"{model}_{m['year']}_{m['code']}_{m['vin']}"


def _pids():
    return hostjobs.pgrep(PROC)


def _crawls():
    out = []
    try:
        dirs = sorted((d for d in OUT_ROOT.iterdir() if d.is_dir()),
                      key=lambda d: d.stat().st_mtime, reverse=True)
    except OSError:
        return out
    for d in dirs[:30]:
        pages = d / 'pages'
        try:
            n_pages = sum(1 for _ in pages.iterdir())
            diagrams = sum(1 for p in pages.iterdir() if p.name.startswith('diagram_'))
        except OSError:
            n_pages = diagrams = 0
        try:
            images = sum(1 for _ in (d / 'images').iterdir())
        except OSError:
            images = 0
        log = d / 'crawl.log'
        last = tis_crawler._tail(log, 1)
        try:
            at = datetime.fromtimestamp(log.stat().st_mtime, tz=timezone.utc).isoformat()
        except OSError:
            at = None
        out.append({'name': d.name, 'pages': n_pages, 'diagrams': diagrams, 'images': images,
                    'done': 'DONE:' in last, 'blocked': 'STOPPING' in last,
                    'has_parts': (d / 'parts.json').is_file(), 'last_line': last, 'last_at': at})
    return out


def status():
    crawls = _crawls()
    pids = _pids()
    latest = crawls[0]['name'] if crawls else None
    return {
        'installed': hostjobs.enabled() or SCRIPT.is_file(),
        'dir': str(OUT_ROOT),
        'running': bool(pids),
        'pids': pids,
        'chrome': tis_crawler._chrome(),
        'crawls': crawls,
        'log_tail': tis_crawler._tail(OUT_ROOT / latest / 'crawl.log') if latest else '',
    }


def start(url):
    """Start a crawl of one VIN catalog. Returns (pid, error)."""
    url, name = parse_url(url)
    if not url:
        return None, ('آدرس معتبر نیست. آدرس صفحهٔ گروه‌های قطعات VIN در partsouq را وارد کنید '
                      '(…/category/groups/vin/<VIN>).')
    if not (hostjobs.enabled() or SCRIPT.is_file()):
        return None, 'اسکریپت خزشگر partsouq روی سرور پیدا نشد.'
    if _pids():
        return None, 'خزشگر partsouq در حال اجراست.'
    if tis_crawler._pids():
        return None, 'خزشگر TIS از همین مرورگر استفاده می‌کند؛ ابتدا آن را متوقف کنید.'
    if not tis_crawler._chrome()['reachable']:
        return None, 'Chrome در دسترس نیست. ابتدا «راه‌اندازی Chrome» را در کارت TIS بزنید.'
    unit = 'kgkg-ps-crawl-%d' % int(time.time())
    try:
        if hostjobs.enabled():
            hostjobs.call('ps_crawl_start', unit=unit, url=url, name=name)
        else:
            spawn_crawl(unit, url, name)
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        return None, 'اجرای خزشگر ناموفق بود: %s' % e
    for _ in range(20):
        pids = _pids()
        if pids:
            return pids[0], None
        time.sleep(0.25)
    return None, 'خزشگر اجرا شد اما فرایند آن پیدا نشد؛ گزارش را بررسی کنید.'


def spawn_crawl(unit, url, name):
    """Start the crawler as its own transient systemd unit (on the host)."""
    url2, name2 = parse_url(url)
    if not UNIT.fullmatch(unit) or url2 != url or name2 != name:
        raise ValueError('bad crawl request')
    if not PYTHON.exists() or not SCRIPT.is_file():
        raise FileNotFoundError(f'crawler missing: {PYTHON} / {SCRIPT}')
    out = OUT_ROOT / name
    out.mkdir(parents=True, exist_ok=True)
    subprocess.run(['systemd-run', '--unit', unit, '--collect', '--quiet',
                    '-p', 'StandardOutput=append:%s' % (out / 'run.log'),
                    '-p', 'StandardError=append:%s' % (out / 'run.log'),
                    str(PYTHON), str(SCRIPT), url, str(out)],
                   check=True, capture_output=True, timeout=15)


def stop():
    """SIGTERM the crawler. It is resumable: pages on disk are skipped next time."""
    stopped = 0
    for pid in _pids():
        try:
            hostjobs.terminate(pid, 'partsouq')
            stopped += 1
        except OSError:
            pass
    return stopped
