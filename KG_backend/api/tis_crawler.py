"""TIS crawler status and start/stop for the admin pipeline page.

The TIS crawler (``toyota_tis.py``) is not a pipeline stage and cannot be one:
it attaches over CDP to a Chrome window that a person logged into by hand
(TIS login includes an OTP), and a single vehicle takes hours. So this module
only *observes* it and starts/stops the crawler process. It never starts,
restarts or kills Chrome -- doing that would throw away the logged-in session.

Paths are env-overridable (``KG_TIS_DIR``) so the crawler can move without a
code change.
"""
import ast
import json
import os
import signal
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

TIS_DIR = Path(os.environ.get('KG_TIS_DIR', '/root/Desktop/tis_crawler'))
SCRIPT = TIS_DIR / 'toyota_tis.py'
PYTHON = TIS_DIR / '.venv' / 'bin' / 'python'
OUT_DIR = TIS_DIR / 'downloads_tis'
STATE_FILE = OUT_DIR / '_state.json'
CRAWL_LOG = OUT_DIR / 'crawl.log'
RUN_LOG = TIS_DIR / 'panel_run.log'
CDP_URL = 'http://127.0.0.1:9222/json'

# The browser must be a real, headful Chrome: the TIS login involves an OTP and
# anti-bot checks that behave differently headless. It runs on a virtual X
# display that is exposed over VNC (localhost only, reached via SSH tunnel) so
# a person can type the OTP. Same flags as tis_crawler/start_chrome.sh.
DISPLAY = os.environ.get('KG_TIS_DISPLAY', ':99')
CHROME_PROFILE = os.environ.get('KG_TIS_CHROME_PROFILE', '/root/.chrome-tis-profile')
CHROME_ARGS = [
    '--remote-debugging-port=9222', f'--user-data-dir={CHROME_PROFILE}',
    '--no-first-run', '--no-default-browser-check', '--no-sandbox',
    '--disable-background-timer-throttling',
    '--disable-backgrounding-occluded-windows',
    '--disable-renderer-backgrounding',
    '--disable-features=CalculateNativeWinOcclusion,IntensiveWakeUpThrottling',
    'https://techinfo.toyota.com/',
]

# Walking a finished vehicle's folder touches tens of thousands of files, so
# per-vehicle progress is cached; everything else is cheap and read live.
_PROGRESS_TTL = 120
_progress_cache = {'at': 0.0, 'data': None}


def _vehicles():
    """The (model, year) list, read from the script's own VEHICLES constant
    without importing it (importing would pull in its browser dependencies)."""
    import warnings
    try:
        with warnings.catch_warnings():
            # The crawler's own source has an invalid '\s' escape; parsing it
            # would otherwise log a SyntaxWarning on every status poll.
            warnings.simplefilter('ignore', SyntaxWarning)
            tree = ast.parse(SCRIPT.read_text(encoding='utf-8'))
    except (OSError, SyntaxError):
        return []
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and getattr(node.targets[0], 'id', None) == 'VEHICLES'):
            try:
                return [(str(m), str(y)) for m, y in ast.literal_eval(node.value)]
            except (ValueError, TypeError):
                return []
    return []


def _pids():
    """PIDs of running crawler processes. No shell, so pgrep cannot match a
    wrapper that merely mentions the name."""
    try:
        out = subprocess.run(['pgrep', '-f', r'toyota_tis\.py'],
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [int(p) for p in out.split() if p.isdigit() and int(p) != os.getpid()]


def status_running():
    """True while a crawler process is alive (its output is still changing)."""
    return bool(_pids())


def _chrome():
    """Is the logged-in Chrome reachable, and is any tab inside TIS?"""
    try:
        with urllib.request.urlopen(CDP_URL, timeout=2) as resp:
            tabs = json.loads(resp.read().decode('utf-8'))
    except (OSError, ValueError):
        return {'reachable': False, 'logged_in': False}
    urls = [t.get('url', '') for t in tabs if t.get('type') == 'page']
    return {'reachable': True,
            'logged_in': any('/t3Portal/' in u for u in urls)}


def _pgrep(pattern):
    try:
        out = subprocess.run(['pgrep', '-f', pattern], capture_output=True,
                             text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [int(p) for p in out.split() if p.isdigit()]


def _listening(port):
    import socket
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=1):
            return True
    except OSError:
        return False


def _display():
    """The pieces a person needs to reach the browser and type the OTP."""
    return {'xvfb': bool(_pgrep(f'Xvfb {DISPLAY}')),
            'vnc': _listening(5900),
            'novnc': _listening(6080)}


def start_chrome():
    """Bring up the headful Chrome, but ONLY when none is answering.

    Never kills or restarts an existing Chrome: that would throw away a
    session someone logged into with an OTP. Returns (ok, error)."""
    import shutil
    if _chrome()['reachable']:
        return False, 'Chrome از قبل در حال اجراست.'
    if _pgrep(CHROME_PROFILE):
        return False, ('یک Chrome با همین پروفایل در حال اجراست اما پاسخ نمی‌دهد؛ '
                       'از طریق VNC بررسی کنید.')
    chrome = shutil.which('google-chrome') or shutil.which('google-chrome-stable')
    if not chrome:
        return False, 'Chrome روی سرور نصب نیست.'
    env = dict(os.environ, DISPLAY=DISPLAY)
    quiet = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                 stderr=subprocess.DEVNULL, start_new_session=True)
    if not _pgrep(f'Xvfb {DISPLAY}'):
        subprocess.Popen(['Xvfb', DISPLAY, '-screen', '0', '1920x1080x24'], **quiet)
        time.sleep(2)
    if not _listening(5900):
        # -localhost binds loopback on BOTH IPv4 and IPv6; reached via SSH tunnel.
        subprocess.Popen(['x11vnc', '-display', DISPLAY, '-localhost', '-nopw',
                          '-forever', '-shared', '-rfbport', '5900'], **quiet)
    subprocess.Popen([chrome] + CHROME_ARGS, env=env, **quiet)
    for _ in range(20):
        time.sleep(0.5)
        if _chrome()['reachable']:
            return True, None
    return False, 'Chrome اجرا شد اما پورت اشکال‌زدایی (9222) پاسخ نداد.'


def _progress(vehicles):
    now = time.monotonic()
    cached = _progress_cache['data']
    if cached is not None and now - _progress_cache['at'] < _PROGRESS_TTL:
        return cached
    rows = []
    for model, year in vehicles:
        folder = OUT_DIR / f'{model}_{year}'
        pages = size = 0
        cats = []
        if folder.is_dir():
            cats = sorted(p.name for p in folder.iterdir() if p.is_dir())
            for root, _dirs, files in os.walk(folder):
                for f in files:
                    if f == 'content.html':
                        pages += 1
                    try:
                        size += os.path.getsize(os.path.join(root, f))
                    except OSError:
                        pass
        rows.append({'model': model, 'year': year, 'started': folder.is_dir(),
                     'pages': pages, 'size_mb': round(size / 1048576, 1),
                     'categories': cats})
    _progress_cache.update(at=now, data=rows)
    return rows


def _tail(path, lines=25):
    try:
        with open(path, 'rb') as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - 16384))
            text = fh.read().decode('utf-8', 'replace')
    except OSError:
        return ''
    return '\n'.join(text.splitlines()[-lines:])


def status():
    installed = SCRIPT.is_file()
    vehicles = _vehicles() if installed else []
    state = {}
    try:
        state = json.loads(STATE_FILE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        pass
    last_log = None
    try:
        last_log = datetime.fromtimestamp(CRAWL_LOG.stat().st_mtime,
                                          tz=timezone.utc).isoformat()
    except OSError:
        pass
    pids = _pids()
    return {
        'installed': installed,
        'dir': str(TIS_DIR),
        'running': bool(pids),
        'pids': pids,
        'chrome': _chrome(),
        'display': _display(),
        'vehicles': _progress(vehicles),
        'done_pubs': len(state.get('done_pubs') or []),
        'last_log_at': last_log,
        'log_tail': _tail(CRAWL_LOG),
    }


def start():
    """Start the crawler detached. Returns (pid, error)."""
    if not SCRIPT.is_file() or not PYTHON.exists():
        return None, 'اسکریپت خزشگر TIS روی سرور پیدا نشد.'
    if _pids():
        return None, 'خزشگر TIS در حال اجراست.'
    chrome = _chrome()
    if not chrome['reachable']:
        return None, ('Chrome در دسترس نیست. ابتدا از طریق VNC مرورگر را باز '
                      'کرده و وارد TIS شوید.')
    if not chrome['logged_in']:
        return None, 'Chrome باز است اما وارد TIS نشده است. ابتدا از طریق VNC وارد شوید.'
    log = open(RUN_LOG, 'a', encoding='utf-8')
    try:
        proc = subprocess.Popen([str(PYTHON), str(SCRIPT)], cwd=str(TIS_DIR),
                                stdin=subprocess.DEVNULL, stdout=log,
                                stderr=subprocess.STDOUT, start_new_session=True)
    finally:
        log.close()
    _progress_cache['data'] = None
    return proc.pid, None


def stop():
    """SIGTERM every crawler process. The crawler's state file makes it
    resume-safe, so the next start continues where this one stopped."""
    stopped = 0
    for pid in _pids():
        try:
            os.kill(pid, signal.SIGTERM)
            stopped += 1
        except OSError:
            pass
    return stopped
