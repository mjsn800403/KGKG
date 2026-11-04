#!/usr/bin/env python3
"""Keep the Persian documentation (docs/fa/) from silently drifting from the English source.

Rule: every document listed in docs/i18n.toml has a Persian twin docs/fa/<same name> whose first
line is an HTML comment

    <!-- i18n-source: <name>.md sha256:<12 hex chars> -->

where the hash is taken over the English file's text (line endings normalised). Change the English
file and the hash no longer matches, so CI fails until the Persian twin is updated and re-stamped in
the same pull request. A stamp is a statement by the translator that the Persian text was brought
in line with that exact English revision; it is not proof, so reviewers still read the diff.

    python3 ops/governance/check_i18n.py            # check (exit 1 on drift)
    python3 ops/governance/check_i18n.py --stamp    # rewrite stamps of twins you have just updated
    python3 ops/governance/check_i18n.py --stamp fa-name.md   # stamp one twin only

Only documents listed in docs/i18n.toml are enforced, so unrelated work is never blocked; the list
grows as documents are translated. Standard library only (the governance job installs nothing).
"""
import argparse
import hashlib
import io
import os
import re
import sys

DOCS = 'docs'
LIST = 'i18n.toml'
STAMP_RE = re.compile(r'^<!-- i18n-source: (\S+) sha256:([0-9a-f]{12}) -->\s*$')


def digest(path):
    with io.open(path, encoding='utf-8', newline='') as f:
        text = f.read().replace('\r\n', '\n')
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:12]


def listed(docs_dir):
    """Names under `files = [ ... ]` in i18n.toml (no TOML library needed: one quoted name per entry)."""
    p = os.path.join(docs_dir, LIST)
    if not os.path.exists(p):
        return []
    with io.open(p, encoding='utf-8') as f:
        return re.findall(r'^\s*"([^"]+\.md)"', f.read(), re.M)


def first_line(path):
    with io.open(path, encoding='utf-8') as f:
        return f.readline().rstrip('\n')


def check(docs_dir):
    errors = []
    names = listed(docs_dir)
    for name in names:
        en = os.path.join(docs_dir, name)
        fa = os.path.join(docs_dir, 'fa', name)
        if not os.path.exists(en):
            errors.append(f'{name}: listed in {LIST} but the English file does not exist')
            continue
        if not os.path.exists(fa):
            errors.append(f'fa/{name}: missing Persian twin of {name}')
            continue
        m = STAMP_RE.match(first_line(fa))
        if not m:
            errors.append(f'fa/{name}: first line must be "<!-- i18n-source: {name} sha256:<12 hex> -->"')
        elif m.group(1) != name:
            errors.append(f'fa/{name}: stamp names {m.group(1)}, expected {name}')
        elif m.group(2) != digest(en):
            errors.append(f'fa/{name}: English source changed since the Persian text was stamped '
                          f'(stamp {m.group(2)}, source now {digest(en)}). Update the Persian text, then --stamp.')
    fa_dir = os.path.join(docs_dir, 'fa')
    if os.path.isdir(fa_dir):
        for f in sorted(os.listdir(fa_dir)):
            if f.endswith('.md') and f != 'README.md' and f not in names:
                errors.append(f'fa/{f}: Persian file not listed in {LIST} (it would never be checked)')
    return errors


def stamp(docs_dir, only=None):
    done = []
    for name in listed(docs_dir):
        if only and name != only:
            continue
        en = os.path.join(docs_dir, name)
        fa = os.path.join(docs_dir, 'fa', name)
        if not (os.path.exists(en) and os.path.exists(fa)):
            continue
        with io.open(fa, encoding='utf-8', newline='') as f:
            body = f.read()
        nl = '\r\n' if '\r\n' in body else '\n'
        lines = body.split(nl)
        head = f'<!-- i18n-source: {name} sha256:{digest(en)} -->'
        if lines and STAMP_RE.match(lines[0]):
            lines[0] = head
        else:
            lines.insert(0, head)
        with io.open(fa, 'w', encoding='utf-8', newline='') as f:
            f.write(nl.join(lines))
        done.append(name)
    return done


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--docs', default=DOCS)
    ap.add_argument('--stamp', nargs='?', const='ALL', default=None)
    a = ap.parse_args(argv)
    if a.stamp:
        for n in stamp(a.docs, None if a.stamp == 'ALL' else a.stamp):
            print(f'stamped fa/{n}')
        return 0
    errs = check(a.docs)
    for e in errs:
        print(f'FAIL {e}')
    if errs:
        return 1
    print(f'i18n: {len(listed(a.docs))} Persian twin(s) match their English source')
    return 0


if __name__ == '__main__':
    sys.exit(main())
