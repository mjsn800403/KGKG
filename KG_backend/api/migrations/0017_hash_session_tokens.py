"""Hash session tokens at rest and give them an expiry.

Both AuthToken and AdminAuthToken stored their bearer value in plaintext and
never expired, so a copy of db.sqlite3 (which lived in git history for a while)
was a set of permanent, ready-to-use sessions.

The old plaintext rows are deleted rather than migrated to hashes on purpose:
re-hashing them would keep already-leaked bearer values working, which is the
exact problem this migration exists to end. Everyone signs in once more.
"""
import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


def drop_plaintext_sessions(apps, schema_editor):
    """Revoke every pre-hash session. See the module docstring for why."""
    for name in ('AuthToken', 'AdminAuthToken'):
        apps.get_model('api', name).objects.all().delete()


def noop_reverse(apps, schema_editor):
    """Nothing to restore — the raw keys were never recoverable."""


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0016_remove_portaluser_org_role_delete_orgrole'),
    ]

    operations = [
        # Must run first: the table is emptied before the unique key_hash column
        # is added, so there are no rows needing a backfilled value.
        migrations.RunPython(drop_plaintext_sessions, noop_reverse),

        migrations.RemoveField(model_name='authtoken', name='key'),
        migrations.RemoveField(model_name='adminauthtoken', name='key'),

        migrations.AddField(
            model_name='authtoken',
            name='key_hash',
            field=models.CharField(db_index=True, default='', max_length=64, unique=True),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='authtoken',
            name='last_used_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='authtoken',
            name='expires_at',
            field=models.DateTimeField(db_index=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),

        migrations.AddField(
            model_name='adminauthtoken',
            name='key_hash',
            field=models.CharField(db_index=True, default='', max_length=64, unique=True),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='adminauthtoken',
            name='last_used_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='adminauthtoken',
            name='expires_at',
            field=models.DateTimeField(db_index=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),

        migrations.AlterModelOptions(
            name='authtoken', options={'ordering': ['-created_at']},
        ),
        migrations.AlterModelOptions(
            name='adminauthtoken', options={'ordering': ['-created_at']},
        ),
    ]
