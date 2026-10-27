#!/usr/bin/env python3
"""Watch the watcher.

The alerting engine (api/alert_rules.py, run by kgkg-alerts.timer every five
minutes) is thorough: disk, memory, container restarts, probe failures with
blip suppression, TLS expiry, login brute force, AI cost — and it pages by SMS.
Nothing, however, watched the engine. If the timer stalls, the service starts
failing every run, or Prometheus stops answering, the result is silence, and
silence is exactly what a healthy system looks like.

This closes that hole and nothing else. It deliberately does not re-implement
the engine's rules: duplicating them would double every page and halve the
trust in both. It answers one question — "is anybody still watching?" — and
pages only when the answer is no. In that case the SMS also carries the direct
service checks, because if the engine is down these are the only facts anyone
is going to get.

It shares nothing with the application: standard library only, no Django, no
ORM, no database. It reads the SMS credentials straight out of .env.prod so
there is a single source of truth, and it posts to the same provider the
application uses.

Every check is also written to a node-exporter textfile so Grafana can show
the state continuously, which gives visibility without adding noise.

    ops/observability/watchdog.py              # check, page if unwatched
    ops/observability/watchdog.py --dry-run    # check and report, never send
    ops/observability/watchdog.py --selftest   # internal consistency checks
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import pathlib
from pathlib import Path

ENV_FILE = Path(os.environ.get('KG_ENV_FILE_WATCHDOG', '/opt/KGKG/KG_backend/.env.prod'))
STATE_DIR = Path(os.environ.get('KG_WATCHDOG_STATE', '/var/lib/kgkg-watchdog'))
STATE_FILE = STATE_DIR / 'state.json'
TEXTFILE_DIR = Path(os.environ.get('KG_TEXTFILE_DIR', '/var/lib/node-exporter-textfile'))
TEXTFILE = TEXTFILE_DIR / 'kgkg_watchdog.prom'

# The alert sweep runs every 5 minutes; three missed runs is a stall, not a
# slow minute.
ALERTS_STALE_S = int(os.environ.get('KG_WATCHDOG_STALE_S', '1200'))
COOLDOWN_H = float(os.environ.get('KG_WATCHDOG_COOLDOWN_H', '6'))
PROM_URL = os.environ.get('KG_PROMETHEUS_URL', 'http://127.0.0.1:9090')
LOCAL_HEALTH = os.environ.get('KG_LOCAL_HEALTH_URL', 'http://127.0.0.1:8000/api/health/')
SMS_ENDPOINT = 'https://rest.payamak-panel.com/api/SendSMS/SendSMS'

# What the provider will actually accept, learnt the hard way: the first real
# page from this file came back Value 11. The rules are documented in
# api/portal.py and implemented in api/alert_rules.deliver, which is the path
# the application has used in production for months:
#
#   * a Persian (unicode) body is refused unless it ends with the opt-out line
#     (Value 11); an ASCII body does not need it
#   * anything that looks like a link or an @domain is refused (Value 14), and
#     a dotted number such as an IP or "75.6%" reads as one, so the dots
#     become a Persian decimal separator
#   * bodies are kept short; the provider charges per segment
SMS_BRAND = 'خدمات گستر'
SMS_OPT_OUT = 'لغو11'
SMS_MAX_BODY = 250

ALERT_UNITS = ('kgkg-alerts.timer',)

# The internal company server pulls an off-host snapshot hourly and runs
# /root/kgkg_snapshot.py to build it (doc 11 §11.6). Six hours allows for a
# few missed pulls before anyone is told something is wrong.
SNAPSHOT_STAMP = pathlib.Path(
    os.environ.get('KG_SNAPSHOT_STAMP', '/root/backup_snapshot/SNAPSHOT_AT'))
SNAPSHOT_MAX_H = float(os.environ.get('KG_WATCHDOG_SNAPSHOT_MAX_H', '6'))

FA_DIGITS = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')


def fa(value) -> str:
    """Persian digits, matching the engine's own SMS bodies."""
    return str(value).translate(FA_DIGITS)


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

def read_env(path: Path = ENV_FILE) -> dict[str, str]:
    """Parse KEY=VALUE from an env file. Tolerates comments, blanks, quotes
    and `export `, and never raises: a missing file means "no credentials",
    which is reported, not fatal."""
    out: dict[str, str] = {}
    try:
        text = path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return out
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        if line.startswith('export '):
            line = line[7:]
        key, _, value = line.partition('=')
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
            value = value[1:-1]
        out[key.strip()] = value
    return out


# ---------------------------------------------------------------------------
# Checks. Each returns (ok: bool, detail: str).
# ---------------------------------------------------------------------------

def _systemctl(*args: str) -> str:
    try:
        return subprocess.run(
            ('systemctl', *args), capture_output=True, text=True, timeout=15,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ''


def check_timer_active(unit: str) -> tuple[bool, str]:
    state = _systemctl('is-active', unit)
    return state == 'active', f'{unit} is {state or "unknown"}'


def parse_monotonic_usec(show_output: str, key: str) -> int | None:
    """Pull an integer property out of `systemctl show` output."""
    for line in show_output.splitlines():
        name, _, value = line.partition('=')
        if name == key:
            try:
                return int(value)
            except ValueError:
                return None
    return None


def check_alert_sweep_fresh(now: float | None = None,
                            show_output: str | None = None) -> tuple[bool, str]:
    """Did the sweep finish recently, and successfully?

    Read from systemd rather than from the application's own tables: if the
    sweep cannot reach the database, its tables are exactly the wrong place to
    ask whether it ran.
    """
    out = show_output if show_output is not None else _systemctl(
        'show', 'kgkg-alerts.service',
        '-p', 'ExecMainStatus', '-p', 'ExecMainExitTimestampMonotonic',
        '-p', 'NRestarts',
    )
    if not out:
        return False, 'systemd did not answer for kgkg-alerts.service'

    status = parse_monotonic_usec(out, 'ExecMainStatus')
    exited = parse_monotonic_usec(out, 'ExecMainExitTimestampMonotonic')
    if exited is None or exited == 0:
        return False, 'kgkg-alerts.service has no recorded successful run'

    uptime = now if now is not None else _monotonic_now()
    age_s = uptime - (exited / 1_000_000)
    if status not in (0, None):
        return False, f'last alert sweep exited {status} ({int(age_s)}s ago)'
    if age_s > ALERTS_STALE_S:
        return False, f'last alert sweep was {int(age_s)}s ago (limit {ALERTS_STALE_S}s)'
    return True, f'last alert sweep {int(age_s)}s ago, exit 0'


def _monotonic_now() -> float:
    """Seconds since boot, the clock systemd's *Monotonic stamps use."""
    try:
        return float(Path('/proc/uptime').read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return time.monotonic()


def check_prometheus() -> tuple[bool, str]:
    try:
        url = f'{PROM_URL}/api/v1/query?query=up'
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.load(r)
        results = data.get('data', {}).get('result', [])
        if not results:
            return False, 'Prometheus answered but knows no targets'
        down = [x['metric'].get('job', '?') for x in results if x['value'][1] == '0']
        if down:
            return True, f'Prometheus up; targets down: {",".join(sorted(set(down)))}'
        return True, f'Prometheus up, {len(results)} targets'
    except Exception as exc:                      # noqa: BLE001 - any failure is a failure
        return False, f'Prometheus unreachable: {type(exc).__name__}'


def check_url(url: str, label: str, timeout: int = 10) -> tuple[bool, str]:
    """Fetch a URL, but describe it by name.

    The detail string can end up in an SMS, and the provider rejects any body
    containing a link (code 14) — a page that is silently refused is worse
    than no page at all, so the URL never appears in the text.
    """
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status == 200, f'{label} -> {r.status}'
    except urllib.error.HTTPError as exc:
        return False, f'{label} -> {exc.code}'
    except Exception as exc:                      # noqa: BLE001
        return False, f'{label} -> {type(exc).__name__}'


def check_containers() -> tuple[bool, str]:
    """Production containers present and not unhealthy."""
    try:
        out = subprocess.run(
            ('docker', 'ps', '--filter', 'label=kgkg.env=prod',
             '--format', '{{.Names}}\t{{.Status}}'),
            capture_output=True, text=True, timeout=20,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f'docker ps failed: {type(exc).__name__}'
    if not out:
        return False, 'no production containers are running'
    bad = [line.split('\t')[0] for line in out.splitlines() if 'unhealthy' in line.lower()]
    if bad:
        return False, f'unhealthy: {",".join(bad)}'
    return True, f'{len(out.splitlines())} production container(s) healthy'


def check_backup_snapshot(now: float | None = None,
                          stamp: pathlib.Path | None = None) -> tuple[bool, str]:
    """Is the off-host snapshot still being taken?

    Reads the stamp the snapshot script writes. Not a paging check: a late
    backup wants looking at, not waking someone for. It is the silence that
    this catches — an hourly job that quietly stopped looks exactly like an
    hourly job that is fine.
    """
    path = stamp if stamp is not None else SNAPSHOT_STAMP
    try:
        age_s = (now if now is not None else time.time()) - path.stat().st_mtime
    except OSError:
        return False, 'no off-host snapshot stamp found'
    hours = age_s / 3600
    if hours > SNAPSHOT_MAX_H:
        return False, f'off-host snapshot is {hours:.1f}h old (limit {SNAPSHOT_MAX_H:.0f}h)'
    return True, f'off-host snapshot {hours:.1f}h old'


def check_failed_units(show_output: str | None = None) -> tuple[bool, str]:
    """Any systemd unit in a failed state.

    Not a paging check — the alert engine owns paging — but it is reported and
    turned into a metric, because a unit can fail silently for a long time.
    logrotate did exactly that for 14 hours on 2026-10-27, which meant nginx
    logs stopped rotating on a disk at 73%.
    """
    out = show_output if show_output is not None else _systemctl(
        'list-units', '--failed', '--no-legend', '--plain', '--no-pager')
    units = [line.split()[0] for line in out.splitlines() if line.strip()]
    if not units:
        return True, 'no failed units'
    return False, 'failed: ' + ','.join(units[:5])


def check_disk(path: str = '/', critical_pct: float = 95.0) -> tuple[bool, str]:
    try:
        st = os.statvfs(path)
    except OSError as exc:
        return False, f'statvfs failed: {exc}'
    used_pct = 100.0 * (1 - st.f_bavail / st.f_blocks) if st.f_blocks else 0.0
    return used_pct < critical_pct, f'disk {used_pct:.1f}% used'


# ---------------------------------------------------------------------------
# State and cooldown
# ---------------------------------------------------------------------------

def load_state(path: Path = STATE_FILE) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def save_state(state: dict, path: Path = STATE_FILE) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
        tmp.replace(path)
    except OSError as exc:
        print(f'warning: could not persist state: {exc}', file=sys.stderr)


def due(state: dict, key: str, now: float, cooldown_h: float = COOLDOWN_H) -> bool:
    """Has this key been quiet long enough to page again?

    Without a cooldown a wedged timer would send a message every five minutes
    until someone woke up and stopped caring.
    """
    last = state.get('sent', {}).get(key)
    if not isinstance(last, (int, float)):
        return True
    return (now - last) >= cooldown_h * 3600


def mark_sent(state: dict, key: str, now: float) -> None:
    state.setdefault('sent', {})[key] = now


# ---------------------------------------------------------------------------
# Paging
# ---------------------------------------------------------------------------

def phones(env: dict[str, str]) -> list[str]:
    raw = env.get('KG_ALERT_PHONES') or os.environ.get('KG_ALERT_PHONES', '')
    return [p.strip() for p in raw.split(',') if p.strip()]


def sms_body(message: str) -> str:
    """Wrap a message in the envelope the provider requires.

    Mirrors api/alert_rules.deliver deliberately: brand line, the message with
    dotted numbers and @ defused, then the opt-out line. Without the opt-out
    line a Persian body is simply refused, and a refused page is indis-
    tinguishable from no page at all.
    """
    import re
    body = re.sub(r'(\d)\.(?=\d)', '\\1٫', message[:SMS_MAX_BODY]).replace('@', ' at ')
    return f'{SMS_BRAND}\n{body}\n{SMS_OPT_OUT}'


def send_sms(env: dict[str, str], phone: str, text: str) -> tuple[bool, str]:
    """Post to the same provider the application uses.

    The provider rejects bodies containing links (code 14), so messages here
    are plain prose. RetStatus only says the request parsed; the outcome is in
    Value, which is a long record id on success.
    """
    user, key, sender = (env.get('SMS_USERNAME', ''), env.get('SMS_API_KEY', ''),
                         env.get('SMS_FROM', ''))
    if not (user and key and sender):
        return False, 'sms_not_configured'
    payload = json.dumps({
        'username': user, 'password': key, 'to': phone, 'from': sender,
        'text': sms_body(text), 'isFlash': False,
    }).encode()
    req = urllib.request.Request(
        SMS_ENDPOINT, data=payload, headers={'Content-Type': 'application/json'},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode())
    except Exception as exc:                      # noqa: BLE001
        return False, f'transport_error:{type(exc).__name__}'
    value = str(result.get('Value', '')).strip().split(',')[0]
    try:
        if int(value) > 1000:
            return True, value
    except ValueError:
        pass
    return False, f'provider_code:{value or "?"}'


# ---------------------------------------------------------------------------
# Exposition
# ---------------------------------------------------------------------------

def write_textfile(checks: list[tuple[str, bool, str]], watched: bool,
                   path: Path = TEXTFILE) -> None:
    """node-exporter textfile collector output. Written atomically, because the
    collector may read the file while this writes it."""
    lines = [
        '# HELP kgkg_watchdog_check Watchdog check result (1 = ok).',
        '# TYPE kgkg_watchdog_check gauge',
    ]
    for name, ok, _detail in checks:
        lines.append(f'kgkg_watchdog_check{{check="{name}"}} {1 if ok else 0}')
    lines += [
        '# HELP kgkg_watchdog_alerting_healthy 1 when the alerting engine is demonstrably alive.',
        '# TYPE kgkg_watchdog_alerting_healthy gauge',
        f'kgkg_watchdog_alerting_healthy {1 if watched else 0}',
        '# HELP kgkg_watchdog_last_run_timestamp_seconds Unix time of the last watchdog run.',
        '# TYPE kgkg_watchdog_last_run_timestamp_seconds gauge',
        f'kgkg_watchdog_last_run_timestamp_seconds {int(time.time())}',
    ]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix('.prom.tmp')
        tmp.write_text('\n'.join(lines) + '\n')
        tmp.replace(path)
    except OSError as exc:
        print(f'warning: could not write {path}: {exc}', file=sys.stderr)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_checks() -> list[tuple[str, bool, str]]:
    checks = []
    for unit in ALERT_UNITS:
        ok, detail = check_timer_active(unit)
        checks.append(('alerts_timer_active', ok, detail))
    checks.append(('alert_sweep_fresh', *check_alert_sweep_fresh()))
    checks.append(('prometheus', *check_prometheus()))
    checks.append(('backend_health', *check_url(LOCAL_HEALTH, 'سلامت بک‌اند')))
    checks.append(('containers', *check_containers()))
    checks.append(('disk', *check_disk()))
    checks.append(('systemd_units', *check_failed_units()))
    checks.append(('backup_snapshot', *check_backup_snapshot()))
    return checks


# These three are the paging path. If they hold, the engine is alive and owns
# every other alert; this process stays quiet.
PAGING_PATH = ('alerts_timer_active', 'alert_sweep_fresh', 'prometheus')


def scrub(detail: str) -> str:
    """Remove anything the SMS provider would read as a link.

    Details are written by this file, so they should already be clean; this is
    the belt to that braces, because the cost of getting it wrong is a page
    that the provider refuses during an outage.
    """
    out = []
    for token in str(detail).split():
        if '://' in token or token.startswith('www.'):
            continue
        if any(token.endswith(tld) or f'{tld}/' in token
               for tld in ('.com', '.ir', '.net', '.org', '.dev')):
            continue
        out.append(token)
    return ' '.join(out)


def compose_message(checks: list[tuple[str, bool, str]]) -> str:
    """Persian, link-free (the provider rejects links), and specific enough to
    act on without opening a laptop."""
    broken = [c for c in checks if c[0] in PAGING_PATH and not c[1]]
    others = [c for c in checks if c[0] not in PAGING_PATH]
    failed_others = [c for c in others if not c[1]]

    head = 'هشدار زیرساخت: سامانهٔ هشدار خودکار کار نمی‌کند.'
    reasons = '؛ '.join(fa(scrub(detail)) for _n, _ok, detail in broken)
    if failed_others:
        state = 'وضعیت سرویس‌ها: ' + '؛ '.join(
            fa(scrub(detail)) for _n, _ok, detail in failed_others)
    else:
        state = 'سایر بررسی‌ها سالم است.'
    return f'{head} علت: {reasons}. {state}'


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dry-run', action='store_true',
                    help='check and report; never send an SMS')
    ap.add_argument('--selftest', action='store_true',
                    help='run internal consistency checks and exit')
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    checks = run_checks()
    watched = all(ok for name, ok, _ in checks if name in PAGING_PATH)

    for name, ok, detail in checks:
        print(f'{"ok  " if ok else "FAIL"} {name:22} {detail}')
    print(f'alerting engine healthy: {watched}')

    write_textfile(checks, watched)

    if watched:
        print('the engine is alive and owns every other alert; staying quiet')
        return 0

    message = compose_message(checks)
    print(f'\npaging: {message}')
    if args.dry_run:
        print('(dry run: nothing sent)')
        return 1

    env = read_env()
    now = time.time()
    state = load_state()
    key = 'alerting_down'
    if not due(state, key, now):
        print('within cooldown; not sending again')
        return 1

    targets = phones(env)
    if not targets:
        print('no KG_ALERT_PHONES configured — cannot page', file=sys.stderr)
        return 2

    sent_any = False
    for phone in targets:
        ok, info = send_sms(env, phone, message)
        print(f'sms {phone}: {"sent " + info if ok else "FAILED " + info}')
        sent_any = sent_any or ok
    if sent_any:
        mark_sent(state, key, now)
        save_state(state)
    return 1


def selftest() -> int:
    """Checks that can be made without a live system, so a packaging mistake
    shows up here rather than during an outage."""
    failures = []

    def expect(label, got, want):
        if got != want:
            failures.append(f'{label}: got {got!r}, want {want!r}')

    expect('fa', fa('123'), '۱۲۳')

    show = ('NRestarts=0\n'
            'ExecMainExitTimestampMonotonic=1000000000\n'
            'ExecMainStatus=0\n')
    ok, detail = check_alert_sweep_fresh(now=1100.0, show_output=show)
    expect('fresh sweep ok', ok, True)
    ok, _ = check_alert_sweep_fresh(now=1000.0 + ALERTS_STALE_S + 60, show_output=show)
    expect('stale sweep fails', ok, False)
    ok, _ = check_alert_sweep_fresh(
        now=1100.0, show_output=show.replace('ExecMainStatus=0', 'ExecMainStatus=1'))
    expect('failed sweep fails', ok, False)
    ok, _ = check_alert_sweep_fresh(now=1100.0, show_output='')
    expect('no systemd answer fails', ok, False)

    state = {}
    expect('first page is due', due(state, 'k', 1000.0), True)
    mark_sent(state, 'k', 1000.0)
    expect('cooldown holds', due(state, 'k', 1000.0 + 60), False)
    expect('cooldown expires', due(state, 'k', 1000.0 + COOLDOWN_H * 3600 + 1), True)

    expect('scrub drops a url', scrub('health http://127.0.0.1:8000/x -> 502'),
           'health -> 502')

    body = sms_body('disk 75.6% used; probe at a@b.com failed')
    if not body.startswith(SMS_BRAND):
        failures.append('sms body lacks the brand line')
    if not body.endswith(SMS_OPT_OUT):
        failures.append('sms body lacks the opt-out line (provider returns 11)')
    if '75.6' in body:
        failures.append('dotted number not defused (provider reads it as a link)')
    if '@' in body:
        failures.append('@ not defused (provider returns 14)')
    expect('scrub drops a hostname', scrub('probe kgtechvault.com failed'),
           'probe failed')

    msg = compose_message([
        ('alerts_timer_active', False, 'kgkg-alerts.timer is failed'),
        ('alert_sweep_fresh', True, 'fine'),
        ('prometheus', True, 'fine'),
        # A URL-bearing detail, as an older call site produced, must not reach
        # the provider.
        ('backend_health', False, 'health http://127.0.0.1:8000/api/health/ -> 502'),
    ])
    if 'kgkg-alerts.timer is failed' not in msg:
        failures.append('message omits the broken paging-path reason')
    if '۵۰۲' not in msg:
        failures.append('message omits the failing service detail')
    if '://' in msg or '.com' in msg:
        failures.append('message contains a link; the SMS provider rejects those')

    if failures:
        for f in failures:
            print(f'SELFTEST FAIL: {f}')
        return 1
    print('watchdog selftest: all checks passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
