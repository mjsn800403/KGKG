#!/usr/bin/env python3
"""Read-only fleet and parts-catalog checks for the staging smoke test.

    KG_SMOKE_TOKEN=<portal token> ops/deploy/smoke_fleet.py <backend-url>
    ops/deploy/smoke_fleet.py --selftest

Called by smoke.sh when it has a portal token (staging). Every request is a GET
and nothing is written. The token comes from the environment, is only ever sent
as a Bearer header, and is never printed.

It uses the token's own fleet (/api/auth/fleet/), so the result depends on what
that account is granted; nothing here assumes a vehicle count. For each listed
vehicle it checks that the fleet flags agree with what the endpoints do:

  has_manual    -> GET /<brand>/<year>/<car>/ answers 200, otherwise 404
  has_parts     -> GET /api/parts/<brand>/<year>/<car>/ answers 200 and a
                   catalog group with part rows can be reached, otherwise the
                   endpoint answers 403 or 404 (no grant / no catalog)
  every listed vehicle has at least one of the two, and both are booleans

The parts-catalog chip rule (has_parts and not has_manual, see
kg_frontend/src/lib/vehicleContent.js) is applied to the same data and reported;
that proves the classification input is right, not that the component renders.

Result lines: ok / FAIL / SKIP. A SKIP means a prerequisite is missing (the
account has no parts-only vehicle, say) and the check did NOT run; it is never
shown as ok. KG_SMOKE_STRICT=1 turns a required SKIP into a failure. Exit 0 only
with no FAIL (and, when strict, no required SKIP).

  KG_SMOKE_SAMPLE=3   vehicles opened per category (default 3, 1..20)
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT_S = 60
LEAF_BUDGET = 15          # requests spent looking for one leaf with part rows


class Report:
    def __init__(self):
        self.lines = []
        self.fails = 0
        self.ok = 0
        self.skips = 0
        self.required_skips = 0

    def passed(self, name, detail=''):
        self.ok += 1
        self.lines.append(f'  ok    {name:<44s} {detail}'.rstrip())

    def failed(self, name, detail):
        self.fails += 1
        self.lines.append(f'  FAIL  {name:<44s} {detail}')

    def skipped(self, name, reason, required=True):
        self.skips += 1
        self.required_skips += 1 if required else 0
        self.lines.append(f'  SKIP  {name:<44s} {reason}')

    def note(self, text):
        self.lines.append(f'        {text}')


def fetch(base, path, token):
    """(status, parsed JSON or None, error text). status is None on a network error."""
    req = urllib.request.Request(base.rstrip('/') + path, headers={
        'Authorization': f'Bearer {token}', 'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    except (urllib.error.URLError, OSError, ValueError) as e:
        return None, None, f'{e.__class__.__name__}: {e}'
    try:
        return status, json.loads(raw.decode('utf-8')), ''
    except ValueError:
        return status, None, 'body is not JSON'


def _q(s):
    return urllib.parse.quote(str(s), safe='')


def _paths(item):
    b, y, c = _q(item['brand_name']), _q(item['year']), _q(item['car_name'])
    return f'/{b}/{y}/{c}/', f'/api/parts/{b}/{y}/{c}/'


def _label(item):
    return f"{item.get('brand_name')} {item.get('car_name')} ({item.get('year')})"


def check_catalog(base, token, parts_path):
    """Walk one parts catalog to a leaf with part rows. Returns (ok, detail)."""
    st, root, err = fetch(base, parts_path, token)
    if st != 200 or not isinstance(root, dict):
        return False, f'root answered {st} {err}'.strip()
    frames = root.get('frames')
    if not isinstance(frames, list) or not frames:
        return False, 'root has no frames'
    first = frames[0].get('code') if isinstance(frames[0], dict) else None
    cfg = root.get('default_frame') or first
    if not cfg:
        return False, 'root has no default frame'
    budget = [LEAF_BUDGET]

    def descend(segs):
        if budget[0] <= 0:
            return 0, 'request budget exhausted before a leaf was found'
        budget[0] -= 1
        qs = urllib.parse.urlencode([('cfg', cfg)] + [('seg', s) for s in segs])
        st2, body, err2 = fetch(base, f'{parts_path}?{qs}', token)
        where = '/'.join(segs) or cfg
        if st2 != 200:
            return 0, f'{where} answered {st2} {err2}'.strip()
        if isinstance(body, dict) and body.get('leaf'):
            rows = sum(len(s.get('parts') or []) for s in body.get('sections') or [])
            return (rows, '') if rows else (0, f'leaf {where} has no part rows')
        if not isinstance(body, list) or not body:
            return 0, f'{where} has no child groups'
        why = ''
        for node in body:
            rows, why = descend(segs + [node.get('title')])
            if rows:
                return rows, ''
            if budget[0] <= 0:
                break
        return 0, why
    rows, why = descend([])
    if not rows:
        return False, why
    return True, f'{len(frames)} frame(s), leaf with {rows} part row(s)'


def _pick(items, n):
    return sorted(items, key=lambda i: (str(i['brand_name']), str(i['car_name']), str(i['year'])))[:n]


def run(base, token, sample=3, strict=False):
    """Run every check. Returns (exit code, report lines)."""
    rep = Report()
    st, body, err = fetch(base, '/api/auth/fleet/', token)
    items = body.get('items') if isinstance(body, dict) else None
    if st != 200 or not isinstance(items, list):
        rep.failed('fleet answers', f'status {st}, items missing {err}'.strip())
        return 1, rep.lines
    rep.passed('fleet answers', f'{len(items)} vehicle(s)')

    bad = []
    for it in items:
        if not all(isinstance(it.get(k), bool) for k in ('has_manual', 'has_parts')):
            bad.append(f'{_label(it)}: flags missing or not boolean')
        elif not (it['has_manual'] or it['has_parts']):
            bad.append(f'{_label(it)}: listed with neither manual nor parts')
    if bad:
        rep.failed('fleet flags are well formed', f'{len(bad)} bad, e.g. {"; ".join(bad[:3])}')
        return 1, rep.lines
    if items:
        rep.passed('fleet flags are well formed', 'booleans, at least one true each')

    manual_only = [i for i in items if i['has_manual'] and not i['has_parts']]
    parts_only = [i for i in items if i['has_parts'] and not i['has_manual']]
    both = [i for i in items if i['has_parts'] and i['has_manual']]
    rep.note(f'fleet: {len(manual_only)} manual-only, {len(parts_only)} parts-only, {len(both)} both; '
             f'the catalog chip would show on {len(parts_only)}')

    def verify(group, want_manual, want_parts, title):
        for it in _pick(group, sample):
            manual_path, parts_path = _paths(it)
            name = f'{title}: {_label(it)}'
            ms, _, _ = fetch(base, manual_path, token)
            if want_manual and ms == 200:
                rep.passed(name + ' manual', '200')
            elif not want_manual and ms == 404:
                rep.passed(name + ' manual', '404 (no manual, as flagged)')
            else:
                rep.failed(name + ' manual', f'answered {ms}, want {"200" if want_manual else "404"}')
            if want_parts:
                ok, detail = check_catalog(base, token, parts_path)
                if ok:
                    rep.passed(name + ' parts', detail)
                else:
                    rep.failed(name + ' parts', detail)
            else:
                ps, _, _ = fetch(base, parts_path, token)
                if ps in (403, 404):
                    rep.passed(name + ' parts', f'{ps} (no catalog served, as flagged)')
                else:
                    rep.failed(name + ' parts', f'answered {ps}, want 403/404 because has_parts is false')

    if parts_only:
        verify(parts_only, False, True, 'parts-only')
    else:
        rep.skipped('parts-only vehicles', "none in this token's fleet; catalog and chip-rule checks did not run")
    if manual_only:
        verify(manual_only, True, False, 'manual-only')
    else:
        rep.skipped('manual-only vehicles', "none in this token's fleet; manual-only checks did not run")
    if both:
        verify(both, True, True, 'manual+parts')
    else:
        rep.skipped('manual+parts vehicles', "none in this token's fleet (unit tests only)", required=False)

    rep.note(f'{rep.ok} ok, {rep.fails} failed, {rep.skips} skipped ({rep.required_skips} required)')
    if rep.required_skips and not strict:
        rep.note('required checks were SKIPPED, not passed (KG_SMOKE_STRICT=1 fails the run)')
    return (1 if rep.fails or (strict and rep.required_skips) else 0), rep.lines


# ---------------------------------------------------------------------------
# --selftest: a fake backend on loopback, so the checker itself is tested in CI
# ---------------------------------------------------------------------------
def _selftest():
    import threading
    import unittest
    from http.server import BaseHTTPRequestHandler, HTTPServer

    token = 'selftest-secret-token-0123456789'
    cars = {}                      # car_name -> {'manual': status, 'parts': kind}
    state = {'fleet': [], 'fleet_status': 200}

    def car(name, manual=200, parts='none', brand='Toyota', year=2022):
        cars[name] = {'manual': manual, 'parts': parts}
        return {'brand_name': brand, 'car_name': name, 'year': year}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, status, payload):
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            u = urllib.parse.urlsplit(self.path)
            if self.headers.get('Authorization') != f'Bearer {token}':
                return self.send(401, {'error': 'unauthorized'})
            parts = [urllib.parse.unquote(p) for p in u.path.strip('/').split('/')]
            if u.path == '/api/auth/fleet/':
                return self.send(state['fleet_status'], {'items': state['fleet']})
            if parts[:2] == ['api', 'parts'] and len(parts) == 5:
                kind = cars.get(parts[4], {}).get('parts', 'none')
                q = urllib.parse.parse_qs(u.query)
                if kind in ('none',):
                    return self.send(404, {'error': 'no_parts_catalog'})
                if kind == 'forbidden':
                    return self.send(403, {'error': 'forbidden'})
                if not q:
                    return self.send(200, {'frames': [{'code': 'FR1'}], 'default_frame': 'FR1'})
                segs = q.get('seg', [])
                if not segs:
                    return self.send(200, [{'title': 'Service parts', 'is_leaf': False}])
                if segs == ['Service parts']:
                    return self.send(200, [{'title': 'Empty', 'is_leaf': True}, {'title': 'Oil Filter', 'is_leaf': True}]
                                     if kind == 'ok' else [{'title': 'Empty', 'is_leaf': True}])
                if segs == ['Service parts', 'Oil Filter']:
                    return self.send(200, {'leaf': True, 'sections': [{'parts': [{'pn': '1'}, {'pn': '2'}]}]})
                return self.send(200, {'leaf': True, 'sections': [{'parts': []}]})
            if len(parts) == 3:
                status = cars.get(parts[2], {}).get('manual', 404)
                return self.send(status, {'children': []} if status == 200 else {'error': 'not found'})
            return self.send(404, {'error': 'unknown'})

    srv = HTTPServer(('127.0.0.1', 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{srv.server_port}'

    def good_fleet():
        cars.clear()
        return [
            dict(car('Corolla Cross LE (2023)', manual=200, parts='none'), has_manual=True, has_parts=False),
            dict(car('Corolla Cross LE (Parts 2022)', manual=404, parts='ok'), has_manual=False, has_parts=True),
            dict(car('Camry Both', manual=200, parts='ok'), has_manual=True, has_parts=True),
        ]

    class T(unittest.TestCase):
        def setUp(self):
            state['fleet'] = good_fleet()
            state['fleet_status'] = 200

        def go(self, strict=False, tok=token):
            code, lines = run(base, tok, 3, strict)
            return code, '\n'.join(lines)

        def test_all_four_scenarios_consistent(self):
            code, out = self.go()
            self.assertEqual(code, 0, out)
            self.assertIn('1 manual-only, 1 parts-only, 1 both', out)
            self.assertIn('the catalog chip would show on 1', out)
            self.assertNotIn('SKIP', out)

        def test_token_never_printed(self):
            _, out = self.go()
            self.assertNotIn(token, out)

        def test_manual_vehicle_wrongly_flagged_with_parts_fails(self):
            state['fleet'][0]['has_parts'] = True        # the PR #71 bug, seen from the API
            code, out = self.go()
            self.assertEqual(code, 1)
            self.assertRegex(out, r'FAIL  manual\+parts: .*LE \(2023\).* parts +root answered 404')

        def test_parts_hidden_from_flags_fails(self):
            cars['Corolla Cross LE (2023)']['parts'] = 'ok'   # catalog served but flag false
            code, out = self.go()
            self.assertEqual(code, 1)
            self.assertIn('want 403/404 because has_parts is false', out)

        def test_parts_only_vehicle_that_still_serves_a_manual_fails(self):
            cars['Corolla Cross LE (Parts 2022)']['manual'] = 200
            code, out = self.go()
            self.assertEqual(code, 1)
            self.assertIn('manual', out)

        def test_empty_catalog_fails(self):
            cars['Corolla Cross LE (Parts 2022)']['parts'] = 'emptyleaf'
            code, out = self.go()
            self.assertEqual(code, 1)
            self.assertIn('no part rows', out)

        def test_ungranted_parts_counts_as_not_served(self):
            state['fleet'][0]['has_parts'] = False
            cars['Corolla Cross LE (2023)']['parts'] = 'forbidden'
            code, out = self.go()
            self.assertEqual(code, 0, out)

        def test_malformed_flags_fail(self):
            for bad in ({'has_manual': 'yes', 'has_parts': False}, {'has_manual': False, 'has_parts': False},
                        {'has_parts': True}):
                state['fleet'] = [dict({'brand_name': 'Toyota', 'car_name': 'X', 'year': 2022}, **bad)]
                code, out = self.go()
                self.assertEqual(code, 1, bad)
                self.assertIn('FAIL  fleet flags are well formed', out)

        def test_fleet_error_is_an_application_failure(self):
            state['fleet_status'] = 500
            code, out = self.go()
            self.assertEqual(code, 1)
            self.assertIn('FAIL  fleet answers', out)

        def test_wrong_token_fails(self):
            code, out = self.go(tok='nope')
            self.assertEqual(code, 1)
            self.assertIn('status 401', out)

        def test_empty_fleet_is_skipped_loudly_and_fails_when_strict(self):
            state['fleet'] = []
            code, out = self.go()
            self.assertEqual(code, 0)
            self.assertIn('SKIP  parts-only vehicles', out)
            self.assertIn('SKIP  manual-only vehicles', out)
            self.assertNotIn('  ok    parts-only', out)
            self.assertEqual(self.go(strict=True)[0], 1)

        def test_missing_parts_only_is_a_required_skip(self):
            state['fleet'] = state['fleet'][:1] + state['fleet'][2:]
            code, out = self.go()
            self.assertEqual(code, 0)
            self.assertIn('SKIP  parts-only vehicles', out)
            self.assertEqual(self.go(strict=True)[0], 1)

        def test_missing_both_category_is_not_a_required_skip(self):
            state['fleet'] = state['fleet'][:2]
            self.assertEqual(self.go(strict=True)[0], 0)

        def test_unreachable_backend_fails(self):
            code, lines = run('http://127.0.0.1:1', token)
            self.assertEqual(code, 1)

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(T)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    srv.shutdown()
    return 0 if result.wasSuccessful() else 1


def main(argv):
    if argv == ['--selftest']:
        return _selftest()
    token = os.environ.get('KG_SMOKE_TOKEN', '')
    if len(argv) != 1 or not token:
        print('usage: KG_SMOKE_TOKEN=<token> smoke_fleet.py <backend-url> | --selftest')
        return 2
    try:
        sample = max(1, min(20, int(os.environ.get('KG_SMOKE_SAMPLE', '3'))))
    except ValueError:
        sample = 3
    code, lines = run(argv[0], token, sample, os.environ.get('KG_SMOKE_STRICT') == '1')
    print('\n'.join(lines))
    return code


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
