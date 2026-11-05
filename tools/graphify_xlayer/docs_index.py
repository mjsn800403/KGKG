#!/usr/bin/env python3
"""Deterministic, no-LLM documentation index for the Graphify companion layer.

Parses project Markdown (docs/*.md, KG_backend/ARCHITECTURE.md, CLAUDE.md): headings -> doc/section nodes;
backticked code references -> `documents` links to code nodes. Every link is INFERRED (a doc mention is
a claim by a human, not a verified relationship) and carries the doc line as evidence.
Backticked paths that no longer exist are reported as `stale_doc_refs` (useful drift signal).
Output: graphify-out/docsindex.json (graph schema, layer='docs') + docsindex-report.json
"""
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

OUT = 'graphify-out'
DOC_GLOBS = ['docs/*.md', 'KG_backend/ARCHITECTURE.md', 'CLAUDE.md', 'kg_frontend/README.md']
PATH_RE = re.compile(r'^[\w./\-\[\]]+\.(py|jsx?|tsx?|sh|mjs|sql|json|md|ya?ml)$')
SYM_RE = re.compile(r'^[A-Za-z_][\w]{4,}(\(\))?$')
ROUTE_RE = re.compile(r'^/?api/[\w/<>:\-]*$')


def slug(s):
    return re.sub(r'[^a-z0-9]+', '_', s.lower()).strip('_')


def main(root='.'):
    os.chdir(root)
    g = json.load(open(f'{OUT}/graph.json'))
    try:
        x = json.load(open(f'{OUT}/xlayer.json'))
    except FileNotFoundError:
        x = {'nodes': []}
    nodes = g['nodes'] + x['nodes']
    files = {n['source_file'] for n in nodes if n.get('source_file')}
    by_suffix = defaultdict(set)
    for f in files:
        parts = f.split('/')
        for i in range(len(parts)):
            by_suffix['/'.join(parts[i:])].add(f)
    file_node = {n['source_file']: n['id'] for n in g['nodes'] if n['label'] == Path(n['source_file'] or '').name and n.get('source_location') == 'L1'}
    sym = defaultdict(list)
    for n in g['nodes']:
        if n.get('file_type') == 'code' and n.get('source_location') != 'L1':
            sym[n['label'].rstrip('()')].append(n)
    routes = {n['label'].strip('/'): n['id'] for n in x['nodes'] if n.get('kind') == 'django_route'}

    out_nodes, out_links, stale, seen = {}, [], [], set()
    for pat in DOC_GLOBS:
        for p in sorted(Path('.').glob(pat)):
            doc = str(p)
            did = 'xl_doc_' + slug(doc)
            out_nodes[did] = {'id': did, 'label': p.name, 'file_type': 'document', 'source_file': doc,
                              'source_location': 'L1', 'kind': 'doc', 'layer': 'docs', '_origin': 'docsindex'}
            cur, incode = did, False
            for i, line in enumerate(p.read_text(encoding='utf-8').splitlines(), 1):
                if line.startswith('```'):
                    incode = not incode
                    continue
                m = re.match(r'^(#{2,3})\s+(.*)', line)
                if m and not incode:
                    cur = f'{did}_{slug(m.group(2))[:48]}'
                    out_nodes[cur] = {'id': cur, 'label': m.group(2).strip()[:90], 'file_type': 'document',
                                      'source_file': doc, 'source_location': f'L{i}', 'kind': 'doc_section',
                                      'layer': 'docs', '_origin': 'docsindex'}
                    k = (did, cur, 'contains')
                    out_links.append({'source': did, 'target': cur, 'relation': 'contains', 'confidence': 'EXTRACTED',
                                      'confidence_score': 1.0, 'source_file': doc, 'source_location': f'L{i}',
                                      'weight': 1.0, 'evidence': 'markdown heading', '_origin': 'docsindex', 'layer': 'docs'})
                    continue
                if incode:
                    continue
                for tok in re.findall(r'`([^`\n]+)`', line):
                    tok = tok.strip()
                    targets, kind = [], None
                    w = tok.split(':')[0].split()
                    t0 = w[0] if w else ''
                    if PATH_RE.match(t0) and '/' in t0 or PATH_RE.match(t0) and t0.count('.') == 1:
                        c = by_suffix.get(t0.lstrip('./')) or set()
                        if len(c) == 1:
                            targets = [file_node.get(next(iter(c)))]; kind = 'path'
                        elif not c and '/' in t0 and not t0.startswith(('http', '~', '/opt', '/root', '/var')) \
                                and not Path(t0).exists():
                            stale.append({'doc': doc, 'line': i, 'ref': t0})
                    elif ROUTE_RE.match(tok) and tok.strip('/') in routes:
                        targets = [routes[tok.strip('/')]]; kind = 'route'
                    elif SYM_RE.match(tok) and len(sym.get(tok.rstrip('()'), [])) == 1:
                        targets = [sym[tok.rstrip('()')][0]['id']]; kind = 'symbol'
                    for t in targets:
                        if not t:
                            continue
                        key = (cur, t)
                        if key in seen:
                            continue
                        seen.add(key)
                        out_links.append({'source': cur, 'target': t, 'relation': 'documents', 'confidence': 'INFERRED',
                                          'confidence_score': 0.5, 'source_file': doc, 'source_location': f'L{i}',
                                          'weight': 1.0, 'evidence': f'doc mentions `{tok}` ({kind})',
                                          '_origin': 'docsindex', 'layer': 'docs'})
    doc = {'directed': bool(g.get('directed', False)), 'multigraph': False, 'graph': {}, 'nodes': list(out_nodes.values()),
           'links': out_links, 'hyperedges': [], 'built_at_commit': g.get('built_at_commit')}
    json.dump(doc, open(f'{OUT}/docsindex.json', 'w'), indent=1)
    json.dump({'docs': len([n for n in out_nodes.values() if n['kind'] == 'doc']),
               'sections': len([n for n in out_nodes.values() if n['kind'] == 'doc_section']),
               'documents_links': len([l for l in out_links if l['relation'] == 'documents']),
               'stale_doc_refs': stale}, open(f'{OUT}/docsindex-report.json', 'w'), indent=1, ensure_ascii=False)
    print(json.dumps({'docs': len([n for n in out_nodes.values() if n['kind'] == 'doc']),
                      'sections': len([n for n in out_nodes.values() if n['kind'] == 'doc_section']),
                      'documents_links': len([l for l in out_links if l['relation'] == 'documents']),
                      'stale_doc_refs': len(stale)}))


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else '.')
