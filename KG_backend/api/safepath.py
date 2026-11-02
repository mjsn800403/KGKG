"""Two small helpers that close whole classes of CodeQL findings at one place.

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


def split_year_suffix(name):
    """``('Corolla LE, FWD', 2023)`` for ``'Corolla LE, FWD (2023)'``; ``(name, None)``
    when there is no trailing four-digit year. Same result as the old
    ``\\s*\\((\\d{4})\\)\\s*$`` search, in linear time."""
    stripped = name.rstrip()
    m = _YEAR.search(stripped)
    if not m:
        return name, None
    return stripped[:m.start()].strip(), int(m.group(1))
