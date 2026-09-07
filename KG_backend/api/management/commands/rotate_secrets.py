"""Rotate the server's long-lived secrets in place, safely.

Before this, rotating DJANGO_SECRET_KEY or KG_ADMIN_TOKEN meant hand-editing
.env.prod — which nobody did, so both had been the same value since first
deploy. This command makes rotation a one-liner with the sharp edges handled:

  * the env file is rewritten atomically (temp file + os.replace) with mode
    0600, so a crash mid-write can't leave the backend with no secret at all
    and the file never briefly exists world-readable;
  * the outgoing DJANGO_SECRET_KEY is pushed onto DJANGO_SECRET_KEY_FALLBACKS,
    so signatures already in flight (password-reset links, signed cookies)
    still verify for one more window instead of erroring the moment you rotate;
  * a timestamped backup of the previous env file is kept, also 0600.

Nothing takes effect until the service restarts — the command says so rather
than restarting on your behalf, because that's a production decision.

Usage:
    manage.py rotate_secrets --what django-key
    manage.py rotate_secrets --what admin-token
    manage.py rotate_secrets --what all --prune-fallbacks 1
    manage.py rotate_secrets --status          # ages only, never prints values
"""
import datetime
import os
import re
import secrets
import stat
import tempfile

from django.core.management.base import BaseCommand, CommandError

DEFAULT_ENV = '/opt/KGKG/KG_backend/.env.prod'

# Rotating these is a plain value swap.
ROTATABLE = {
    'django-key': 'DJANGO_SECRET_KEY',
    'admin-token': 'KG_ADMIN_TOKEN',
}


def parse_env(text):
    """Very small KEY=VALUE reader — matches what systemd EnvironmentFile does.

    Deliberately not shlex: systemd's parser doesn't do command substitution or
    variable expansion either, and mimicking it exactly avoids the file meaning
    one thing to systemd and another to this command.
    """
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def render_env(original, updates):
    """Return `original` with `updates` applied, preserving order and comments.

    Rewriting the file from a dict would throw away the comments that explain
    what each knob does; keeping the original layout means a human can still
    read the file after a rotation.
    """
    seen = set()
    lines = []
    for line in original.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith('#') and '=' in stripped:
            key = stripped.split('=', 1)[0].strip()
            if key in updates:
                seen.add(key)
                value = updates[key]
                if value is None:          # explicit removal
                    continue
                lines.append(f'{key}={value}')
                continue
        lines.append(line)
    for key, value in updates.items():
        if key not in seen and value is not None:
            lines.append(f'{key}={value}')
    return '\n'.join(lines).rstrip('\n') + '\n'


def write_env_atomically(path, content):
    """Replace `path` with `content`, 0600, without ever truncating in place."""
    directory = os.path.dirname(path) or '.'
    fd, tmp = tempfile.mkstemp(dir=directory, prefix='.env.rotate.')
    try:
        with os.fdopen(fd, 'w') as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(tmp, path)              # atomic on the same filesystem
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _fingerprint(value):
    """A stable, non-reversible handle for a secret, safe to print in logs."""
    import hashlib
    if not value:
        return '(unset)'
    return hashlib.sha256(value.encode()).hexdigest()[:12]


class Command(BaseCommand):
    help = 'Rotate DJANGO_SECRET_KEY / KG_ADMIN_TOKEN in the production env file.'

    def add_arguments(self, parser):
        parser.add_argument('--what', default='status',
                            choices=sorted(ROTATABLE) + ['all', 'status'],
                            help='Which secret to rotate (default: just report).')
        parser.add_argument('--env-file', default=os.environ.get('KG_ENV_FILE', DEFAULT_ENV))
        parser.add_argument('--prune-fallbacks', type=int, default=1,
                            help='How many retired Django keys to keep for '
                                 'signature verification (default 1).')
        parser.add_argument('--status', action='store_true',
                            help='Report secret ages/fingerprints and exit.')
        parser.add_argument('--print-new', action='store_true',
                            help='Echo the new KG_ADMIN_TOKEN to stdout. Only '
                                 'use this on a terminal you trust.')

    def handle(self, *args, **opts):
        path = opts['env_file']
        if not os.path.exists(path):
            raise CommandError(f'env file not found: {path}')

        with open(path) as fh:
            original = fh.read()
        env = parse_env(original)

        what = 'status' if opts['status'] else opts['what']
        if what == 'status':
            return self._status(path, env)

        targets = sorted(ROTATABLE) if what == 'all' else [what]
        updates = {}
        new_admin_token = None

        for target in targets:
            var = ROTATABLE[target]
            old = env.get(var, '')
            if target == 'django-key':
                new = secrets.token_urlsafe(64)
                updates[var] = new
                # Keep the outgoing key verifying for one more window.
                fallbacks = [f for f in
                             (env.get('DJANGO_SECRET_KEY_FALLBACKS', '') or '').split(',')
                             if f.strip()]
                if old:
                    fallbacks.insert(0, old)
                keep = max(0, opts['prune_fallbacks'])
                updates['DJANGO_SECRET_KEY_FALLBACKS'] = (
                    ','.join(fallbacks[:keep]) if keep and fallbacks else None)
            else:
                new = secrets.token_urlsafe(48)
                updates[var] = new
                new_admin_token = new
            self.stdout.write(
                f'{var}: {_fingerprint(old)} -> {_fingerprint(new)}')

        # Back up the outgoing file before replacing it, at 0600.
        stamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
        backup = f'{path}.bak.{stamp}'
        write_env_atomically(backup, original)

        write_env_atomically(path, render_env(original, updates))

        self.stdout.write(self.style.SUCCESS(f'rewrote {path} (mode 0600)'))
        self.stdout.write(f'previous version saved to {backup}')

        if new_admin_token and opts['print_new']:
            self.stdout.write(f'KG_ADMIN_TOKEN={new_admin_token}')
        elif new_admin_token:
            self.stdout.write('new KG_ADMIN_TOKEN written to the env file '
                              '(re-run with --print-new to display it)')

        self.stdout.write(self.style.WARNING(
            'not live yet — run: systemctl restart kgkg-backend'))

    def _status(self, path, env):
        st = os.stat(path)
        mode = stat.S_IMODE(st.st_mode)
        age = datetime.datetime.now() - datetime.datetime.fromtimestamp(st.st_mtime)

        self.stdout.write(f'env file : {path}')
        self.stdout.write(f'mode     : {mode:04o}' + (
            '  <-- should be 0600' if mode & 0o077 else '  (ok)'))
        self.stdout.write(f'modified : {age.days}d ago')
        for var in sorted(set(ROTATABLE.values())):
            self.stdout.write(f'{var:<24}: {_fingerprint(env.get(var, ""))}')
        fallbacks = [f for f in (env.get('DJANGO_SECRET_KEY_FALLBACKS', '') or '').split(',')
                     if f.strip()]
        self.stdout.write(f'{"retired django keys":<24}: {len(fallbacks)}')
        if age.days > 90:
            self.stdout.write(self.style.WARNING(
                'secrets are over 90 days old — consider rotating.'))
