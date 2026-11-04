#!/usr/bin/env python3
"""Generated inventory of the codebase, and a drift check against the docs.

Why this exists: a document is not current because somebody moved its
`reviewed` date. It is current when what it says matches the code. This script
extracts the facts that drift fastest (backend modules, models, management
commands, environment variables, frontend routes, systemd units, migrations,
CI jobs) straight from the source, writes them to docs/generated/inventory.md
for humans and agents to read, and enforces two content rules in CI:

1. FRESH: docs/generated/inventory.md must equal what the code produces now.
   Add a model, an env var or a command and CI fails until the inventory is
   regenerated, so the change is visible in the diff of the same pull request.
2. NO NEW DEBT: every item the inventory lists should be named in a hand-written
   reference doc (docs/*.md, not CHANGELOG, not docs/superpowers). The items that
   are not yet are recorded in docs/generated/doc-debt.json. An item missing from
   the docs AND from that file fails the build; an item that has since been
   documented but is still in the file also fails, so the debt can only shrink.

    python3 ops/governance/gen_inventory.py            # rewrite both files
    python3 ops/governance/gen_inventory.py --check    # CI: exit 1 on drift

Standard library only (the governance job installs nothing).
"""
import argparse
import ast
import json
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
BACKEND = 'KG_backend/api'
OUT_MD = 'docs/generated/inventory.md'
OUT_DEBT = 'docs/generated/doc-debt.json'
#: Not documentation of the current system: a changelog mentions a name once,
#: when it shipped, which is history, not a description.
DOC_EXCLUDE = ('CHANGELOG.md',)
DOC_EXCLUDE_DIRS = ('superpowers', 'generated')
SKIP_DIRS = {'__pycache__', 'node_modules', '.next', '.git', 'migrations'}

ENV_PY = re.compile(
    r"(?:environ(?:\.get|\.setdefault)?|getenv|_env_\w+|_flag|_int_env|_float_env)"
    r"\s*[\(\[]\s*['\"]([A-Z][A-Z0-9_]{3,})['\"]")
ENV_SH = re.compile(r'\$\{?((?:KG|RAG|METIS|DJANGO)_[A-Z0-9_]+)')
ENV_JS = re.compile(r'process\.env\.([A-Z][A-Z0-9_]{3,})')
#: Names the platform or tooling provides, not ours to document.
ENV_IGNORE = {'HOME', 'PATH', 'USER', 'PWD', 'CI', 'NODE_ENV', 'PYTHONPATH',
              'DJANGO_SETTINGS_MODULE', 'TZ', 'LANG', 'TERM', 'HOSTNAME',
              'GITHUB_SHA', 'GITHUB_OUTPUT', 'GITHUB_ENV'}


def _read(path):
    with open(os.path.join(ROOT, path), encoding='utf-8', errors='replace') as f:
        return f.read()


def _walk(sub, exts):
    base = os.path.join(ROOT, sub)
    for d, dirs, files in os.walk(base):
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS)
        for n in sorted(files):
            if n.endswith(exts):
                yield os.path.relpath(os.path.join(d, n), ROOT).replace(os.sep, '/')


def _is_test(path):
    n = os.path.basename(path)
    return n.startswith('test') or '/tests/' in path or n.endswith(('.test.js', '.test.mjs'))


def _first_line(doc):
    if not doc:
        return ''
    for line in doc.strip().splitlines():
        line = line.strip()
        if line:
            return line.rstrip('.')[:110]
    return ''


def _module_doc(path):
    try:
        return _first_line(ast.get_docstring(ast.parse(_read(path))))
    except SyntaxError:
        return ''


def backend_modules():
    rows = []
    for p in _walk(BACKEND, ('.py',)):
        if _is_test(p) or '/management/' in p or p.endswith('__init__.py'):
            continue
        rows.append((p, os.path.splitext(os.path.basename(p))[0], _module_doc(p)))
    return rows


def models():
    rows = []
    for p in _walk(BACKEND, ('.py',)):
        if os.path.basename(p) != 'models.py':
            continue
        for node in ast.parse(_read(p)).body:
            if not isinstance(node, ast.ClassDef):
                continue
            bases = [ast.unparse(b) for b in node.bases]
            if any(b.endswith('Model') or b.endswith('Mixin') for b in bases):
                abstract = False
                for sub in node.body:
                    if isinstance(sub, ast.ClassDef) and sub.name == 'Meta':
                        for a in sub.body:
                            if isinstance(a, ast.Assign) and getattr(a.targets[0], 'id', '') == 'abstract':
                                abstract = True
                if not abstract:
                    rows.append((p, node.name, _first_line(ast.get_docstring(node))))
    return rows


def commands():
    rows = []
    for p in _walk(BACKEND + '/management/commands', ('.py',)):
        name = os.path.splitext(os.path.basename(p))[0]
        if name.startswith('_') or _is_test(p):
            continue
        rows.append((p, name, _module_doc(p)))
    return rows


def env_vars():
    found = {}

    def add(name, path):
        if name in ENV_IGNORE or name.startswith('NEXT_'):
            return
        found.setdefault(name, set()).add(path)

    for p in _walk('KG_backend', ('.py',)):
        if _is_test(p):
            continue
        for m in ENV_PY.finditer(_read(p)):
            add(m.group(1), p)
    for p in list(_walk('ops', ('.py', '.sh', '.yml', '.yaml', '.service', '.timer', '.conf',
                                '.alloy', '.Dockerfile'))):
        if _is_test(p) or os.path.basename(p).startswith('test_'):
            continue
        t = _read(p)
        for m in ENV_PY.finditer(t):
            add(m.group(1), p)
        for m in ENV_SH.finditer(t):
            add(m.group(1), p)
    for p in _walk('kg_frontend/src', ('.js', '.jsx', '.mjs', '.ts', '.tsx')):
        if _is_test(p):
            continue
        for m in ENV_JS.finditer(_read(p)):
            add(m.group(1), p)
    return sorted((n, sorted(ps)) for n, ps in found.items())


def frontend_routes():
    out = []
    base = 'kg_frontend/src/app'
    for p in _walk(base, ('.js', '.jsx', '.ts', '.tsx')):
        n = os.path.basename(p)
        if n.startswith(('page.', 'route.')):
            route = os.path.dirname(p)[len(base):] or '/'
            kind = 'page' if n.startswith('page.') else 'route'
            out.append((route, kind, p))
    return sorted(out)


def units():
    return [(p, _unit_desc(p)) for p in _walk('ops', ('.service', '.timer'))]


def _unit_desc(p):
    m = re.search(r'^Description=(.+)$', _read(p), re.M)
    return m.group(1).strip()[:110] if m else ''


def migration_files():
    out = []
    base = os.path.join(ROOT, BACKEND, 'migrations')
    for n in sorted(os.listdir(base)):
        if re.match(r'\d{4}_.*\.py$', n):
            out.append(n[:-3])
    return out


def ci_jobs():
    t = _read('.github/workflows/ci.yml')
    jobs = t.split('\njobs:', 1)[-1]
    return re.findall(r'^  ([a-z][\w-]*):\s*$', jobs, re.M)


def ops_files():
    out = []
    for p in _walk('ops', ('.py', '.sh', '.yml', '.yaml', '.service', '.timer', '.conf',
                           '.alloy', '.json', '.lock', '.toml', '.mjs')):
        if _is_test(p) or 'provisioning/' in p:
            continue
        out.append(p)
    for p in _walk('ops', ('.Dockerfile',)):
        out.append(p)
    return sorted(set(out))


def doc_corpus():
    text = []
    base = os.path.join(ROOT, 'docs')
    for d, dirs, files in os.walk(base):
        rel = os.path.relpath(d, base).replace(os.sep, '/')
        if rel.split('/')[0] in DOC_EXCLUDE_DIRS:
            dirs[:] = []
            continue
        for n in sorted(files):
            if n.endswith('.md') and n not in DOC_EXCLUDE:
                with open(os.path.join(d, n), encoding='utf-8', errors='replace') as f:
                    text.append(f.read())
    return '\n'.join(text)


def _documented(name, corpus):
    return re.search(r'(?<![A-Za-z0-9_])' + re.escape(name) + r'(?![A-Za-z0-9_])', corpus) is not None


def _model_documented(name, corpus):
    low = name.lower()
    snake = re.sub(r'(?<!^)(?=[A-Z])', '_', name).lower()
    return any(_documented(x, corpus) for x in (name, 'api_' + low, 'api_' + snake))


def build():
    """Return (markdown, debt dict)."""
    corpus = doc_corpus()
    debt = {'env': [], 'models': [], 'commands': [], 'modules': [], 'units': [], 'ops_files': []}
    L = []
    w = L.append
    w('# Generated inventory\n')
    w('> GENERATED by `ops/governance/gen_inventory.py` from the source tree. **Do not edit by hand.**')
    w('> Regenerate with `python3 ops/governance/gen_inventory.py`. CI fails when this file is out of date')
    w('> (`--check`). It lists what the code contains; the reference docs (01-21) explain it.')
    w('> "Documented" means the name appears in a hand-written doc under `docs/` other than the CHANGELOG')
    w('> and `docs/superpowers/`. Items marked `no` are tracked in `doc-debt.json` and can only shrink.\n')

    mig = migration_files()
    w('## Migrations\n')
    w(f'{len(mig)} migrations; latest `{mig[-1]}`. Additive only (see `ops/deploy/check_migrations.py`).\n')

    mods = backend_modules()
    w(f'## Backend modules (`{BACKEND}`)\n')
    w('| Module | Summary (module docstring) | Documented |')
    w('|---|---|---|')
    for p, name, doc in mods:
        key = p[len(BACKEND) + 1:]
        ok = _documented(os.path.basename(p), corpus) or _documented(name, corpus)
        if not ok and '/' in key:
            # a module inside a package counts when its package is described
            ok = _documented(key.split('/')[0], corpus)
        if not ok:
            debt['modules'].append(key)
        w(f'| `{key}` | {doc or "-"} | {"yes" if ok else "no"} |')
    w('')

    ms = models()
    w('## Models\n')
    w('| Model | File | Documented |')
    w('|---|---|---|')
    for p, name, _ in ms:
        ok = _model_documented(name, corpus)
        if not ok:
            debt['models'].append(name)
        w(f'| `{name}` | `{p[len(BACKEND) + 1:]}` | {"yes" if ok else "no"} |')
    w('')

    cs = commands()
    w('## Management commands (`manage.py <name>`)\n')
    w('| Command | Summary | Documented |')
    w('|---|---|---|')
    for p, name, doc in cs:
        ok = _documented(name, corpus)
        if not ok:
            debt['commands'].append(name)
        w(f'| `{name}` | {doc or "-"} | {"yes" if ok else "no"} |')
    w('')

    ev = env_vars()
    w('## Environment variables read by the code\n')
    w('Names only; values live in `.env.prod` on the server and are never recorded here.\n')
    w('| Variable | Read in | Documented |')
    w('|---|---|---|')
    for name, paths in ev:
        ok = _documented(name, corpus)
        if not ok:
            debt['env'].append(name)
        shown = ', '.join(f'`{x}`' for x in paths[:2]) + (f' +{len(paths) - 2}' if len(paths) > 2 else '')
        w(f'| `{name}` | {shown} | {"yes" if ok else "no"} |')
    w('')

    us = units()
    w('## systemd units shipped in the repo\n')
    w('Timers and services installed on the host from `ops/`. The host also runs units that are installed by')
    w('`ops/deploy/*.sh` or by hand; compare with the server before assuming this list is complete.\n')
    w('| Unit file | Description | Documented |')
    w('|---|---|---|')
    for p, desc in us:
        ok = _documented(os.path.basename(p), corpus)
        if not ok:
            debt['units'].append(p)
        w(f'| `{p}` | {desc or "-"} | {"yes" if ok else "no"} |')
    w('')

    w('## Other files under `ops/`\n')
    w('| File | Documented |')
    w('|---|---|')
    for p in ops_files():
        if p in {u for u, _ in us}:
            continue
        ok = _documented(os.path.basename(p), corpus) or _documented(p, corpus)
        if not ok:
            debt['ops_files'].append(p)
        w(f'| `{p}` | {"yes" if ok else "no"} |')
    w('')

    fr = frontend_routes()
    w('## Frontend routes (`kg_frontend/src/app`)\n')
    w('| Path | Kind | File |')
    w('|---|---|---|')
    for route, kind, p in fr:
        w(f'| `{route}` | {kind} | `{p}` |')
    w('')

    w('## CI jobs (`.github/workflows/ci.yml`)\n')
    w(', '.join(f'`{j}`' for j in ci_jobs()) + '\n')

    for k in debt:
        debt[k] = sorted(set(debt[k]))
    return '\n'.join(L) + '\n', debt


def _dump_debt(debt):
    return json.dumps(debt, indent=1, sort_keys=True, ensure_ascii=False) + '\n'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--check', action='store_true', help='CI mode: exit 1 on drift, write nothing')
    args = ap.parse_args(argv)
    md, debt = build()
    md_path = os.path.join(ROOT, OUT_MD)
    debt_path = os.path.join(ROOT, OUT_DEBT)

    if not args.check:
        os.makedirs(os.path.dirname(md_path), exist_ok=True)
        with open(md_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(md)
        with open(debt_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(_dump_debt(debt))
        print(f'wrote {OUT_MD} and {OUT_DEBT}; undocumented: ' +
              ', '.join(f'{k}={len(v)}' for k, v in debt.items()))
        return 0

    problems = []
    try:
        current = open(md_path, encoding='utf-8', newline='').read()
    except FileNotFoundError:
        current = None
    if current != md:
        problems.append(f'{OUT_MD} is out of date. Run: python3 ops/governance/gen_inventory.py '
                        'and commit the result (git add -f for files ignored by *.md).')
    try:
        base = json.load(open(debt_path, encoding='utf-8'))
    except FileNotFoundError:
        base = {}
    for kind, items in debt.items():
        known = set(base.get(kind, []))
        for x in sorted(set(items) - known):
            problems.append(f'undocumented {kind[:-1] if kind.endswith("s") else kind}: {x} - describe it in '
                            'the matching docs/ reference (see docs/AGENTS.md "Where each kind of fact lives").')
        for x in sorted(known - set(items)):
            problems.append(f'{kind}: {x} is documented now or gone; remove it from {OUT_DEBT} '
                            '(regenerate) so the debt only shrinks.')
    if problems:
        print('Documentation drift:\n  - ' + '\n  - '.join(problems), file=sys.stderr)
        return 1
    print('inventory is current; no new undocumented items.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
