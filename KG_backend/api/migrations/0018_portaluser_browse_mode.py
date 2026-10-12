from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0017_hash_session_tokens'),
    ]

    operations = [
        migrations.AddField(
            model_name='portaluser',
            name='browse_mode',
            field=models.CharField(default='modern', max_length=10),
        ),
    ]
