"""docs/openapi.yaml must list exactly the routes in api/urls.py.

Adding or removing a route without updating the spec fails here (and so in
CI). The spec is read with a small line reader, not PyYAML (not a dependency):
docs/openapi.yaml keeps the block layout PyYAML's dumper produces - path keys
at 2 spaces under ``paths:``, HTTP methods at 4, operation keys at 6.
"""
import re
from pathlib import Path

from django.test import SimpleTestCase
from django.urls import URLPattern, URLResolver, get_resolver
from django.urls.resolvers import RegexPattern, RoutePattern

SPEC = Path(__file__).resolve().parents[2] / 'docs' / 'openapi.yaml'

# The only route deliberately left out of the spec: the api/* 404 catch-all.
EXCLUDED_REGEXES = {r'^api/(?P<rest>.*)$'}

HTTP_METHODS = ('get', 'put', 'post', 'delete', 'patch', 'options', 'head', 'trace')
_PATH_RE = re.compile(r"""^  (['"]?)(/[^'"]*)\1:\s*$""")
_METHOD_RE = re.compile(r'^    (%s):\s*$' % '|'.join(HTTP_METHODS))
_SECURITY_RE = re.compile(r'^      security:')


def normalize(path):
    """'/api/x/{id}/' and 'api/x/<int:id>/' -> '/api/x/{}/'."""
    path = re.sub(r'<[^>]+>', '{}', path)
    path = re.sub(r'\{[^}]*\}', '{}', path)
    return path if path.startswith('/') else '/' + path


def read_spec(text):
    """-> {path: {method: has_security}} from the ``paths:`` block."""
    paths, cur_path, cur_op = {}, None, None
    in_paths = False
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        if not line.startswith(' '):          # top-level key
            in_paths = line.rstrip() == 'paths:'
            cur_path = cur_op = None
            continue
        if not in_paths:
            continue
        m = _PATH_RE.match(line)
        if m:
            cur_path, cur_op = m.group(2), None
            if cur_path in paths:
                raise ValueError('duplicate path in spec: %s' % cur_path)
            paths[cur_path] = {}
            continue
        if cur_path is None:
            continue
        m = _METHOD_RE.match(line)
        if m:
            cur_op = m.group(1)
            paths[cur_path][cur_op] = False
            continue
        if re.match(r'^    \S', line):       # path-level key (parameters, ...)
            cur_op = None
            continue
        if cur_op and _SECURITY_RE.match(line):
            paths[cur_path][cur_op] = True
    return paths


def django_routes(patterns=None, prefix=''):
    """Every route string of the api urlconf (excluding EXCLUDED_REGEXES)."""
    if patterns is None:
        patterns = get_resolver('api.urls').url_patterns
    out = set()
    for p in patterns:
        if isinstance(p.pattern, RoutePattern):
            route = str(p.pattern)
        elif isinstance(p.pattern, RegexPattern):
            route = p.pattern._regex
            if isinstance(p, URLPattern) and route in EXCLUDED_REGEXES:
                continue
        else:  # pragma: no cover - unknown pattern type: surface it
            route = str(p.pattern)
        if isinstance(p, URLResolver):
            out |= django_routes(p.url_patterns, prefix + route)
        else:
            out.add(prefix + route)
    return out


def spec_drift(spec_paths, routes):
    """-> (missing_from_spec, extra_in_spec) as sorted normalized lists."""
    spec = {normalize(p) for p in spec_paths}
    real = {normalize(r) for r in routes}
    return sorted(real - spec), sorted(spec - real)


class OpenApiRoutesTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.text = SPEC.read_text(encoding='utf-8')
        cls.spec = read_spec(cls.text)

    def test_spec_header(self):
        self.assertRegex(self.text, r'(?m)^openapi: 3\.0\.3\s*$')
        self.assertRegex(self.text, r'(?m)^servers:\s*$')
        self.assertIn('url: /kg-api', self.text)

    def test_spec_paths_match_urlconf(self):
        routes = django_routes()
        self.assertGreater(len(routes), 50)
        missing, extra = spec_drift(self.spec, routes)
        self.assertEqual(
            (missing, extra), ([], []),
            'docs/openapi.yaml is out of sync with api/urls.py.\n'
            'Routed but not in the spec: %s\nIn the spec but not routed: %s' % (missing, extra))
        self.assertEqual(len(self.spec), len(routes))

    def test_every_operation_declares_security(self):
        no_ops = [p for p, ops in self.spec.items() if not ops]
        self.assertEqual(no_ops, [], 'paths without any operation')
        missing = ['%s %s' % (m.upper(), p) for p, ops in self.spec.items()
                   for m, has in ops.items() if not has]
        self.assertEqual(missing, [], 'operations without a security requirement')

    def test_catch_all_is_the_only_exclusion(self):
        regexes = [p.pattern._regex for p in get_resolver('api.urls').url_patterns
                   if isinstance(p.pattern, RegexPattern)]
        self.assertEqual(set(regexes), EXCLUDED_REGEXES)

    def test_pyyaml_agrees_when_available(self):
        try:
            import yaml
        except ImportError:
            self.skipTest('PyYAML not installed; the line reader is authoritative')
        doc = yaml.safe_load(self.text)
        self.assertEqual(set(doc['paths']), set(self.spec))
        for p, ops in doc['paths'].items():
            self.assertEqual({k for k in ops if k in HTTP_METHODS}, set(self.spec[p]), p)
            for m in self.spec[p]:
                self.assertIsInstance(ops[m]['security'], list, '%s %s' % (m, p))


class DriftDetectorTests(SimpleTestCase):
    """The helpers themselves: they must notice a synthetic drift."""

    SAMPLE = (
        'openapi: 3.0.3\n'
        'paths:\n'
        '  /api/a/:\n'
        '    get:\n'
        '      summary: a\n'
        '      security: []\n'
        "  '/api/b/{req_id}/':\n"
        '    parameters:\n'
        '    - name: req_id\n'
        '    post:\n'
        '      summary: b\n'
        '      responses: {}\n'
        'components:\n'
        '  /not/a/path/: {}\n'
    )

    def test_reader(self):
        spec = read_spec(self.SAMPLE)
        self.assertEqual(spec, {'/api/a/': {'get': True}, '/api/b/{req_id}/': {'post': False}})

    def test_normalize_matches_converters(self):
        self.assertEqual(normalize('api/b/<int:req_id>/'), normalize('/api/b/{id}/'))
        self.assertEqual(normalize(''), '/')

    def test_in_sync(self):
        self.assertEqual(spec_drift(read_spec(self.SAMPLE), {'api/a/', 'api/b/<int:x>/'}), ([], []))

    def test_detects_extra_spec_path(self):
        spec = read_spec(self.SAMPLE)
        spec['/api/ghost/'] = {'get': True}
        self.assertEqual(spec_drift(spec, {'api/a/', 'api/b/<int:x>/'}), ([], ['/api/ghost/']))

    def test_detects_unspecified_route(self):
        missing, extra = spec_drift(read_spec(self.SAMPLE),
                                    {'api/a/', 'api/b/<int:x>/', 'api/new/<str:token>/'})
        self.assertEqual((missing, extra), (['/api/new/{}/'], []))

    def test_real_urlconf_plus_synthetic_route_drifts(self):
        spec = read_spec(SPEC.read_text(encoding='utf-8'))
        routes = django_routes() | {'api/synthetic-extra/'}
        self.assertEqual(spec_drift(spec, routes)[0], ['/api/synthetic-extra/'])
