"""Small helpers that close whole classes of CodeQL findings at one place.

``safe_join`` is the only way a name that came from a request, a database row or
a folder listing becomes a path under a known directory (``py/path-injection``).
``split_year_suffix`` replaces regexes whose leading and trailing ``\\s*`` were
quadratic on long whitespace runs (``py/polynomial-redos``).

No Django imports: the offline tools under ``api/rag`` import this too.
"""
import os
import re
from pathlib import Path

_YEAR = re.compile(r'\((\d{4})\)$')


def safe_join(base, *names):
    """``base`` joined with ``names``, refused unless the result stays inside ``base``.

    Normalises first, then checks containment on a separator boundary, so
    ``../x``, an absolute name, a NUL byte and a sibling that merely shares the
    base's prefix (``/srv/warehouse-evil``) are all ``ValueError``. ``..`` inside
    a file name (``Foo..Bar.db``) is not traversal and is allowed.
    """
    base_s = os.path.normpath(os.fspath(base))
    parts = [os.fspath(n) for n in names]
    if any('\x00' in p for p in parts):
        raise ValueError('NUL byte in path')
    joined = os.path.normpath(os.path.join(base_s, *parts))
    if joined != base_s and not joined.startswith(base_s.rstrip(os.sep) + os.sep):
        raise ValueError('path escapes its base directory')
    return Path(joined)


# --- error text that may leave the server --------------------------------
# Exception messages name files, SQL, hosts and DSNs, and a stored traceback names
# every frame (CodeQL py/stack-trace-exposure, KGTEC-14). New code stores and returns
# the exception CLASS only and logs the rest; ``public_error`` also reduces the
# text already persisted by older versions (DataQualityRun.error, ZipPackage.error,
# ProcessingJob.error/stages, SystemAlert.context) when an API serves it.
#
# Fail closed: a stored error text is returned unchanged ONLY when it is one of the
# phrases our own code writes (SAFE_PHRASES), a list of our own pipeline stage keys,
# or a verified exception class name. Everything else -- including short text with no
# punctuation at all ("password for admin is hunter2") -- becomes the verified
# exception class name(s) found in it, or the word "error".
import builtins

SAFE_PHRASES = frozenset({
    'error', 'skipped by admin', 'zip file missing on disk', 'parse produced no result',
    'parse failed', 'no nodes table', 'every vehicle-schema build failed',
    'every diag build failed', 'every PostgreSQL move failed',
    'به دلیل خطا در مرحله RAG اجرا نشد',
})
# ProcessingJob.error is '; '.join(<failed stage keys>) (run_pipeline.py), 'worker' for a crash.
STAGE_KEYS = frozenset({'parse', 'catalog', 'schema', 'rag', 'diag', 'pgcar', 'audit', 'worker'})
# A class name proves nothing unless it is one we know: builtins plus the library
# errors this code base can meet. An unknown class (or text posing as one) is not echoed.
_EXC_NAMES = frozenset(
    {n for n, v in vars(builtins).items() if isinstance(v, type) and issubclass(v, BaseException)}
    | {'OperationalError', 'DatabaseError', 'IntegrityError', 'ProgrammingError', 'InterfaceError',
       'DataError', 'NotSupportedError', 'InternalError', 'BadZipFile', 'LargeZipFile',
       'JSONDecodeError', 'URLError', 'HTTPError', 'TimeoutExpired', 'CalledProcessError',
       'SubprocessError', 'BrokenProcessPool', 'HostJobError', 'BuildError', 'DoesNotExist',
       'MultipleObjectsReturned', 'ValidationError', 'SSLError', 'ConnectionError'})
_EXC_TOKEN = re.compile(r'(?<![\w.])(?:\w+\.)*(\w+)(?=:|$|\s*[|;,]|\s*\Z)')
_ERROR_KEYS = ('error', 'db_error')
_INTEGRITY_OK = frozenset({'ok', 'error', 'unreadable'})


def _exception_names(text):
    """The verified exception class names mentioned in ``text``, in order, de-duplicated."""
    names = []
    for m in _EXC_TOKEN.finditer(text):
        n = m.group(1)
        if n in _EXC_NAMES and n not in names:
            names.append(n)
    return names


def public_error(value):
    """A stored or caught error text reduced to what is safe to send to a client:
    one of our own phrases, our stage keys, or the verified exception class name(s)
    in it, else ``'error'``."""
    if not isinstance(value, str) or not value.strip():
        return value
    s = value.strip()
    if s in SAFE_PHRASES:
        return s
    if all(t.strip() in STAGE_KEYS for t in s.split(';')):
        return '; '.join(t.strip() for t in s.split(';'))
    names = _exception_names(s)
    return ', '.join(names[:3]) if names else 'error'


def scrub_errors(obj):
    """``obj`` (JSON-like) with every ``error`` / ``db_error`` string passed through
    :func:`public_error`, an audit ``integrity`` verdict reduced to ok / error /
    unreadable (it can hold SQLite's own corruption message) and a ``log_tail`` passed
    through :func:`public_log_tail`; other keys and the structure are untouched."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in _ERROR_KEYS and isinstance(v, str):
                out[k] = public_error(v)
            elif k == 'integrity' and isinstance(v, str):
                out[k] = v if v in _INTEGRITY_OK else 'error'
            elif k == 'log_tail' and isinstance(v, str):
                out[k] = public_log_tail(v)         # crawler status carries its crawl.log tail
            else:
                out[k] = scrub_errors(v)
        return out
    if isinstance(obj, list):
        return [scrub_errors(v) for v in obj]
    return obj


# --- the worker log tail ---------------------------------------------------
# ProcessingJob.log_tail is the pipeline worker's rolling log (run_pipeline.Runner.log),
# which also tees the stdout/stderr of the commands it calls. New code no longer writes
# exception text into it, but rows written earlier hold lines like
# "!! stage rag failed: OSError: [Errno 2] ... /srv/x" and traceback frames. The text is
# free-form, so this is a redaction, not an allow-list: error lines lose their message,
# traceback frames disappear and credential-looking values are masked.
_LOG_STAMP = re.compile(r'^(\[\d\d:\d\d:\d\d\]\s*)?(.*)$', re.DOTALL)
_TRACE_LINE = re.compile(r'^\s*(Traceback \(most recent call last\)|File ")')
_SECRET_KV = re.compile(
    r'(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|authorization|dsn)\b(\s*[=:]\s*)(?:Bearer\s+)?\S+')
_URL_CREDS = re.compile(r'(\w+://)[^/\s:@]+:[^/\s@]+@')


def _public_log_line(line):
    m = _LOG_STAMP.match(line)
    stamp, body = (m.group(1) or ''), m.group(2)
    if _TRACE_LINE.match(body):
        return stamp + '[traceback omitted]'
    body = _URL_CREDS.sub(r'\1[redacted]@', body)
    body = _SECRET_KV.sub(r'\1\2[redacted]', body)
    if body.startswith('!!'):
        # "!! <what failed>: <message>" -> keep what failed and the verified class
        head, sep, rest = body.partition(': ')
        names = _exception_names(rest) if sep else []
        return stamp + head + (': ' + ', '.join(names[:3]) if names else '')
    for tm in _EXC_TOKEN.finditer(body):
        if tm.group(1) in _EXC_NAMES and body[tm.end():tm.end() + 1] == ':':
            return stamp + body[:tm.end()]          # "ValueError: <message>" -> "ValueError"
    return stamp + body


def public_log_tail(text):
    """The worker log tail with exception messages, traceback frames and credential-looking
    values removed (see the note above: a redaction, so other free text is kept)."""
    if not isinstance(text, str) or not text:
        return text
    return '\n'.join(_public_log_line(ln) for ln in text.split('\n'))


def split_year_suffix(name):
    """``('Corolla LE, FWD', 2023)`` for ``'Corolla LE, FWD (2023)'``; ``(name, None)``
    when there is no trailing four-digit year. Same result as the old
    ``\\s*\\((\\d{4})\\)\\s*$`` search, in linear time."""
    stripped = name.rstrip()
    m = _YEAR.search(stripped)
    if not m:
        return name, None
    return stripped[:m.start()].strip(), int(m.group(1))
