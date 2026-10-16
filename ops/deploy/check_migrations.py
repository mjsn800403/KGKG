"""Refuse migrations the previous release cannot run against.

A deploy rollback puts the old code back but never reverses migrations, so
every new migration must leave a schema the PREVIOUS code still works with.
This flags the operations that break that, in migration files added since
<base-ref> (normally the live production commit):

  * RemoveField / DeleteModel / RenameField / RenameModel: old code still
    reads and writes the old names;
  * AddField that is NOT NULL with no db_default: old code inserts rows
    without the column (this is what broke the first rollback, ChatLog.flags);
  * AlterField / RunSQL: may or may not be safe, so a human has to say so.

A reviewed migration opts out with a line `# deploy-safety: reviewed <why>`.

Usage (from KG_backend/, Django settings importable):
    python ../ops/deploy/check_migrations.py <base-ref>      exit 1 = unsafe
"""
import importlib
import os
import re
import subprocess
import sys

import django

sys.path.insert(0, os.getcwd())  # run from KG_backend/

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'KG_backend.settings')
django.setup()

from django.db import migrations  # noqa: E402
from django.db.models import NOT_PROVIDED, ManyToManyField  # noqa: E402

RENAMES_AND_DROPS = (migrations.RemoveField, migrations.DeleteModel,
                     migrations.RenameField, migrations.RenameModel)
NEEDS_REVIEW = (migrations.AlterField, migrations.RunSQL)
REVIEWED = re.compile(r'^#\s*deploy-safety:\s*reviewed\b', re.M)


def problems(operations):
    for op in operations:
        name = type(op).__name__
        if isinstance(op, RENAMES_AND_DROPS):
            yield f'{name} {getattr(op, "name", "")}: the previous release still uses it'
        elif isinstance(op, migrations.AddField):
            f = op.field
            if (not f.null and not isinstance(f, ManyToManyField)
                    and getattr(f, 'db_default', NOT_PROVIDED) is NOT_PROVIDED):
                yield (f'AddField {op.model_name}.{op.name}: NOT NULL without db_default '
                       '(old code would fail to insert rows); use null=True or db_default=')
        elif isinstance(op, NEEDS_REVIEW):
            yield f'{name}: check the previous release still works, then mark it reviewed'


def main(base):
    added = subprocess.run(
        ['git', 'diff', '--name-only', '--diff-filter=A', base, 'HEAD', '--', '*/migrations/0*.py'],
        capture_output=True, text=True, check=True).stdout.split()
    bad = 0
    for path in added:
        rel = path.split('KG_backend/', 1)[-1]
        with open(rel) as fh:
            if REVIEWED.search(fh.read()):
                print(f'reviewed  {rel}')
                continue
        mod = importlib.import_module(rel[:-3].replace('/', '.'))
        found = list(problems(mod.Migration.operations))
        for p in found:
            print(f'UNSAFE    {rel}: {p}')
        bad += bool(found)
        if not found:
            print(f'ok        {rel}')
    if not added:
        print('no new migrations')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))
