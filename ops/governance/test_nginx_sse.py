"""The Nginx route that carries the live event stream must not be able to buffer it.

Live updates (staff inbox, portal) ride Server-Sent Events through ``/kg-api/api/events/stream/``.
A proxy that buffers, compresses or times out that response does not fail loudly: the console
quietly falls back to its 20 s refresh, so nobody notices for weeks. These checks read
ops/nginx/kgkg.conf (standard library only) and fail when an edit would reintroduce the problem.
Verified against the live server's effective config (``nginx -T``, read-only) on 2026-11-04.

    python3 -m unittest discover -s ops/governance -t ops/governance -p 'test_*.py'
"""
import os
import re
import unittest

CONF = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'nginx', 'kgkg.conf')
STREAM_MAX_S = 300           # api/events.py _MAX_STREAM_S: the server recycles the stream
HEARTBEAT_S = 15             # api/events.py _HEARTBEAT_S


def _text():
    with open(CONF, encoding='utf-8') as f:
        return f.read()


def _block(text, header):
    """The braces-balanced body of the first block whose header line contains ``header``."""
    start = text.index(header)
    open_at = text.index('{', start)
    depth, i = 0, open_at
    while True:
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return text[open_at + 1:i]
        i += 1


def _seconds(value):
    m = re.fullmatch(r'(\d+)([smh]?)', value.strip())
    return int(m.group(1)) * {'': 1, 's': 1, 'm': 60, 'h': 3600}[m.group(2)]


class StreamLocation(unittest.TestCase):
    def setUp(self):
        self.text = _text()
        self.block = _block(self.text, 'location = /kg-api/api/events/stream/')

    def directive(self, name):
        m = re.search(rf'^\s*{name}\s+([^;]+);', self.block, re.M)
        return m.group(1).strip() if m else None

    def test_it_does_not_buffer_or_cache(self):
        self.assertEqual(self.directive('proxy_buffering'), 'off')
        self.assertEqual(self.directive('proxy_cache'), 'off')

    def test_it_asks_nginx_not_to_buffer_per_response(self):
        self.assertRegex(self.block, r'add_header\s+X-Accel-Buffering\s+no\b')

    def test_http_1_1_with_chunked_transfer(self):
        self.assertEqual(self.directive('proxy_http_version'), '1.1')
        self.assertEqual(self.directive('chunked_transfer_encoding'), 'on')

    def test_the_read_timeout_outlasts_a_stream_and_many_heartbeats(self):
        timeout = _seconds(self.directive('proxy_read_timeout'))
        self.assertGreater(timeout, STREAM_MAX_S, 'a stream must end by recycle, never by proxy timeout')
        self.assertGreater(timeout, HEARTBEAT_S * 3)

    def test_clients_are_limited_by_connections_not_request_rate(self):
        self.assertIsNotNone(self.directive('limit_conn'))
        self.assertNotIn('limit_req', self.block)

    def test_it_precedes_the_general_api_location(self):
        self.assertLess(self.text.index('location = /kg-api/api/events/stream/'),
                        self.text.index('location /kg-api/ '))


class NothingElseCanBufferIt(unittest.TestCase):
    def test_event_stream_is_never_compressed(self):
        for m in re.finditer(r'^\s*gzip_types\s+([^;]+);', _text(), re.M):
            self.assertNotIn('text/event-stream', m.group(1))

    def test_the_stream_is_not_exposed_through_a_cached_location(self):
        self.assertNotRegex(_text(), r'proxy_cache_path')


if __name__ == '__main__':
    unittest.main()
