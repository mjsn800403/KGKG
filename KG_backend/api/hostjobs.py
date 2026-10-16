"""Bridge from the backend container to the host, for the few things that
must run on the host itself: launching/stopping pipeline workers as systemd
units, the TIS crawler and its Chrome/VNC session, and looking at host
processes.

Outside a container (KG_HOSTJOBS_DIR unset: host timers, management commands,
tests) every helper acts locally, exactly as before. Inside the container the
helpers drop a JSON request into the spool directory, and the host service
ops/hostjobs/hostjobs_daemon.py runs it. That service only knows a fixed list
of actions and validates every parameter, so the container never gets a host
shell. Django-free on purpose: the daemon imports this module.
"""
import json
import os
import re
import signal
import time
import uuid
from pathlib import Path

# Environment a pipeline worker may be started with (validated on the host).
PIPELINE_ENV_KEYS = frozenset({
    'HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE', 'TOKENIZERS_PARALLELISM',
    'RAG_EMBED_MODEL', 'OMP_NUM_THREADS', 'KG_PARSE_WORKERS',
})


class HostJobError(OSError):
    pass


def spool():
    return os.environ.get('KG_HOSTJOBS_DIR', '')


def enabled():
    return bool(spool())


def call(action, timeout=30, **params):
    """Run one host action through the spool and return its result."""
    rid = uuid.uuid4().hex
    req = Path(spool(), 'req')
    tmp = req / f'.{rid}.tmp'
    tmp.write_text(json.dumps({'action': action, 'params': params}))
    tmp.rename(req / f'{rid}.json')
    out = Path(spool(), 'resp', f'{rid}.json')
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if out.exists():
            data = json.loads(out.read_text())
            out.unlink(missing_ok=True)
            if not data.get('ok'):
                raise HostJobError(data.get('error') or f'host action {action} failed')
            return data.get('result')
        time.sleep(0.05)
    raise HostJobError(f'host action {action} timed out (is kgkg-hostjobs running?)')


def local_processes():
    """[(pid, cmdline)] of the processes visible here (the host, outside a container)."""
    procs = []
    try:
        names = os.listdir('/proc')
    except OSError:
        return procs
    for pid in names:
        if not pid.isdigit():
            continue
        try:
            with open(f'/proc/{pid}/cmdline', 'rb') as f:
                cmd = f.read().decode('utf-8', 'replace').replace('\x00', ' ').strip()
        except OSError:
            continue
        if cmd:
            procs.append((int(pid), cmd))
    return procs


def processes():
    """[(pid, cmdline)] of every HOST process."""
    if enabled():
        return [(int(p), str(c)) for p, c in call('procs', timeout=10)]
    return local_processes()


def pgrep(pattern):
    """Host PIDs whose command line matches ``pattern`` (like ``pgrep -f``)."""
    me = None if enabled() else os.getpid()
    rx = re.compile(pattern)
    return [pid for pid, cmd in processes() if pid != me and rx.search(cmd)]


def pid_alive(pid):
    if not pid:
        return False
    if enabled():
        return any(p == pid for p, _ in processes())
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def terminate(pid, kind):
    """SIGTERM a pipeline worker (kind='pipeline') or TIS crawler (kind='tis')."""
    if enabled():
        return bool(call('term', pid=int(pid), kind=kind))
    os.kill(pid, signal.SIGTERM)
    return True


def pipeline_unit_cmd(base, unit, plan, env_pairs, argv):
    """The systemd-run command line for a pipeline worker unit."""
    cmd = ['systemd-run', '--collect', f'--unit={unit}',
           f'--working-directory={base}',
           f'--property=Nice={plan["nice"]}',
           f'--property=IOSchedulingClass={plan["io_class"]}',
           f'--property=CPUWeight={plan["cpu_weight"]}',
           f'--property=EnvironmentFile={base}/.env.prod']
    for k, v in env_pairs.items():
        cmd.append(f'--setenv={k}={v}')
    return cmd + list(argv)
