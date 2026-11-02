#!/usr/bin/env python3
"""CI gate: every document has a named owner and a review date.

The evaluation found no formal knowledge-transfer mechanism. The content was
never the problem — docs/ holds an SRS, an architecture reference, an API
reference and six ADRs. What was missing is maintenance: ownership was assigned
by ROLE rather than to a person, nothing recorded when a document was last
confirmed correct, and nothing noticed when one rotted. The 2026-10-28 audit
found two stale sections by reading them, which is not a method that scales.

The staleness rule here is deliberately the same one the product applies to
knowledge-base articles (`KnowledgeArticle.is_stale`): never reviewed, or
reviewed longer ago than the document's own interval. The repository and the
product should not disagree about what "stale" means.

    python3 ops/governance/check_docs_freshness.py [--docs docs]

Exit 1 listing every problem, so one run tells you everything to fix.
"""
import argparse
import datetime
import os
import sys
import tomllib

REGISTRY = 'OWNERS.toml'
DEFAULT_REVIEW_DAYS = 180
#: Directories holding dated design RECORDS rather than living documentation.
#: A record of what was decided on a particular day cannot go stale, and
#: putting it on a review cycle would turn the gate into noise — which is how
#: a gate stops being read.
EXCLUDED_DIRS = ('superpowers',)


def owners_of(entry):
    """The people responsible, as a list of names.

    `owner` may be one name or several: shared ownership is the normal case on
    a small team — two people who both know a document and either of whom can
    confirm it. A blank, an empty list, or a list of blanks is not ownership.
    """
    raw = entry.get('owner') if isinstance(entry, dict) else None
    if isinstance(raw, str):
        raw = [raw]
    elif not isinstance(raw, (list, tuple)):
        raw = []
    return [str(n).strip() for n in raw if str(n).strip()]


def is_stale(reviewed, review_days, today):
    """Never reviewed, or reviewed longer ago than its own interval."""
    if reviewed is None:
        return True
    return (today - reviewed).days > review_days


def _markdown_files(docs_dir):
    """Every document the registry is expected to cover, as repo-relative
    paths with forward slashes."""
    found = []
    for root, dirs, files in os.walk(docs_dir):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
        for name in sorted(files):
            if not name.endswith('.md'):
                continue
            rel = os.path.relpath(os.path.join(root, name), docs_dir)
            found.append(rel.replace(os.sep, '/'))
    return sorted(found)


def check(docs_dir, today=None):
    """Every problem found, as human sentences. Empty list means healthy."""
    today = today or datetime.date.today()
    registry_path = os.path.join(docs_dir, REGISTRY)
    try:
        with open(registry_path, 'rb') as fh:
            registry = tomllib.load(fh)
    except FileNotFoundError:
        return [f'{docs_dir}/{REGISTRY} is missing: every document needs a '
                f'named owner and a review interval.']
    except tomllib.TOMLDecodeError as exc:
        return [f'{docs_dir}/{REGISTRY} is not valid TOML: {exc}']

    problems = []
    present = _markdown_files(docs_dir)

    for rel in present:
        if rel not in registry:
            problems.append(
                f'{rel} is not in {REGISTRY}: give it an owner and a review '
                f'interval, or delete the document.')

    for rel, entry in sorted(registry.items()):
        if rel not in present:
            problems.append(
                f'{REGISTRY} lists {rel}, which no longer exists: remove the '
                f'entry so ownership describes what is actually there.')
            continue
        owners = owners_of(entry)
        if not owners:
            problems.append(f'{rel} has no owner in {REGISTRY}: an unowned '
                            f'document is one nobody maintains.')
            continue
        days = entry.get('review_days', DEFAULT_REVIEW_DAYS)
        reviewed = entry.get('reviewed')
        if isinstance(reviewed, datetime.datetime):
            reviewed = reviewed.date()
        if is_stale(reviewed, days, today):
            last = reviewed.isoformat() if reviewed else 'never'
            # Name EVERY owner: a notice that names one of two lets each of
            # them assume the other was asked.
            problems.append(
                f'{rel} is past its review interval (last reviewed {last}, '
                f'every {days} days, owner {" and ".join(owners)}): read it, '
                f'correct it, and move the reviewed date.')
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--docs', default='docs', help='documentation directory')
    args = ap.parse_args(argv)

    problems = check(args.docs)
    if not problems:
        print(f'docs freshness: every document in {args.docs}/ is owned and in date')
        return 0
    print(f'docs freshness: {len(problems)} problem(s)\n', file=sys.stderr)
    for p in problems:
        print(f'  * {p}', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
