#!/usr/bin/env python3
"""Turn a Playwright results.json into the E2E evidence record kgkg-promote reads.

    qa/e2e_record.py <results.json> <sha> <scope> <out-dir>

Writes <out-dir>/<sha>.env (atomically) and prints it:

    E2E_SHA=<40-hex>   E2E_AT=<UTC ISO-8601>   E2E_SCOPE=full|partial
    E2E_RESULT=pass|fail   E2E_PASSED=n   E2E_FAILED=n   E2E_FLAKY=n   E2E_SKIPPED=n

A run is `pass` only when Playwright reported at least one passing test and no
unexpected (failed) ones. A missing or unreadable results file is recorded as a
`fail`, never skipped: the record exists so that "did E2E pass on this commit?"
has an answer, and "we don't know" is not a pass. `partial` scope (a filtered
run, e.g. one spec while debugging) is recorded but kgkg-promote does not count
it as release evidence.

  qa/e2e_record.py --selftest
"""
import datetime
import json
import os
import re
import sys
import tempfile

SHA_RE = re.compile(r'^[0-9a-f]{40}$')


def summarize(results_path):
    try:
        with open(results_path, encoding='utf-8') as f:
            stats = json.load(f).get('stats') or {}
    except (OSError, ValueError):
        stats = {}
    passed = int(stats.get('expected', 0) or 0)
    failed = int(stats.get('unexpected', 0) or 0)
    flaky = int(stats.get('flaky', 0) or 0)
    skipped = int(stats.get('skipped', 0) or 0)
    result = 'pass' if passed > 0 and failed == 0 else 'fail'
    return {'E2E_RESULT': result, 'E2E_PASSED': passed, 'E2E_FAILED': failed,
            'E2E_FLAKY': flaky, 'E2E_SKIPPED': skipped}


def write_record(results_path, sha, scope, out_dir, now=None):
    if not SHA_RE.match(sha):
        raise ValueError(f'not a full commit sha: {sha!r}')
    if scope not in ('full', 'partial'):
        raise ValueError(f'scope must be full or partial, not {scope!r}')
    now = now or datetime.datetime.now(datetime.timezone.utc)
    rec = {'E2E_SHA': sha,
           'E2E_AT': now.strftime('%Y-%m-%dT%H:%M:%SZ'),
           'E2E_SCOPE': scope}
    rec.update(summarize(results_path))
    body = ''.join(f'{k}={v}\n' for k, v in rec.items())
    os.makedirs(out_dir, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=out_dir, prefix='.e2e-')
    with os.fdopen(fd, 'w') as f:
        f.write(body)
    os.replace(tmp, os.path.join(out_dir, f'{sha}.env'))
    return body


def _selftest():
    sha = 'a' * 40
    with tempfile.TemporaryDirectory() as d:
        def res(name, **stats):
            p = os.path.join(d, name)
            with open(p, 'w') as f:
                json.dump({'stats': stats}, f)
            return p
        good = res('good.json', expected=42, unexpected=0)
        cases = [
            (good, 'RESULT=pass'),
            (res('one-failed.json', expected=41, unexpected=1), 'RESULT=fail'),
            (res('all-skipped.json', expected=0, unexpected=0, skipped=42), 'RESULT=fail'),
            (os.path.join(d, 'missing.json'), 'RESULT=fail'),
        ]
        for path, want in cases:
            body = write_record(path, sha, 'full', os.path.join(d, 'out'))
            assert want in body, (path, body)
        assert open(os.path.join(d, 'out', sha + '.env')).read() == body
        for bad_sha in ('abc', 'A' * 40, sha + '; rm -rf /'):
            try:
                write_record(good, bad_sha, 'full', d)
            except ValueError:
                pass
            else:
                raise AssertionError(f'accepted sha {bad_sha!r}')
        try:
            write_record(good, sha, 'everything', d)
        except ValueError:
            pass
        else:
            raise AssertionError('accepted an unknown scope')
    print('E2E RECORD SELFTEST PASSED')


if __name__ == '__main__':
    if sys.argv[1:] == ['--selftest']:
        _selftest()
        sys.exit(0)
    if len(sys.argv) != 5:
        sys.exit(__doc__)
    print(write_record(*sys.argv[1:]), end='')
