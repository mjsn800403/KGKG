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
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from . import hostjobs

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
        return hostjobs.pgrep(r'toyota_tis\.py')
    except OSError:
        return []


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
    # TIS allows one login per account; a second login elsewhere bounces this
    # tab to /t3Portal/resources/jsp/concurrentLoginFailure.html -- still under
    # /t3Portal/, so the path alone would wrongly read as "logged in".
    def _dead(u):
        low = u.lower()
        return any(m in low for m in ('concurrentlogin', 'loginpage', 'prelogin',
                                      'login.html', 'loginfailure'))
    tis = [u for u in urls if '/t3Portal/' in u]
    return {'reachable': True,
            'logged_in': any(not _dead(u) for u in tis),
            'session_lost': bool(tis) and all(_dead(u) for u in tis)}


# Any TIS portal URL bounces an anonymous browser to the TIS login form.
LOGIN_URL = 'https://techinfo.toyota.com/t3Portal/appmanager/t3/ti'


def open_login():
    """Put the TIS login form on screen when Chrome is not logged in.

    Opens a fresh tab on the login URL and closes the stale ones (e.g. the
    concurrent-login page). Never touches a live TIS session or a running
    crawler. Returns True when it navigated.
    """
    ch = _chrome()
    if not ch['reachable'] or ch['logged_in'] or status_running():
        return False
    base = CDP_URL.rsplit('/json', 1)[0]
    try:
        with urllib.request.urlopen(CDP_URL, timeout=2) as resp:
            old = [t['id'] for t in json.loads(resp.read().decode('utf-8'))
                   if t.get('type') == 'page']
        req = urllib.request.Request(
            base + '/json/new?' + urllib.parse.quote(LOGIN_URL, safe=':/'), method='PUT')
        urllib.request.urlopen(req, timeout=5).read()
        for tid in old:
            try:
                urllib.request.urlopen(base + '/json/close/' + tid, timeout=2).read()
            except OSError:
                pass
    except (OSError, ValueError):
        return False
    return True


def _pgrep(pattern):
    try:
        return hostjobs.pgrep(pattern)
    except OSError:
        return []


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
    if hostjobs.enabled():
        try:
            ok, err = hostjobs.call('tis_start_chrome', timeout=40)
        except OSError as e:
            return False, 'اجرای Chrome روی سرور ناموفق بود: %s' % e
        return ok, err
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
    # In the container the crawler venv's python is a link into the host's
    # /usr/bin, so only the host (spawn_crawl) can check it.
    if not SCRIPT.is_file() or not (hostjobs.enabled() or PYTHON.exists()):
        return None, 'اسکریپت خزشگر TIS روی سرور پیدا نشد.'
    if _pids():
        return None, 'خزشگر TIS در حال اجراست.'
    chrome = _chrome()
    if not chrome['reachable']:
        return None, ('Chrome در دسترس نیست. ابتدا از طریق VNC مرورگر را باز '
                      'کرده و وارد TIS شوید.')
    if chrome.get('session_lost'):
        return None, ('نشست TIS از دست رفته است (ورود هم‌زمان از جای دیگر). '
                      'از طریق VNC دوباره وارد TIS شوید و سپس شروع کنید.')
    if not chrome['logged_in']:
        return None, 'Chrome باز است اما وارد TIS نشده است. ابتدا از طریق VNC وارد شوید.'
    # Run as its own transient systemd unit: a child of gunicorn would sit in
    # kgkg-backend's cgroup and be killed by every backend restart/deploy.
    unit = 'kgkg-tis-crawl-%d' % int(time.time())
    try:
        if hostjobs.enabled():
            hostjobs.call('tis_crawl_start', unit=unit)
        else:
            spawn_crawl(unit)
    except (OSError, subprocess.SubprocessError) as e:
        return None, 'اجرای خزشگر ناموفق بود: %s' % e
    _progress_cache['data'] = None
    for _ in range(20):
        pids = _pids()
        if pids:
            return pids[0], None
        time.sleep(0.25)
    return None, 'خزشگر اجرا شد اما فرایند آن پیدا نشد؛ گزارش اجرا را بررسی کنید.'


def spawn_crawl(unit):
    """Start the crawler as its own transient systemd unit (on the host)."""
    if not PYTHON.exists():
        raise FileNotFoundError(f'crawler python missing: {PYTHON}')
    subprocess.run(['systemd-run', '--unit', unit, '--collect', '--quiet',
                    '-p', 'WorkingDirectory=%s' % TIS_DIR,
                    '-p', 'StandardOutput=append:%s' % RUN_LOG,
                    '-p', 'StandardError=append:%s' % RUN_LOG,
                    str(PYTHON), str(SCRIPT)],
                   check=True, capture_output=True, timeout=15)


def stop():
    """SIGTERM every crawler process. The crawler's state file makes it
    resume-safe, so the next start continues where this one stopped."""
    stopped = 0
    for pid in _pids():
        try:
            hostjobs.terminate(pid, 'tis')
            stopped += 1
        except OSError:
            pass
    return stopped
