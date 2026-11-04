#!/usr/bin/env python3
"""Check the SRS traceability matrix: tests named in docs/00-srs.md exist; every FR/NFR id of the SRS is in docs/37.

Proves existence and completeness of the mapping only, not that the tests pass or cover the requirement.
    python3 ops/governance/check_srs_trace.py [--root .]
Standard library only.
"""
import argparse, io, os, re, sys

SRS, TRACE = 'docs/00-srs.md', 'docs/37-requirements-traceability.md'
SKIP = ('node_modules', '.git', '__pycache__')


def read(root, rel):
    with io.open(os.path.join(root, rel), encoding='utf-8') as f:
        return f.read()


def check(root='.'):
    srs, trace = read(root, SRS), read(root, TRACE)
    errors = []
    named = set(re.findall(r'`((?:[\w./-]+/)?(?:test_\w+|tests\w*)\.py)`', srs))
    named |= set(re.findall(r'`([\w.-]+\.spec\.js)`', srs)) | set(re.findall(r'`([\w.-]+\.test\.mjs)`', srs))
    have = set()
    for dp, dn, fs in os.walk(root):
        dn[:] = [d for d in dn if d not in SKIP]
        have.update(fs)
    for n in sorted(named):
        if os.path.basename(n) not in have:
            errors.append(f'test named in {SRS} does not exist: {n}')
    ids = set(re.findall(r'^\| ((?:N?FR)-\d+) \|', srs, re.M))
    for i in sorted(ids):
        if not re.search(rf'^\| {re.escape(i)} \|', trace, re.M):
            errors.append(f'{i} is in {SRS} but missing from {TRACE}')
    for i in sorted(set(re.findall(r'^\| ((?:N?FR)-\d+) \|', trace, re.M)) - ids):
        errors.append(f'{i} is in {TRACE} but not in {SRS}')
    return errors, len(named), len(ids)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default='.')
    errs, n, k = check(ap.parse_args(argv).root)
    for e in errs:
        print('FAIL', e)
    if errs:
        return 1
    print(f'srs trace: {k} requirements mapped, {n} named test files exist')
    return 0


if __name__ == '__main__':
    sys.exit(main())
