"""Hostile input on the org-graph write endpoints must be a 400, never a 500.

Found by the OWASP ZAP API scan (audit-evidence/07-security): non-numeric
parent_id / occupant_id and non-numeric coordinates reached the ORM or
float() unvalidated and raised, returning HTTP 500.
"""
from .models import OrgNode
from .test_qa_orggraph_authz import _Base


class OrgNodeInputTests(_Base):
    URL = '/api/org/nodes/'

    def test_create_rejects_non_numeric_parent(self):
        for bad in ('http://www.google.com/', 'S4feV4lu3', '1 OR 1=1', [], {}, True, -3):
            r = self.req('post', self.URL, self.root, {'parent_id': bad, 'x': 1, 'y': 1})
            self.assertEqual(r.status_code, 400, (bad, r.content))

    def test_create_rejects_bad_coordinates(self):
        for bad in ('abc', 'nan', 'inf', [], {}):
            r = self.req('post', self.URL, self.root, {'x': bad, 'y': 0})
            self.assertEqual(r.status_code, 400, (bad, r.content))

    def test_create_accepts_valid_input_and_coerces_label(self):
        n = OrgNode.objects.filter(graph=self.g).count()
        r = self.req('post', self.URL, self.root,
                     {'parent_id': str(self.n_mid.id), 'x': '12.5', 'y': 3, 'label': 123})
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(OrgNode.objects.filter(graph=self.g).count(), n + 1)
        self.assertEqual(r.json()['label'], '123')

    def test_patch_rejects_non_numeric_ids_and_coordinates(self):
        url = f'{self.URL}{self.n_leaf.id}/'
        for body in ({'parent_id': 'S4feV4lu3'}, {'parent_id': []}, {'occupant_id': 'x'},
                     {'occupant_id': {}}, {'x': 'abc'}, {'y': 'nan'}):
            r = self.req('patch', url, self.root, body)
            self.assertEqual(r.status_code, 400, (body, r.content))
        self.n_leaf.refresh_from_db()
        self.assertEqual(self.n_leaf.parent_id, self.n_mid.id)      # nothing changed
