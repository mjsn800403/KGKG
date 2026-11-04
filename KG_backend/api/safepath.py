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
_EXC_NAME = re.compile(
    r'(?<![\w.])(?:[A-Za-z_]\w*\.)*([A-Z]\w*(?:Error|Exception|Exit|Warning|Interrupt|Timeout))(?=:)')
# A short one-line phrase with no path/URL/DSN/frame punctuation cannot carry
# those details and is kept as is (e.g. 'skipped by admin', 'parse; rag').
_PLAIN = re.compile(r'[^\n\r:/\\"\'.()\[\]{}<>@=%]{1,120}')
_ERROR_KEYS = ('error', 'db_error')


def public_error(value):
    """A stored or caught error text reduced to what is safe to send to a client.

    Plain short phrases and bare class names pass; anything else (a traceback,
    ``'OSError: [Errno 2] ... /srv/x'``, ``'cannot open: <sqlite message>'``)
    becomes the exception class name(s) it contains, or ``'error'``."""
    if not isinstance(value, str) or not value.strip():
        return value
    s = value.strip()
    if _PLAIN.fullmatch(s):
        return s
    names = []
    for m in _EXC_NAME.finditer(s):
        if m.group(1) not in names:
            names.append(m.group(1))
    return ', '.join(names[:3]) if names else 'error'


def scrub_errors(obj):
    """``obj`` (JSON-like) with every ``error`` / ``db_error`` string passed through
    :func:`public_error`; other keys and structure are untouched."""
    if isinstance(obj, dict):
        return {k: (public_error(v) if k in _ERROR_KEYS and isinstance(v, str) else scrub_errors(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub_errors(v) for v in obj]
    return obj


def split_year_suffix(name):
    """``('Corolla LE, FWD', 2023)`` for ``'Corolla LE, FWD (2023)'``; ``(name, None)``
    when there is no trailing four-digit year. Same result as the old
    ``\\s*\\((\\d{4})\\)\\s*$`` search, in linear time."""
    stripped = name.rstrip()
    m = _YEAR.search(stripped)
    if not m:
        return name, None
    return stripped[:m.start()].strip(), int(m.group(1))
