"""Accuracy/regression checks for the Graphify companion layer. Run: scripts/test-graphify-xlayer.sh"""
import ast, hashlib, json, re, subprocess, unittest
from pathlib import Path

R = Path(__file__).resolve().parents[2]
OUT = R / 'graphify-out'


def load(n):
    return json.load(open(OUT / n))


class XLayer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base_hash = hashlib.sha256((OUT / 'graph.json').read_bytes()).hexdigest()
        subprocess.run(['python3', '-I', str(R / 'tools/graphify_xlayer/xlayer.py'), 'build', '--root', str(R)],
                       check=True, capture_output=True)
        cls.g, cls.x = load('graph.json'), load('xlayer.json')
        cls.nodes = {n['id']: n for n in cls.g['nodes'] + cls.x['nodes']}

    def test_never_modifies_graphify_graph(self):
        self.assertEqual(self.base_hash, hashlib.sha256((OUT / 'graph.json').read_bytes()).hexdigest())

    def test_route_count_matches_urls_py(self):
        tree = ast.parse((R / 'KG_backend/api/urls.py').read_text())
        n = sum(1 for c in ast.walk(tree) if isinstance(c, ast.Call) and getattr(c.func, 'id', '') == 'path')
        got = len([m for m in self.x['nodes'] if m['kind'] == 'django_route'])
        self.assertEqual(n, got)

    def test_every_foreign_key_line_has_an_edge(self):
        src = (R / 'KG_backend/api/models.py').read_text()
        want = len(re.findall(r'=\s*models\.(ForeignKey|OneToOneField|ManyToManyField)\(', src))
        got = len([l for l in self.x['links'] if l['relation'] in ('foreign_key', 'one_to_one', 'many_to_many')])
        self.assertEqual(want, got)

    def test_every_link_has_evidence_location_and_valid_confidence(self):
        for l in self.x['links']:
            self.assertIn(l['confidence'], ('EXTRACTED', 'INFERRED', 'AMBIGUOUS'))
            self.assertTrue(l['evidence'] and l['source_file'] and re.match(r'^L\d+$', l['source_location']), l)
            self.assertIn(l['source'], self.nodes); self.assertIn(l['target'], self.nodes)

    def test_evidence_lines_exist_in_source(self):
        for l in self.x['links']:
            f = R / l['source_file']
            if f.exists() and l['relation'] in ('calls_endpoint', 'references_model', 'foreign_key', 'routes_to'):
                n = int(l['source_location'][1:])
                self.assertLessEqual(n, len(f.read_text().splitlines()), l)

    def test_known_chain_component_to_model(self):
        got = {(self.nodes[l['source']]['label'], self.nodes[l['target']]['label'], l['relation']) for l in self.x['links']}
        self.assertIn(('teamApi.members', 'GET /api/team/members/', 'calls_endpoint'), got)
        self.assertIn(('team_members_view()', 'PortalUser', 'references_model'), got)
        self.assertIn(('TeamView()', 'teamApi.members', 'uses_api_client'), got)

    def test_ambiguous_matches_are_not_marked_extracted(self):
        for l in self.x['links']:
            if l['relation'] == 'calls_endpoint' and 'also possible' in l['evidence']:
                self.assertEqual(l['confidence'], 'INFERRED')

    def test_dynamic_urls_reported_not_graphed(self):
        rep = load('xlayer-report.json')
        self.assertTrue(any(u['kind'] == 'frontend_dynamic_endpoint' for u in rep['unresolved']))


if __name__ == '__main__':
    unittest.main()
