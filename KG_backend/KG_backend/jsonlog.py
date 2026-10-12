"""One-JSON-object-per-line log formatting, plus secret scrubbing.

Why JSON rather than the usual `[time] LEVEL name: message`: these logs are
meant to be *queried*, not eyeballed. `jq` over app.jsonl answers "which user
hit which endpoint before that 500" in one line; a regex over free-form text
does not. It is also the format every log shipper ingests without a custom
parser, so pointing this at Loki/ELK later is a config change, not a rewrite.

The scrubbing here is deliberately belt-and-braces. `send_default_pii=False`
already keeps Sentry/GlitchTip from attaching users and request bodies, but
secrets leak through channels that setting doesn't cover — an exception
message that happens to contain a bearer token, a logged URL with `?token=`,
an env dump in `extra`. Everything that looks like a credential gets replaced
before it reaches disk or the network.
"""
import datetime
import json
import logging
import os
import re
import sys
import traceback

# Record attributes the stdlib puts on every LogRecord. Anything NOT in here was
# added by the caller via `extra=` and is worth carrying into the JSON payload.
_STD_ATTRS = frozenset((
    'args', 'asctime', 'created', 'exc_info', 'exc_text', 'filename',
    'funcName', 'levelname', 'levelno', 'lineno', 'module', 'msecs',
    'message', 'msg', 'name', 'pathname', 'process', 'processName',
    'relativeCreated', 'stack_info', 'thread', 'threadName', 'taskName',
))

# Keys whose *value* is a secret regardless of what it looks like.
_SECRET_KEY_RE = re.compile(
    r'(secret|password|passwd|token|api[-_]?key|authorization|auth|cookie|'
    r'session|credential|dsn|private)', re.I)

# Secrets embedded in free text: `token=abc123`, `Bearer eyJ...`, `?key=...`.
_INLINE_SECRET_RE = re.compile(
    r'((?:secret|password|passwd|token|api[-_]?key|apikey|auth|key)'
    r'["\']?\s*[=:]\s*["\']?)([^\s"\'&,;}\]]{6,})', re.I)
_BEARER_RE = re.compile(r'\b(Bearer|Token)\s+([A-Za-z0-9._\-]{12,})', re.I)

REDACTED = '***redacted***'


def _scrub_text(value):
    """Blank out credential-shaped substrings inside a free-text string."""
    if not isinstance(value, str) or len(value) < 6:
        return value
    value = _INLINE_SECRET_RE.sub(lambda m: m.group(1) + REDACTED, value)
    value = _BEARER_RE.sub(lambda m: f'{m.group(1)} {REDACTED}', value)
    return value


def scrub(value, _depth=0):
    """Recursively redact secret-looking keys and inline credentials.

    Depth-capped: log payloads are occasionally self-referential (ORM objects,
    request wrappers) and a runaway walk in the logger would be a very annoying
    way to take the site down.
    """
    if _depth > 6:
        return '<max-depth>'
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if isinstance(k, str) and _SECRET_KEY_RE.search(k):
                out[k] = REDACTED
            else:
                out[k] = scrub(v, _depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [scrub(v, _depth + 1) for v in value]
    if isinstance(value, str):
        return _scrub_text(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _scrub_text(str(value))


# Event fields that can carry credentials. Everything else in a Sentry event is
# structure the server parses strictly (stack frames, timestamps, event ids) and
# must be handed over untouched.
_EVENT_TEXT_FIELDS = ('message', 'culprit', 'transaction', 'server_name')


def scrub_event(event):
    """`before_send` hook for sentry_sdk — sanitise, then let the event through.

    Deliberately surgical rather than a blanket walk of the event.

    An earlier version ran `scrub()` over the whole event dict. That corrupted
    it: a Sentry event nests deeper than the recursion cap
    (exception -> values -> stacktrace -> frames -> vars), so stack frames came
    out replaced by the literal string '<max-depth>' and datetimes came out as
    prose. GlitchTip rejected every such event with HTTP 400 — i.e. the
    scrubbing silently disabled the monitoring it was meant to protect.

    So: touch only the fields that actually hold user/secret data, and leave the
    machinery alone. Returning None would drop the event entirely; we never do.
    """
    try:
        if not isinstance(event, dict):
            return event

        for field in _EVENT_TEXT_FIELDS:
            if isinstance(event.get(field), str):
                event[field] = _scrub_text(event[field])

        logentry = event.get('logentry')
        if isinstance(logentry, dict):
            for field in ('message', 'formatted'):
                if isinstance(logentry.get(field), str):
                    logentry[field] = _scrub_text(logentry[field])

        # Free-form context the application attached — the most likely place for
        # a stray token, and safe to walk because it isn't parsed structurally.
        for field in ('extra', 'tags'):
            if isinstance(event.get(field), dict):
                event[field] = scrub(event[field])

        # Request metadata. send_default_pii=False already drops most of this;
        # belt-and-braces for the parts that survive.
        request = event.get('request')
        if isinstance(request, dict):
            for field in ('headers', 'cookies', 'env'):
                if isinstance(request.get(field), dict):
                    request[field] = scrub(request[field])
            for field in ('query_string', 'url'):
                if isinstance(request.get(field), str):
                    request[field] = _scrub_text(request[field])

        # Exception messages: "invalid token abc123" is a real pattern.
        values = (event.get('exception') or {}).get('values')
        if isinstance(values, list):
            for value in values:
                if isinstance(value, dict) and isinstance(value.get('value'), str):
                    value['value'] = _scrub_text(value['value'])

        breadcrumbs = event.get('breadcrumbs')
        crumbs = breadcrumbs.get('values') if isinstance(breadcrumbs, dict) else breadcrumbs
        if isinstance(crumbs, list):
            for crumb in crumbs:
                if not isinstance(crumb, dict):
                    continue
                if isinstance(crumb.get('message'), str):
                    crumb['message'] = _scrub_text(crumb['message'])
                if isinstance(crumb.get('data'), dict):
                    crumb['data'] = scrub(crumb['data'])

        return event
    except Exception:      # never let the monitoring path raise
        return event


class QuietInTests(logging.Filter):
    """Drop records while the Django test runner is active.

    The suite deliberately exercises 401/403/404/500 paths; letting those write
    to error.jsonl (and page GlitchTip) would bury real incidents under
    thousands of expected failures and make `manage.py test` output unreadable.
    """

    def filter(self, record):
        return 'test' not in sys.argv[:2] and not os.environ.get('KG_TESTING')


class JsonFormatter(logging.Formatter):
    """Render a LogRecord as a single-line JSON object."""

    @staticmethod
    def _timestamp(record):
        """UTC ISO-8601 with milliseconds.

        Not `logging.Formatter.formatTime`: that renders in the server's local
        zone, and correlating these lines with nginx, GlitchTip and the DB
        (all UTC here) is exactly what you need logs for during an incident.
        """
        return datetime.datetime.fromtimestamp(
            record.created, datetime.timezone.utc).isoformat(timespec='milliseconds')

    def format(self, record):
        payload = {
            'ts': self._timestamp(record),
            'level': record.levelname,
            'logger': record.name,
            'msg': _scrub_text(record.getMessage()),
            'module': record.module,
            'line': record.lineno,
            'pid': record.process,
        }

        if record.exc_info:
            exc_type, exc_value, exc_tb = record.exc_info
            payload['error'] = {
                'type': getattr(exc_type, '__name__', str(exc_type)),
                'value': _scrub_text(str(exc_value)),
                'stack': _scrub_text(
                    ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))),
            }

        # Request context, when a caller passed one through `extra=`.
        extra = {k: v for k, v in record.__dict__.items()
                 if k not in _STD_ATTRS and not k.startswith('_')}
        # Django's request logger attaches the whole HttpRequest; keep the few
        # useful fields rather than a giant unserialisable blob.
        request = extra.pop('request', None)
        if request is not None:
            try:
                payload['request'] = {
                    'method': getattr(request, 'method', None),
                    'path': _scrub_text(getattr(request, 'path', '') or ''),
                    'ip': (request.META.get('HTTP_X_REAL_IP')
                           or request.META.get('REMOTE_ADDR')),
                }
            except Exception:
                pass
        if extra:
            payload['extra'] = scrub(extra)

        try:
            return json.dumps(payload, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            # A log line must always come out, even if something in it is unserialisable.
            return json.dumps({'ts': payload['ts'], 'level': payload['level'],
                               'logger': payload['logger'],
                               'msg': '<unserialisable log record>'})
