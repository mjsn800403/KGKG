#!/usr/bin/env python3
"""Host side of KG_backend/api/hostjobs.py (systemd unit kgkg-hostjobs).

Watches <spool>/req for JSON requests written by the backend container and
answers in <spool>/resp. Only the actions in ACTIONS exist, and each one
validates its parameters, so a compromised container can at most start or
stop the pipeline/crawler jobs it could already start from the admin panel.
"""
import json
import os
import re
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BACKEND = Path(os.environ.get('KG_BACKEND_DIR', '/opt/KGKG/KG_backend'))
SPOOL = Path(os.environ.pop('KG_HOSTJOBS_DIR', '/run/kgkg-hostjobs'))  # popped: helpers act locally
HOST_PYTHON = BACKEND / '.venv' / 'bin' / 'python'

sys.path.insert(0, str(BACKEND))
from api import hostjobs, tis_crawler  # noqa: E402  (both Django-free)

PIPELINE_UNIT = re.compile(r'kgkg-pipeline-job\d+-a\d+')
TIS_UNIT = re.compile(r'kgkg-tis-crawl-\d+')
TERMINABLE = {
    'pipeline': re.compile(r'manage\.py (run_pipeline|build_rag|build_diag)\b'),
    'tis': re.compile(r'toyota_tis\.py'),
}
ENV_VALUE = re.compile(r'[\w.\-]{0,64}')
REQ_ID = re.compile(r'[0-9a-f]{32}')


def a_procs(p):
    return hostjobs.local_processes()


def a_pipeline_launch(p):
    job, attempt = int(p['job_id']), int(p['attempt'])
    nice, weight, io = int(p['nice']), int(p['cpu_weight']), str(p['io_class'])
    if not (0 <= nice <= 19 and 1 <= weight <= 10000 and io in ('best-effort', 'idle')):
        raise ValueError('CPU plan out of range')
    env = {str(k): str(v) for k, v in (p.get('env') or {}).items()}
    for k, v in env.items():
        if k not in hostjobs.PIPELINE_ENV_KEYS or not ENV_VALUE.fullmatch(v):
            raise ValueError(f'environment {k} not allowed')
    unit = f'kgkg-pipeline-job{job}-a{attempt}'
    cmd = hostjobs.pipeline_unit_cmd(
        BACKEND, unit, {'nice': nice, 'cpu_weight': weight, 'io_class': io}, env,
        [str(HOST_PYTHON), 'manage.py', 'run_pipeline', '--job', str(job)])
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if res.returncode:
        raise RuntimeError((res.stderr or 'systemd-run failed').strip()[-300:])
    return unit


def a_unit_stop(p):
    unit = str(p['unit'])
    if not PIPELINE_UNIT.fullmatch(unit):
        raise ValueError('unit not allowed')
    return subprocess.run(['systemctl', 'stop', unit], capture_output=True, timeout=30).returncode == 0


def a_term(p):
    pid, rx = int(p['pid']), TERMINABLE[str(p['kind'])]
    cmd = dict(hostjobs.local_processes()).get(pid)
    if not cmd or not rx.search(cmd):
        raise ValueError('process not allowed')
    os.kill(pid, signal.SIGTERM)
    return True


def a_tis_start_chrome(p):
    return list(tis_crawler.start_chrome())


def a_tis_crawl_start(p):
    unit = str(p['unit'])
    if not TIS_UNIT.fullmatch(unit):
        raise ValueError('unit not allowed')
    tis_crawler.spawn_crawl(unit)
    return unit


ACTIONS = {'procs': a_procs, 'pipeline_launch': a_pipeline_launch, 'unit_stop': a_unit_stop,
           'term': a_term, 'tis_start_chrome': a_tis_start_chrome, 'tis_crawl_start': a_tis_crawl_start}


def handle(path):
    rid, action = path.stem, '?'
    try:
        req = json.loads(path.read_text())
        action = str(req.get('action'))
        result = {'ok': True, 'result': ACTIONS[action](req.get('params') or {})}
    except Exception as e:  # every failure goes back to the caller
        result = {'ok': False, 'error': f'{type(e).__name__}: {e}'}
    finally:
        path.unlink(missing_ok=True)
    tmp = SPOOL / 'resp' / f'.{rid}.tmp'
    tmp.write_text(json.dumps(result))
    tmp.rename(SPOOL / 'resp' / f'{rid}.json')
    if action != 'procs' or not result['ok']:
        print(f'{rid[:8]} {action} ok={result["ok"]}'
              + ('' if result['ok'] else f' {result["error"]}'), flush=True)


def main():
    for d in ('req', 'resp'):
        (SPOOL / d).mkdir(parents=True, exist_ok=True)
    pool, busy, last_sweep = ThreadPoolExecutor(4), set(), 0.0
    while True:
        for f in (SPOOL / 'req').glob('*.json'):
            if f.name in busy or not REQ_ID.fullmatch(f.stem):
                continue
            busy.add(f.name)
            pool.submit(handle, f).add_done_callback(lambda _, n=f.name: busy.discard(n))
        if time.monotonic() - last_sweep > 60:   # answers nobody collected
            last_sweep = time.monotonic()
            for f in (SPOOL / 'resp').iterdir():
                try:
                    if time.time() - f.stat().st_mtime > 300:
                        f.unlink()
                except OSError:
                    pass
        time.sleep(0.1)


if __name__ == '__main__':
    main()
