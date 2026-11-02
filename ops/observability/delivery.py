#!/usr/bin/env python3
"""Delivery metrics (the four DORA keys) from the deploy logs and git.

The evaluation's BI finding named delivery as an unmeasured domain. Every
deploy already leaves a log under /opt/KGKG_release/logs/ and every promote a
`deploy-*` tag, so nothing new has to be recorded — only read and defined.
Definitions live in audit-evidence/16-improvement-programme/METRIC_DEFINITIONS.md
(§Delivery); this file is their implementation.

A log is classified by what it says, never by its exit code:

  deployed    "DEPLOYED <sha> as <tag>"             reached production and held
  failed      "DEPLOY ABORTED: ... rolled back"     reached production, rolled back
  rollback    "ROLLBACK to <sha>" with no DEPLOYED  a person rolled production back
  caught      "DEPLOY FAILED" / "ABORTED" before PROMOTE   stopped by the gate or
                                                           staging: never reached users
  (ignored)   status queries, staging-only runs, reloads

Writes table `deploys` into the Grafana business snapshot (biz.sqlite), and
prints the 30-day summary as JSON. Standard library only.

    python3 ops/observability/delivery.py [--logs DIR] [--repo DIR] [--db FILE] [--days 30]
"""
import argparse
import datetime
import glob
import json
import os
import re
import sqlite3
import statistics
import subprocess
import sys

LOGS = '/opt/KGKG_release/logs'
REPO = '/opt/KGKG'
DB = '/opt/observability/bizdb/biz.sqlite'

_NAME = re.compile(r'deploy-(\d{8})-(\d{6})\.log$')
_LINE = re.compile(r'^\[(\d\d):(\d\d):(\d\d)\] (.*)$')
_DEPLOYED = re.compile(r'^DEPLOYED ([0-9a-f]{7,40}) as (deploy-\S+)')
# Stage numbers changed when the pipeline grew a step (3/4 before 4/5).
_PROMOTE = re.compile(r'^\d/\d PROMOTE \S+ -> ([0-9a-f]{7,40})')
_ROLLBACK = re.compile(r'^ROLLBACK to ([0-9a-f]{7,40})')


def parse_log(name, text):
    """One deploy log -> a record dict, or None when it is not a deploy attempt."""
    m = _NAME.search(name)
    if not m:
        return None
    day = datetime.datetime.strptime(m.group(1) + m.group(2), '%Y%m%d%H%M%S')
    start = day.replace(tzinfo=datetime.timezone.utc)
    events = []
    for raw in text.splitlines():
        lm = _LINE.match(raw)
        if not lm:
            continue
        t = start.replace(hour=int(lm.group(1)), minute=int(lm.group(2)), second=int(lm.group(3)))
        if t < start:  # the log crossed midnight
            t += datetime.timedelta(days=1)
        events.append((t, lm.group(4)))

    promoted_at = sha = None
    for t, msg in events:
        pm = _PROMOTE.match(msg)
        if pm:
            promoted_at, sha = t, pm.group(1)
        dm = _DEPLOYED.match(msg)
        if dm:
            return {'ts': t, 'sha': dm.group(1), 'outcome': 'deployed', 'restore_s': None}
    for t, msg in events:
        if msg.startswith('DEPLOY ABORTED') and 'rolled back' in msg and promoted_at:
            return {'ts': promoted_at, 'sha': sha, 'outcome': 'failed',
                    'restore_s': (t - promoted_at).total_seconds()}
    for t, msg in events:
        rm = _ROLLBACK.match(msg)
        if rm and promoted_at is None:
            return {'ts': t, 'sha': rm.group(1), 'outcome': 'rollback', 'restore_s': None}
    for t, msg in events:
        if msg.startswith(('DEPLOY FAILED', 'DEPLOY ABORTED')) and promoted_at is None:
            return {'ts': t, 'sha': None, 'outcome': 'caught', 'restore_s': None}
    return None


def attach_rollbacks(records):
    """A manual rollback fails the deploy it undid; its restore time is the
    gap between that deploy and the rollback (an upper bound: the problem may
    have been noticed later than it started)."""
    last = None
    for r in records:
        if r['outcome'] == 'deployed':
            last = r
        elif r['outcome'] == 'rollback' and last is not None:
            last['outcome'] = 'failed'
            last['restore_s'] = (r['ts'] - last['ts']).total_seconds()
            last = None
    return records


def lead_times(records, repo):
    """Median hours from commit to production for each deployed change: the
    non-merge commits between the previous production release and this one."""
    prev = None
    for r in records:
        if r['outcome'] not in ('deployed', 'failed') or not r['sha']:
            continue
        if prev:
            try:
                out = subprocess.run(
                    ['git', '-C', repo, 'log', '--no-merges', '--format=%ct',
                     f'{prev}..{r["sha"]}'],
                    capture_output=True, text=True, timeout=30, check=True).stdout.split()
            except (subprocess.SubprocessError, OSError):
                out = []
            hours = [(r['ts'].timestamp() - int(c)) / 3600 for c in out]
            hours = [h for h in hours if h >= 0]
            r['commits'] = len(hours)
            r['lead_h'] = round(statistics.median(hours), 2) if hours else None
        prev = r['sha']
    return records


def summary(records, now, days):
    """The four keys over the window. An average of nothing is None, not 0."""
    since = now - datetime.timedelta(days=days)
    win = [r for r in records if r['ts'] >= since]
    prod = [r for r in win if r['outcome'] in ('deployed', 'failed')]
    failed = [r for r in prod if r['outcome'] == 'failed']
    leads = [r['lead_h'] for r in prod if r.get('lead_h') is not None]
    restores = [r['restore_s'] for r in failed if r['restore_s'] is not None]
    return {
        'window_days': days,
        'deploys': len(prod),
        'deploys_per_week': round(len(prod) / (days / 7), 2),
        'lead_time_h_median': round(statistics.median(leads), 2) if leads else None,
        'change_failure_rate': round(len(failed) / len(prod), 3) if prod else None,
        'time_to_restore_min_median': (round(statistics.median(restores) / 60, 1)
                                       if restores else None),
        'caught_before_production': sum(1 for r in win if r['outcome'] == 'caught'),
    }


def collect(logs, repo):
    records = []
    for path in sorted(glob.glob(os.path.join(logs, 'deploy-*.log'))):
        try:
            with open(path, errors='replace') as fh:
                rec = parse_log(os.path.basename(path), fh.read())
        except OSError:
            continue
        if rec:
            records.append(rec)
    records.sort(key=lambda r: r['ts'])
    return lead_times(attach_rollbacks(records), repo)


def write(records, db):
    con = sqlite3.connect(db)
    with con:
        con.execute('DROP TABLE IF EXISTS deploys')
        con.execute('CREATE TABLE deploys (ts INTEGER, sha TEXT, outcome TEXT, '
                    'commits INTEGER, lead_h REAL, restore_s REAL)')
        con.executemany('INSERT INTO deploys VALUES (?,?,?,?,?,?)', [
            (int(r['ts'].timestamp()), r['sha'], r['outcome'], r.get('commits'),
             r.get('lead_h'), r['restore_s']) for r in records])
        con.execute('CREATE INDEX deploys_ts ON deploys(ts)')
    con.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--logs', default=LOGS)
    ap.add_argument('--repo', default=REPO)
    ap.add_argument('--db', default=DB)
    ap.add_argument('--days', type=int, default=30)
    a = ap.parse_args(argv)
    records = collect(a.logs, a.repo)
    if a.db:
        write(records, a.db)
    now = datetime.datetime.now(datetime.timezone.utc)
    print(json.dumps(summary(records, now, max(1, min(a.days, 365))), indent=1))


if __name__ == '__main__':
    sys.exit(main())
