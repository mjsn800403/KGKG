#!/usr/bin/env python3
"""Build the downloadable documentation package: a reproducible snapshot of what is in Git.

GitHub stays the single source of truth. This script only copies files that are already tracked in the
repository, adds a MANIFEST.json (sha256 of every file, source commit, commit date) and a short guide,
and zips them with fixed timestamps, so the same commit always yields a byte-identical archive.

    python3 ops/governance/build_docs_package.py [--out dist] [--commit HEAD]

Included: docs/*.md (00-37, AGENTS, README, CHANGELOG), docs/fa/, docs/adr/, docs/generated/, docs/OWNERS.toml,
docs/i18n.toml, docs/openapi.yaml and the root AGENTS.md. Excluded: docs/superpowers/ (dated internal design drafts), anything
untracked, and any file that looks like it contains a secret (the build fails instead).
Standard library only.
"""
import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import zipfile

INCLUDE = ('docs/', 'AGENTS.md')
EXCLUDE = ('docs/superpowers/',)
SECRET = re.compile(
    r'-----BEGIN [A-Z ]*PRIVATE KEY-----|ghp_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16}|xox[bp]-[A-Za-z0-9-]{10,}|'
    r'(?i:(?:password|secret|api_key|token)\s*[:=]\s*["\'][A-Za-z0-9+/_\-]{20,}["\'])')


def git(*args):
    return subprocess.run(['git'] + list(args), check=True, capture_output=True, text=True,
                          encoding='utf-8').stdout


def tracked(commit):
    names = git('ls-tree', '-r', '--full-tree', '--name-only', commit).splitlines()
    out = []
    for n in names:
        if n.startswith(EXCLUDE):
            continue
        if n.startswith(INCLUDE) and n.lower().endswith(('.md', '.json', '.toml', '.yaml', '.yml')):
            out.append(n)
    return sorted(out)


def blob(commit, path):
    return subprocess.run(['git', 'show', f'{commit}:{path}'], check=True, capture_output=True).stdout


GUIDE = """KGtechvault documentation package
=================================
Source commit : {commit}
Commit date   : {date}
Files         : {count} (see MANIFEST.json for sha256 of each)

This archive is a snapshot of files tracked in https://github.com/mjsn800403/KGKG (branch `work`).
GitHub is the authoritative source; regenerate this archive with
    python3 ops/governance/build_docs_package.py --commit <sha>
Never edit files inside the archive.

START HERE
  docs/README.md                       English index (every document, with its Persian twin)
  docs/fa/README.md                    Persian index
  docs/AGENTS.md                       entry point for AI agents and new engineers
  docs/38-implementation-status-matrix.md   what is really implemented / enabled / observed in production
  docs/39-evaluation-evidence-guide.md      claims that are safe to make, per subsystem
  docs/40-documentation-access-guide.md     GitHub links and directory map

WHICH DOCUMENT FOR WHICH PURPOSE
  Requirements / SRS ............ docs/00-srs.md, docs/37-requirements-traceability.md
  Architecture and design ....... docs/02-architecture.md, docs/33-system-design.md
  AI assistant and RAG .......... docs/30-ai-assistant-deep-dive.md, docs/08-ai-assistant-rag.md, docs/17-evaluation.md
  Support and communication ..... docs/35-support-system.md, docs/22-support-chat.md
  Databases and schemas ......... docs/34-data-model-reference.md, docs/23-data-layer.md, docs/generated/schema.md
  API ........................... docs/05-api-reference.md, docs/generated/routes.md, docs/openapi.yaml
  Testing, QA, security tests ... docs/32-testing-and-qa.md, docs/12-security.md, docs/18-security-hardening.md
  CI/CD and deployment .......... docs/36-cicd-and-deployment.md, docs/11-operations-deployment.md, docs/20-runbooks.md
  Infrastructure and monitoring . docs/25-ops-inventory.md, docs/31-ops-files-reference.md
  Environment variables ......... docs/29-environment-reference.md
  Risks and decisions ........... docs/27-open-risks-and-decisions.md, docs/adr/
  Persian twins ................. docs/fa/<same file name>

Evidence tags used throughout: [C] read in code, [S] observed on the server (dated), [D] claim from
Slack/Jira/sessions, [H] historical, [U] unverified. Do not quote [D] or [U] statements as facts.
No secrets, credentials, database dumps or customer data are included.
"""


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--out', default='dist')
    ap.add_argument('--commit', default='HEAD')
    a = ap.parse_args(argv)
    commit = git('rev-parse', a.commit).strip()
    short = commit[:7]
    date = git('show', '-s', '--format=%cs', commit).strip()
    ts = tuple(int(x) for x in git('show', '-s', '--format=%cd', '--date=format:%Y-%m-%d-%H-%M-%S', commit).strip().split('-'))
    files = tracked(commit)
    entries, bad = [], []
    for p in files:
        data = blob(commit, p)
        if SECRET.search(data.decode('utf-8', 'ignore')):
            bad.append(p)
        entries.append((p, data))
    if bad:
        print('REFUSING to package: secret-like content in ' + ', '.join(bad), file=sys.stderr)
        return 1
    manifest = {'repository': 'https://github.com/mjsn800403/KGKG', 'source_commit': commit, 'commit_date': date,
                'generator': 'ops/governance/build_docs_package.py', 'files': [
                    {'path': p, 'bytes': len(d), 'sha256': hashlib.sha256(d).hexdigest()} for p, d in entries]}
    guide = GUIDE.format(commit=commit, date=date, count=len(entries)).encode('utf-8')
    os.makedirs(a.out, exist_ok=True)
    name = f'kgkg-docs-{date}-{short}.zip'
    path = os.path.join(a.out, name)
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        def add(arc, data):
            zi = zipfile.ZipInfo(arc, date_time=ts)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            z.writestr(zi, data)
        add('README-PACKAGE.txt', guide)
        add('MANIFEST.json', (json.dumps(manifest, indent=2, ensure_ascii=False) + '\n').encode('utf-8'))
        for p, d in entries:
            add(p, d)
    print(f'{path}  files={len(entries)}  commit={short}  date={date}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
