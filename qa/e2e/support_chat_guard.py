#!/usr/bin/env python3
"""Fail unless every support-chat E2E test ran and passed (#78).

Playwright reports a skipped test as a success of sorts, and a spec that skips
itself when a prerequisite is missing would otherwise turn the whole support
chat journey into a green run that tested nothing. This reads the JSON report
and requires, for qa/e2e/tests/support-chat.spec.js, exactly as many executed
tests as the spec declares, every one with status "expected", none skipped.

    qa/e2e/support_chat_guard.py results/results.json
    qa/e2e/support_chat_guard.py --selftest
"""
import json
import pathlib
import re
import sys

SPEC = pathlib.Path(__file__).resolve().parent / 'tests' / 'support-chat.spec.js'
SPEC_NAME = SPEC.name


def declared(spec_text):
    """Number of test(...) declarations in the spec (describe blocks excluded)."""
    return len(re.findall(r'^\s*test\(', spec_text, re.M))


def outcomes(report):
    """(title, status) for every test of the support-chat spec in a Playwright JSON report."""
    out = []

    def walk(suite, in_spec):
        in_spec = in_spec or suite.get('file', '').endswith(SPEC_NAME)
        for spec in suite.get('specs', []):
            if in_spec or spec.get('file', '').endswith(SPEC_NAME):
                for t in spec.get('tests', []):
                    out.append((spec.get('title', '?'), t.get('status', '?')))
        for child in suite.get('suites', []):
            walk(child, in_spec)

    for s in report.get('suites', []):
        walk(s, False)
    return out


def check(report, want):
    errors = []
    got = outcomes(report)
    if len(got) != want:
        errors.append(f'{len(got)} support-chat tests in the report, the spec declares {want}')
    for title, status in got:
        if status != 'expected':
            errors.append(f'{status}: {title}')
    return errors


def selftest():
    def report(statuses):
        return {'suites': [{'file': SPEC_NAME, 'suites': [{'specs': [
            {'title': f't{i}', 'tests': [{'status': s}]} for i, s in enumerate(statuses)]}]}]}

    cases = [
        ('all passed', report(['expected'] * 3), 3, True),
        ('one skipped', report(['expected', 'skipped', 'expected']), 3, False),
        ('one failed', report(['expected', 'unexpected', 'expected']), 3, False),
        ('one missing', report(['expected'] * 2), 3, False),
        ('spec absent', {'suites': [{'file': 'public.spec.js', 'specs': [
            {'title': 'x', 'tests': [{'status': 'expected'}]}]}]}, 3, False),
        ('empty report', {}, 3, False),
    ]
    bad = [name for name, rep, want, ok in cases if (not check(rep, want)) != ok]
    if declared("test.describe('x', () => {\n  test('a', 1);\n  test('b', 2);\n});") != 2:
        bad.append('declared() count')
    if bad:
        print('SELFTEST FAIL:', ', '.join(bad))
        return 1
    print('support-chat guard selftest: all checks passed')
    return 0


def main(argv):
    if argv[1:] == ['--selftest']:
        return selftest()
    if len(argv) != 2:
        print(__doc__)
        return 2
    want = declared(SPEC.read_text(encoding='utf-8'))
    try:
        report = json.loads(pathlib.Path(argv[1]).read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        print(f'support-chat guard: no readable report ({exc})')
        return 1
    errors = check(report, want)
    if errors:
        print('support-chat guard FAILED:')
        for e in errors:
            print(f'  {e}')
        return 1
    print(f'support-chat guard: all {want} tests ran and passed')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
