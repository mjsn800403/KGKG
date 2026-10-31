#!/usr/bin/env python3
"""CI gate: a change has to say which tracked item it serves.

The 2026-10-30 evaluation could not verify the use of task management because
nothing connected a change to a task. Commits followed Conventional Commits and
pull requests explained themselves well, but "which change closed which item"
was answerable only from memory — so the tracker and the history were two
separate stories and neither could corroborate the other.

This refuses a pull request whose title and body reference no issue or pull
request. It is deliberately the weakest rule that still produces evidence: it
does not care which item, or that the item exists, only that the author said.
A stricter rule (the item must be open, must carry a milestone) would fail
honest changes and teach people to paste a number they do not mean.

    python3 ops/governance/check_traceability.py            # reads GITHUB_EVENT_PATH
    python3 ops/governance/check_traceability.py --event e.json

Exit 0 when the reference is there, or when there is no pull request to judge
(a push build); exit 1 when a pull request claims no tracked work.
"""
import argparse
import json
import os
import re
import sys

#: '#42', but not '#1a2b3c' (a colour), not 'abc#4', and not '## Heading'.
HASH_REF = re.compile(r'(?<![\w#])#\d+\b')
#: A full link to an issue or pull request on any GitHub host.
URL_REF = re.compile(r'https?://[^\s)]+/(?:issues|pull)/\d+\b')
#: Fenced code: quoting someone else's log is not a claim about THIS change.
FENCE = re.compile(r'```.*?```', re.DOTALL)


def references_issue(title, body):
    """Does this change name the tracked work it belongs to?"""
    text = f'{title or ""}\n{FENCE.sub("", body or "")}'
    return bool(HASH_REF.search(text) or URL_REF.search(text))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--event', default=os.environ.get('GITHUB_EVENT_PATH', ''),
                    help='GitHub event payload (default: $GITHUB_EVENT_PATH)')
    args = ap.parse_args(argv)

    try:
        with open(args.event, encoding='utf-8') as fh:
            event = json.load(fh)
    except (OSError, ValueError):
        # No payload to read: a local run or a push build. Nothing to judge,
        # and a gate that fails when it cannot see is a gate people disable.
        print('traceability: no pull-request event, nothing to check')
        return 0

    pr = event.get('pull_request')
    if not isinstance(pr, dict):
        print('traceability: not a pull-request event, nothing to check')
        return 0

    if references_issue(pr.get('title'), pr.get('body')):
        print('traceability: the pull request references tracked work')
        return 0

    print(
        'traceability: this pull request references no issue.\n'
        '\n'
        '  Add a reference to its description, e.g. "Closes #42" or "Refs #42".\n'
        '  If no issue exists yet, file one first — that is the point of the\n'
        '  rule: the tracker is meant to be where the work is decided, not a\n'
        '  record written afterwards.\n',
        file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
