#!/usr/bin/env python3
"""Build graphify-out/architecture.html: a self-contained, filterable module-level view.

Complements (does not replace) Graphify's native graph.html. Data comes only from
graph.json (+ xlayer.json, docsindex.json when present). Modules are plain directory groups
(evidence = file path), never invented names. No network, no external JS.
"""
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

OUT = 'graphify-out'
STRUCTURAL = {'contains', 'method', 'defines'}
TEST_RE = re.compile(r'(^|/)(tests?|__tests__)/|(^|/)test_[^/]*$|tests?\.py$|\.test\.[jt]sx?$|_test\.py$')


def module_of(f):
    p = f.split('/')
    if p[0] == 'KG_backend':
        if len(p) > 3 and p[1] == 'api' and p[2] in ('rag', 'management', 'migrations', 'reporting_assets'):
            return '/'.join(p[:3])
        return '/'.join(p[:2]) if len(p) > 2 else 'KG_backend'
    if p[0] == 'kg_frontend':
        if len(p) > 3 and p[1] == 'src':
            return '/'.join(p[:3])
        return 'kg_frontend/(config)'
    if p[0] in ('ops', 'docs', 'scripts', 'tools', 'lemon-downloader'):
        return p[0]
    return '(root scripts)'


def layer_of(m):
    if m.startswith('kg_frontend'):
        return 'frontend'
    if m.startswith('KG_backend'):
        return 'backend'
    if m == 'docs':
        return 'docs'
    return 'tooling'


def main(root='.'):
    os.chdir(root)
    g = json.load(open(f'{OUT}/graph.json'))
    layers = [g]
    for name in ('xlayer', 'docsindex'):
        try:
            layers.append(json.load(open(f'{OUT}/{name}.json')))
        except FileNotFoundError:
            pass
    nodes = {}
    for L in layers:
        for n in L['nodes']:
            nodes[n['id']] = n
    files = {}
    for n in nodes.values():
        f = n.get('source_file')
        if not f:
            continue
        e = files.setdefault(f, {'p': f, 'm': module_of(f), 't': bool(TEST_RE.search(f)), 'n': 0, 'top': []})
        if n.get('file_type') != 'rationale':
            e['n'] += 1
    deg = defaultdict(int)
    agg = defaultdict(int)            # (srcfile, dstfile, rel, conf, layer) -> count
    ex = {}
    for li, L in enumerate(layers):
        lay = 'xlayer' if li == 1 else 'docs' if li == 2 else 'ast'
        for l in L['links']:
            s, t = nodes.get(l['source']), nodes.get(l['target'])
            if not s or not t:
                continue
            deg[l['source']] += 1; deg[l['target']] += 1
            fs, ft = s.get('source_file'), t.get('source_file')
            if not fs or not ft or l['relation'] in STRUCTURAL:
                continue
            if fs == ft and l['relation'] != 'rationale_for':
                continue
            key = (fs, ft, l['relation'], l['confidence'], lay)
            agg[key] += 1
            ex.setdefault(key, f"{s['label']} → {t['label']} @ {l['source_file']}:{l['source_location']}")
    for n in nodes.values():
        f = n.get('source_file')
        if f in files and n.get('file_type') != 'rationale' and n.get('kind') != 'doc_section' \
                and n.get('source_location') != 'L1' and n.get('layer') != 'docs':
            files[f]['top'].append((deg[n['id']], n['label'], n.get('source_location', '')))
    for e in files.values():
        e['top'] = [[b, c, a] for a, b, c in sorted(e['top'], reverse=True)[:6]]
    edges = [[a, b, r, c, lay, k, ex[(a, b, r, c, lay)]] for (a, b, r, c, lay), k in agg.items()]
    # endpoint chains from the companion layer
    chains = []
    if len(layers) > 1:
        X = layers[1]
        outl = defaultdict(list)
        for l in X['links']:
            outl[l['source']].append(l)
        inl = defaultdict(list)
        for l in X['links']:
            inl[l['target']].append(l)
        for n in X['nodes']:
            if n.get('kind') != 'http_endpoint':
                continue
            clients = []
            for l in inl[n['id']]:
                if l['relation'] != 'calls_endpoint':
                    continue
                users = [[nodes[u['source']]['label'], u['source_file'], u['source_location']]
                         for u in inl[l['source']] if u['relation'] == 'uses_api_client']
                clients.append({'fn': nodes[l['source']]['label'], 'at': f"{l['source_file']}:{l['source_location']}",
                                'conf': l['confidence'], 'ev': l['evidence'], 'users': users[:6]})
            view = None
            for l in outl[n['id']]:
                if l['relation'] == 'served_by':
                    r = nodes[l['target']]
                    for v in outl[r['id']]:
                        if v['relation'] == 'routes_to':
                            vn = nodes[v['target']]
                            ms = sorted({nodes[m['target']]['label'] for m in outl[v['target']] if m['relation'] == 'references_model'})
                            sv = sorted({nodes[m['target']]['label'] for m in outl[v['target']] if m['relation'] == 'calls_service'})
                            view = {'route': r['label'], 'methods': r.get('methods') or [], 'view': vn['label'],
                                    'at': f"{vn['source_file']}:{vn['source_location']}", 'models': ms, 'services': sv[:12]}
            chains.append({'ep': n['label'], 'clients': clients, 'view': view})
    report = {}
    for name in ('xlayer-report', 'docsindex-report'):
        try:
            report[name] = json.load(open(f'{OUT}/{name}.json'))
        except FileNotFoundError:
            pass
    data = {'files': list(files.values()), 'edges': edges, 'chains': chains,
            'meta': {'commit': (g.get('built_at_commit') or '')[:8], 'nodes': len(g['nodes']), 'links': len(g['links']),
                     'xl_unresolved': (report.get('xlayer-report') or {}).get('unresolved', []),
                     'stale_docs': (report.get('docsindex-report') or {}).get('stale_doc_refs', [])}}
    html = (Path(__file__).parent / 'viewer_template.html').read_text(encoding='utf-8')
    html = html.replace('/*__DATA__*/null', json.dumps(data, ensure_ascii=False).replace('</', '<\\/'))
    Path(f'{OUT}/architecture.html').write_text(html, encoding='utf-8')
    mods = {f['m'] for f in files.values()}
    print(json.dumps({'modules': len(mods), 'files': len(files), 'edge_groups': len(edges), 'chains': len(chains),
                      'bytes': len(html)}))


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else '.')
