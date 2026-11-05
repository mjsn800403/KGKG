#!/usr/bin/env python3
"""Graphify companion layer ("xlayer"): deterministic cross-layer relationships.

Adds what Graphify 0.8.46's AST extraction does not know:
  Next.js component -> API client fn -> HTTP method+endpoint -> Django route -> view
  -> models / services, plus Django ForeignKey / OneToOne / ManyToMany relations.

Design rules
  * No LLM, no network. stdlib `ast` for Python, tree-sitter (a Graphify dependency) for JS.
  * Never edits graphify-out/graph.json. Writes graphify-out/xlayer.json (same node/link
    schema, every link carries evidence: source file + line) and xlayer-report.json.
  * Anything not statically resolvable goes to the `unresolved` list, never into the graph.
  * Confidence uses Graphify's vocabulary: EXTRACTED = read directly from source and
    resolved uniquely; INFERRED = resolved with ambiguity or by naming convention.

Usage:
  python tools/graphify_xlayer/xlayer.py build [--root .]
  python tools/graphify_xlayer/xlayer.py trace "/api/team/members/"   # full chain for one endpoint
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path('.')
OUT = 'graphify-out'
BACKEND_API = 'KG_backend/api'
FRONT = 'kg_frontend/src'
BASE_VARS = {'API_BASE', 'BACKEND_URL'}
EXCLUDE_PARTS = {'node_modules', '.next', '.venv', '__pycache__', 'migrations'}


# ----------------------------------------------------------------------------- graph index
class Index:
    def __init__(self, graph):
        self.nodes = {n['id']: n for n in graph['nodes']}
        self.by_label = defaultdict(list)      # (source_file,label) -> ids
        for n in graph['nodes']:
            self.by_label[(n.get('source_file'), n['label'])].append(n['id'])

    def find(self, file, label):
        ids = self.by_label.get((file, label), [])
        return ids[0] if ids else None

    def file_node(self, file):
        return self.find(file, Path(file).name)

    def func(self, file, name):
        return self.find(file, f'{name}()') or self.find(file, name)


class Out:
    def __init__(self):
        self.nodes, self.links, self.unresolved = {}, [], []
        self._seen = set()

    def node(self, id_, label, file, line, kind, **extra):
        if id_ not in self.nodes:
            self.nodes[id_] = {'id': id_, 'label': label, 'file_type': 'code', 'source_file': file,
                               'source_location': f'L{line}', 'kind': kind, 'layer': 'xlayer',
                               '_origin': 'xlayer', **extra}
        return id_

    def link(self, s, t, rel, conf, file, line, evidence, **extra):
        key = (s, t, rel, file, line)
        if key in self._seen or (s == t and rel not in ('foreign_key', 'one_to_one', 'many_to_many')):
            return
        self._seen.add(key)
        self.links.append({'source': s, 'target': t, 'relation': rel, 'confidence': conf,
                           'confidence_score': {'EXTRACTED': 1.0, 'INFERRED': 0.6, 'AMBIGUOUS': 0.3}[conf],
                           'source_file': file, 'source_location': f'L{line}', 'weight': 1.0,
                           'evidence': evidence, '_origin': 'xlayer', 'layer': 'xlayer', **extra})

    def miss(self, kind, file, line, detail):
        self.unresolved.append({'kind': kind, 'source_file': file, 'line': line, 'detail': detail})


def slug(s):
    return re.sub(r'[^a-z0-9]+', '_', s.lower()).strip('_')


# ----------------------------------------------------------------------------- Django side
def parse_py(path):
    try:
        return ast.parse(Path(path).read_text(encoding='utf-8'))
    except Exception:
        return None


def collect_models(idx, out):
    """Model classes + relation fields from api/models.py."""
    f = f'{BACKEND_API}/models.py'
    tree = parse_py(ROOT / f)
    models, rels = {}, []
    if not tree:
        return models
    for c in [n for n in tree.body if isinstance(n, ast.ClassDef)]:
        bases = [ast.unparse(b) for b in c.bases]
        if any(b.endswith('Model') for b in bases):
            models[c.name] = c
    for name, c in models.items():
        for st in c.body:
            if not (isinstance(st, ast.Assign) and isinstance(st.value, ast.Call)):
                continue
            fn = ast.unparse(st.value.func).split('.')[-1]
            rel = {'ForeignKey': 'foreign_key', 'OneToOneField': 'one_to_one',
                   'ManyToManyField': 'many_to_many'}.get(fn)
            if not rel:
                continue
            tgt = None
            arg = st.value.args[0] if st.value.args else next(
                (k.value for k in st.value.keywords if k.arg == 'to'), None)
            if isinstance(arg, ast.Name):
                tgt = arg.id
            elif isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                tgt = arg.value.split('.')[-1]
                if tgt == 'self':
                    tgt = name
            field = ast.unparse(st.targets[0])
            kw = {k.arg: ast.unparse(k.value) for k in st.value.keywords}
            s_id = idx.find(f, name)
            t_id = idx.find(f, tgt) if tgt in models else None
            ev = f'{name}.{field} = {fn}({ast.unparse(arg) if arg else ""})'
            if s_id and t_id:
                out.link(s_id, t_id, rel, 'EXTRACTED', f, st.lineno, ev, field=field,
                         related_name=kw.get('related_name'), on_delete=kw.get('on_delete'))
                rels.append((name, tgt, rel))
            else:
                out.miss('model_relation_unresolved', f, st.lineno,
                         f'{ev} (target {ast.unparse(arg) if arg else None!r} not a model class in api/models.py)')
    return models


def import_map(tree, file):
    """local name -> ('module', repo_file) or ('symbol', repo_file, name)"""
    m = {}
    pkg = Path(file).parent
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            if n.level:
                base = pkg
                for _ in range(n.level - 1):
                    base = base.parent
                modparts = n.module.split('.') if n.module else []
                basepath = base.joinpath(*modparts)
            else:
                basepath = Path(*(n.module or '').split('.')) if n.module else Path('.')
                basepath = Path('KG_backend') / basepath
            for a in n.names:
                local = a.asname or a.name
                mod_file = Path(str(basepath / a.name) + '.py')
                pkg_init = basepath / a.name / '__init__.py'
                if (ROOT / mod_file).exists():
                    m[local] = ('module', str(mod_file))
                elif (ROOT / pkg_init).exists():
                    m[local] = ('module', str(pkg_init))
                else:
                    cand = Path(str(basepath) + '.py')
                    if not (ROOT / cand).exists():
                        cand = basepath / '__init__.py'
                    if (ROOT / cand).exists():
                        m[local] = ('symbol', str(cand), a.name)
    return m


def view_facts(tree, fn_name, imports, models, file, idx, out, view_id):
    """Methods, model references and service calls inside one view function."""
    fdef = next((n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and n.name == fn_name), None)
    if not fdef:
        return {'methods': [], 'models': []}
    methods, how, seen = set(), None, set()   # methods = exhaustive (decorators); seen = literals compared with request.method
    for d in fdef.decorator_list:
        t = ast.unparse(d)
        if 'require_POST' in t:
            methods.add('POST'); how = 'decorator'
        elif 'require_GET' in t:
            methods.add('GET'); how = 'decorator'
        elif 'require_http_methods' in t or 'require_safe' in t:
            methods |= set(re.findall(r"['\"]([A-Z]+)['\"]", t)); how = 'decorator'
    mref = {}
    for n in ast.walk(fdef):
        if isinstance(n, ast.Compare) and 'request.method' in ast.unparse(n.left):
            for c in n.comparators:
                seen |= set(re.findall(r"['\"]([A-Z]{3,7})['\"]", ast.unparse(c)))
        if isinstance(n, ast.Name) and n.id in models and n.id not in mref:
            mref[n.id] = n.lineno
        if isinstance(n, ast.Call):
            f = n.func
            tgt_file = tgt_name = None
            if isinstance(f, ast.Name) and f.id in imports and imports[f.id][0] == 'symbol':
                tgt_file, tgt_name = imports[f.id][1], imports[f.id][2]
            elif isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) \
                    and f.value.id in imports and imports[f.value.id][0] == 'module':
                tgt_file, tgt_name = imports[f.value.id][1], f.attr
            if tgt_file:
                t_id = idx.func(tgt_file, tgt_name)
                if t_id and tgt_name not in models:
                    out.link(view_id, t_id, 'calls_service', 'EXTRACTED', file, n.lineno,
                             f'{ast.unparse(f)}() resolved via import to {tgt_file}')
    mfile = f'{BACKEND_API}/models.py'
    for name, line in mref.items():
        t = idx.find(mfile, name)
        if t:
            out.link(view_id, t, 'references_model', 'EXTRACTED', file, line,
                     f'name `{name}` used in {fn_name}() (static reference)')
    return {'methods': sorted(methods), 'how': how, 'seen': sorted(seen), 'models': sorted(mref)}


def seg_norm(pat):
    pat = pat.strip('/')
    segs = pat.split('/') if pat else []
    return ['*' if s.startswith('<') else s for s in segs], segs


def collect_routes(idx, out, models):
    routes = []
    f = f'{BACKEND_API}/urls.py'
    tree = parse_py(ROOT / f)
    if not tree:
        return routes
    imports = import_map(tree, f)
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ('path', 're_path')):
            continue
        if len(n.args) < 2 or not (isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)):
            out.miss('route_pattern_dynamic', f, n.lineno, ast.unparse(n)[:120]); continue
        pat, h = n.args[0].value, n.args[1]
        if n.func.id == 're_path':
            out.miss('route_regex_unmodelled', f, n.lineno, pat); continue
        name = next((ast.unparse(k.value) for k in n.keywords if k.arg == 'name'), None)
        if not (isinstance(h, ast.Attribute) and isinstance(h.value, ast.Name)
                and h.value.id in imports and imports[h.value.id][0] == 'module'):
            out.miss('route_handler_unresolved', f, n.lineno, f'{pat} -> {ast.unparse(h)}'); continue
        vfile, vname = imports[h.value.id][1], h.attr
        v_id = idx.func(vfile, vname)
        route_id = 'xl_route_' + slug('/' + pat)
        rt = out.node(route_id, '/' + pat, f, n.lineno, 'django_route', pattern=pat, route_name=name)
        if not v_id:
            out.miss('view_node_missing', f, n.lineno, f'{vfile}:{vname}'); continue
        vtree = parse_py(ROOT / vfile)
        facts = view_facts(vtree, vname, import_map(vtree, vfile), models, vfile, idx, out, v_id) if vtree else {'methods': []}
        out.nodes[route_id]['methods'] = facts.get('methods', [])
        out.nodes[route_id]['methods_evidence'] = facts.get('how')
        out.nodes[route_id]['methods_seen'] = facts.get('seen', [])
        out.link(rt, v_id, 'routes_to', 'EXTRACTED', f, n.lineno, f"path({pat!r}, {ast.unparse(h)})")
        routes.append({'id': route_id, 'pattern': pat, 'norm': seg_norm(pat)[0], 'raw': seg_norm(pat)[1],
                       'view_id': v_id, 'methods': facts.get('methods', []), 'line': n.lineno})
    return routes


# ----------------------------------------------------------------------------- JS side
def js_parsers():
    import tree_sitter_javascript as tjs
    import tree_sitter_typescript as tts
    from tree_sitter import Language, Parser
    return (Parser(Language(tjs.language())), Parser(Language(tts.language_tsx())))


def T(node, src):
    return src[node.start_byte:node.end_byte].decode('utf8', 'replace')


def walk(node):
    yield node
    for c in node.children:
        yield from walk(c)


def template_parts(node, src):
    """-> list of ('lit', text) | ('sub', expr_node)"""
    parts = []
    for c in node.children:
        if c.type == 'string_fragment':
            parts.append(('lit', T(c, src)))
        elif c.type == 'template_substitution':
            expr = next((x for x in c.children if x.type not in ('${', '}')), None)
            parts.append(('sub', expr))
    return parts


def resolve_url(arg, src, wrapper_params=()):
    """First argument of fetch()/wrapper -> ('static', normalized_path) | ('dynamic', reason)."""
    if arg is None:
        return ('dynamic', 'no argument')
    if arg.type == 'string':
        s = T(arg, src)[1:-1]
        return ('static', s.split('?')[0])
    if arg.type != 'template_string':
        return ('dynamic', f'non-literal URL expression `{T(arg, src)[:60]}`')
    parts = template_parts(arg, src)
    if parts and parts[0][0] == 'sub' and parts[0][1] is not None and T(parts[0][1], src) in BASE_VARS:
        parts = parts[1:]
    elif parts and parts[0][0] == 'sub' and parts[0][1] is not None and T(parts[0][1], src) in wrapper_params:
        return ('wrapper_param', None)
    elif not (parts and parts[0][0] == 'lit' and parts[0][1].startswith('/')):
        return ('dynamic', f'URL does not start with API base or "/" : `{T(arg, src)[:60]}`')
    if parts and parts[0][0] == 'sub' and T(parts[0][1], src) in wrapper_params and len(parts) == 1:
        return ('wrapper_param', None)
    path = ''
    for kind, v in parts:
        if kind == 'lit':
            path += v
            if '?' in v:
                break
        else:
            t = T(v, src) if v is not None else ''
            if '?' in t and ('`?' in t or "'?" in t or t.startswith('`')):
                break                      # ${cond ? `?x=..` : ''} query-string suffix
            path += '<param>'
    path = path.split('?')[0]
    if not path.startswith('/'):
        return ('dynamic', f'could not normalise `{T(arg, src)[:60]}`')
    return ('static', path)


def fetch_method(opts, src, default_from_call=None):
    """-> (method|None, how)"""
    if opts is None:
        return (default_from_call or 'GET', 'default GET')
    if opts.type != 'object':
        return (None, 'options not an object literal')
    has_spread = False
    for c in opts.children:
        if c.type == 'pair' and T(c.children[0], src) in ('method', '"method"', "'method'"):
            v = c.children[-1]
            if v.type == 'string':
                return (T(v, src)[1:-1].upper(), 'literal')
            return (None, f'method expression `{T(v, src)[:40]}`')
        if c.type == 'spread_element':
            has_spread = True
    return ((default_from_call or ('GET' if not has_spread else None)), 'default GET' if not has_spread else 'spread options')


def top_symbols(root, src):
    """Top-level function-like symbols: (name, node, start_line). Object-literal arrow props -> 'obj.prop'."""
    out = []
    for st in root.children:
        decl = st
        if st.type == 'export_statement':
            decl = next((c for c in st.children if c.type in ('function_declaration', 'lexical_declaration',
                                                              'variable_declaration')), None)
            if decl is None:
                continue
        if decl.type == 'function_declaration':
            nm = decl.child_by_field_name('name')
            out.append((T(nm, src), decl, decl.start_point[0] + 1))
        elif decl.type in ('lexical_declaration', 'variable_declaration'):
            for vd in decl.children:
                if vd.type != 'variable_declarator':
                    continue
                nm, val = vd.child_by_field_name('name'), vd.child_by_field_name('value')
                if nm is None or val is None:
                    continue
                if val.type in ('arrow_function', 'function_expression', 'function'):
                    out.append((T(nm, src), val, vd.start_point[0] + 1))
                elif val.type == 'object':
                    for p in val.children:
                        if p.type == 'pair' and p.children[-1].type in ('arrow_function', 'function_expression'):
                            out.append((f'{T(nm, src)}.{T(p.children[0], src)}', p.children[-1], p.start_point[0] + 1))
                        elif p.type == 'method_definition':
                            out.append((f'{T(nm, src)}.{T(p.child_by_field_name("name"), src)}', p, p.start_point[0] + 1))
    return out


def params_of(fnode, src):
    p = fnode.child_by_field_name('parameters')
    names = []
    if p is not None:
        for c in p.children:
            if c.type == 'identifier':
                names.append(T(c, src))
            elif c.type in ('assignment_pattern', 'object_pattern'):
                first = c.children[0]
                names.append(T(first, src) if first.type == 'identifier' else '')
    elif fnode.child_by_field_name('parameter') is not None:
        names.append(T(fnode.child_by_field_name('parameter'), src))
    return names


def frontend_files():
    base = ROOT / FRONT
    for p in sorted(base.rglob('*')):
        if p.suffix in ('.js', '.jsx', '.ts', '.tsx') and not (EXCLUDE_PARTS & set(p.parts)) \
                and '.test.' not in p.name and 'tests' not in p.parts:
            yield p


def scan_frontend(idx, out, routes):
    js, tsx = js_parsers()
    calls = []                       # raw endpoint call records
    sym_nodes = {}                   # (file, symbol) -> node id
    file_syms = {}                   # file -> set of exported client symbols
    parsed = {}
    for p in frontend_files():
        rel = str(p.relative_to(ROOT))
        src = p.read_bytes()
        tree = (tsx if p.suffix in ('.ts', '.tsx') else js).parse(src)
        parsed[rel] = (tree, src)
        syms = top_symbols(tree.root_node, src)
        # pass 1: wrapper functions (take URL param, fetch(`${BASE}${param}`))
        wrappers = {}
        for name, fn, line in syms:
            if '.' in name:
                continue
            ps = params_of(fn, src)
            for n in walk(fn):
                if n.type == 'call_expression' and T(n.child_by_field_name('function'), src) == 'fetch':
                    args = n.child_by_field_name('arguments').named_children
                    kind, _ = resolve_url(args[0] if args else None, src, wrapper_params=ps)
                    if kind == 'wrapper_param' or (args and args[0].type == 'template_string' and
                            any(k == 'sub' and v is not None and T(v, src) in ps for k, v in template_parts(args[0], src)[1:2])):
                        m, how = fetch_method(args[1] if len(args) > 1 else None, src)
                        wrappers[name] = {'method': m, 'how': how}
        # pass 2: call sites inside every top-level symbol
        for name, fn, line in syms:
            for n in walk(fn):
                if n.type != 'call_expression':
                    continue
                callee = T(n.child_by_field_name('function'), src)
                args = n.child_by_field_name('arguments').named_children
                ln = n.start_point[0] + 1
                if callee == 'fetch' and name not in wrappers:
                    kind, val = resolve_url(args[0] if args else None, src)
                    m, how = fetch_method(args[1] if len(args) > 1 else None, src)
                elif callee in wrappers and callee != name:
                    kind, val = resolve_url(args[0] if args else None, src)
                    w = wrappers[callee]
                    if w['method']:            # wrapper fixes its own method (literal or default GET)
                        m, how = w['method'], f"wrapper {callee}: {w['how']}"
                    else:                      # wrapper spreads caller options -> read the call-site options object
                        m, how = fetch_method(args[1] if len(args) > 1 else None, src)
                else:
                    continue
                if kind != 'static':
                    out.miss('frontend_dynamic_endpoint', rel, ln, f'{name}: {val}'); continue
                if val.startswith('http'):
                    continue
                calls.append({'file': rel, 'symbol': name, 'line': ln, 'method': m, 'how': how, 'path': val})
        file_syms[rel] = {n for n, _, _ in syms}
    # symbol nodes
    for c in calls:
        key = (c['file'], c['symbol'])
        if key not in sym_nodes:
            label = c['symbol'] + '()' if '.' not in c['symbol'] else c['symbol']
            gid = idx.find(c['file'], c['symbol'] + '()') or idx.find(c['file'], c['symbol'])
            sym_nodes[key] = gid or out.node(f"xl_client_{slug(c['file'])}_{slug(c['symbol'])}", label, c['file'],
                                              c['line'], 'api_client_fn')
            if not gid:
                fid = idx.file_node(c['file'])
                if fid:
                    out.link(fid, sym_nodes[key], 'contains', 'EXTRACTED', c['file'], c['line'], 'top-level symbol')
    # resolve to routes
    endpoints = defaultdict(list)
    for c in calls:
        segs = [s for s in c['path'].strip('/').split('/') if s != ''] if c['path'].strip('/') else []
        wild = ['*' if '<param>' in s else s for s in segs]
        cand = []
        for r in routes:
            if len(r['norm']) != len(wild):
                continue
            ok, certain = True, True
            for cs, rs in zip(wild, r['norm']):
                if cs == '*':
                    if rs != '*':
                        certain = False
                elif rs != '*' and rs != cs:
                    ok = False; break
            if ok:
                cand.append((r, certain))
        has_wild = '*' in wild
        chosen, conf, note = None, 'EXTRACTED', ''
        if not has_wild:
            chosen = cand[0][0] if cand else None                       # Django first-match wins
        else:
            sure = [r for r, ce in cand if ce]
            chosen = sure[0] if sure else None
            others = [r['pattern'] for r, ce in cand if not ce]
            if chosen and (len(sure) > 1 or others):
                conf = 'INFERRED'
                alts = [s['pattern'] for s in sure[1:]] + others
                note = 'also possible: ' + ', '.join(alts[:3]) + (f' (+{len(alts) - 3} more)' if len(alts) > 3 else '')
        if not chosen:
            out.miss('frontend_endpoint_no_route', c['file'], c['line'],
                     f"{c['symbol']}: {c['method']} {c['path']} matches no Django route")
            continue
        if c['method'] is None:
            conf = 'INFERRED'; note = (note + ' method not statically known').strip()
        elif chosen['methods'] and c['method'] not in chosen['methods']:
            out.miss('method_mismatch', c['file'], c['line'],
                     f"{c['symbol']}: {c['method']} {c['path']} but view allows {chosen['methods']}")
        ep_id = f"xl_ep_{slug((c['method'] or 'ANY') + ' ' + chosen['pattern'])}"
        out.node(ep_id, f"{c['method'] or 'ANY'} /{chosen['pattern']}", f'{BACKEND_API}/urls.py', chosen['line'],
                 'http_endpoint', http_method=c['method'], route=chosen['id'])
        out.link(ep_id, chosen['id'], 'served_by', 'EXTRACTED', f'{BACKEND_API}/urls.py', chosen['line'],
                 f"endpoint {c['method']} /{chosen['pattern']} -> django route")
        out.link(sym_nodes[(c['file'], c['symbol'])], ep_id, 'calls_endpoint', conf, c['file'], c['line'],
                 f"{c['method']} {c['path']} ({c['how']})" + (f'; {note}' if note else ''))
        endpoints[ep_id].append(c)
    # component -> client symbol usage (named imports of modules that define client symbols)
    client_syms = {k for k in sym_nodes}
    by_name = defaultdict(list)
    for (f, s) in client_syms:
        by_name[s.split('.')[0]].append((f, s))
    for rel, (tree, src) in parsed.items():
        imported = {}
        for n in walk(tree.root_node):
            if n.type == 'import_statement':
                srcnode = n.child_by_field_name('source')
                if srcnode is None:
                    continue
                mod = T(srcnode, src)[1:-1]
                for sp in walk(n):
                    if sp.type == 'import_specifier':
                        nm = sp.child_by_field_name('name')
                        al = sp.child_by_field_name('alias')
                        imported[T(al or nm, src)] = (mod, T(nm, src))
        syms = top_symbols(tree.root_node, src)
        spans = [(fn.start_byte, fn.end_byte, name) for name, fn, _ in syms if '.' not in name]
        for n in walk(tree.root_node):
            if n.type not in ('identifier', 'member_expression'):
                continue
            if n.type == 'identifier' and n.parent.type == 'member_expression' and n.parent.child_by_field_name('object') == n:
                continue
            txt = T(n, src)
            head = txt.split('.')[0]
            if head not in imported:
                continue
            mod, orig = imported[head]
            targets = [(f, s) for (f, s) in by_name.get(orig, [])
                       if f != rel and Path(f).with_suffix('').name == Path(mod).name]
            for (f, s) in targets:
                sym = s
                if '.' in s:                       # object API: need member access `obj.prop`
                    if n.type != 'member_expression' or txt != s:
                        continue
                elif n.type != 'identifier':
                    continue
                enc = next((nm for a, b, nm in spans if a <= n.start_byte < b), None)
                src_id = (idx.find(rel, enc + '()') if enc else None) or idx.file_node(rel)
                if not src_id or n.parent.type in ('import_specifier', 'import_clause'):
                    continue
                out.link(src_id, sym_nodes[(f, sym)], 'uses_api_client', 'EXTRACTED', rel, n.start_point[0] + 1,
                         f'`{txt}` imported from {mod}' + (f' (inside {enc})' if enc else ''))
    # Next.js route handlers are themselves endpoints of the frontend server
    for rel in parsed:
        m = re.search(r'src/app/(.+)/route\.(js|ts)$', rel)
        if m:
            rid = out.node('xl_nextroute_' + slug(m.group(1)), f'Next route /{m.group(1)}', rel, 1, 'next_route')
            fid = idx.file_node(rel)
            if fid:
                out.link(rid, fid, 'implemented_in', 'EXTRACTED', rel, 1, 'app-router route.js handler')
    return calls, endpoints


# ----------------------------------------------------------------------------- build / trace
def build(root):
    global ROOT
    ROOT = Path(root).resolve()
    import os
    os.chdir(ROOT)
    graph = json.load(open(f'{OUT}/graph.json'))
    idx, out = Index(graph), Out()
    models = collect_models(idx, out)
    routes = collect_routes(idx, out, models)
    calls, endpoints = scan_frontend(idx, out, routes)
    meta = {'generator': 'tools/graphify_xlayer/xlayer.py', 'base_commit': graph.get('built_at_commit'),
            'counts': {'django_routes': len(routes), 'frontend_call_sites': len(calls),
                       'endpoints_linked': len(endpoints), 'models': len(models)}}
    doc = {'directed': bool(graph.get('directed', False)), 'multigraph': False, 'graph': {}, 'nodes': list(out.nodes.values()),
           'links': out.links, 'hyperedges': [], 'built_at_commit': graph.get('built_at_commit')}
    json.dump(doc, open(f'{OUT}/xlayer.json', 'w'), indent=1)
    rel_counts = defaultdict(int)
    for l in out.links:
        rel_counts[(l['relation'], l['confidence'])] += 1
    json.dump({**meta, 'link_counts': {f'{r}/{c}': n for (r, c), n in sorted(rel_counts.items())},
               'unresolved': out.unresolved}, open(f'{OUT}/xlayer-report.json', 'w'), indent=1, ensure_ascii=False)
    print(json.dumps({**meta, 'new_nodes': len(out.nodes), 'new_links': len(out.links),
                      'unresolved': len(out.unresolved)}))
    return 0


def trace(pattern):
    g = json.load(open(f'{OUT}/graph.json'))
    x = json.load(open(f'{OUT}/xlayer.json'))
    N = {n['id']: n for n in g['nodes'] + x['nodes']}
    L = x['links']
    eps = [n for n in x['nodes'] if n['kind'] == 'http_endpoint' and pattern.strip('/') in n['label']]
    if not eps:
        print('no endpoint matches', pattern); return 1
    for ep in eps:
        print(f"\n== {ep['label']}")
        for l in L:
            if l['target'] == ep['id'] and l['relation'] == 'calls_endpoint':
                s = N[l['source']]
                print(f"  client  {s['label']:<28} {l['source_file']}:{l['source_location']}  [{l['confidence']}] {l['evidence']}")
                for u in L:
                    if u['target'] == l['source'] and u['relation'] == 'uses_api_client':
                        print(f"    <- used by {N[u['source']]['label']:<26} {u['source_file']}:{u['source_location']}")
        for l in L:
            if l['source'] == ep['id'] and l['relation'] == 'served_by':
                r = l['target']
                for v in L:
                    if v['source'] == r and v['relation'] == 'routes_to':
                        vn = N[v['target']]
                        print(f"  route   {N[r]['label']}  methods={N[r].get('methods') or '?'}  -> view {vn['label']} {vn['source_file']}:{vn['source_location']}")
                        for m in L:
                            if m['source'] == v['target'] and m['relation'] in ('references_model', 'calls_service'):
                                t = N[m['target']]
                                print(f"    {m['relation']:<17} {t['label']:<26} {t['source_file']}:{t['source_location']}  (ref line {m['source_location']})")
                                if m['relation'] == 'calls_service':
                                    for m2 in L:
                                        if m2['source'] == m['target'] and m2['relation'] == 'references_model':
                                            print(f"       └ model {N[m2['target']]['label']}")
    return 0


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest='cmd', required=True)
    b = sp.add_parser('build'); b.add_argument('--root', default='.')
    t = sp.add_parser('trace'); t.add_argument('pattern'); t.add_argument('--root', default='.')
    a = ap.parse_args()
    if a.cmd == 'build':
        sys.exit(build(a.root))
    import os
    os.chdir(a.root)
    sys.exit(trace(a.pattern))
