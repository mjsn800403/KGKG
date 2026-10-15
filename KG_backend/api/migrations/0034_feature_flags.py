from django.db import migrations, models


def seed(apps, schema_editor):
    # The Persian query-translation experiment (RAG_MQ_TRANSLATE in the chat
    # route), seeded OFF so behaviour is unchanged until an admin enables it.
    FeatureFlag = apps.get_model('api', 'FeatureFlag')
    FeatureFlag.objects.get_or_create(key='mq_translate', defaults={
        'description': 'ترجمهٔ پرسش فارسی به انگلیسی پیش از جستجو در دستیار (RAG_MQ_TRANSLATE)',
        'enabled': False, 'rollout_pct': 0})


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0033_chatlog_behavior'),
    ]

    operations = [
        migrations.AddField(
            model_name='chatlog',
            name='flags',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.CreateModel(
            name='FeatureFlag',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.CharField(max_length=60, unique=True)),
                ('description', models.CharField(blank=True, default='', max_length=300)),
                ('enabled', models.BooleanField(default=False)),
                ('rollout_pct', models.PositiveSmallIntegerField(default=0)),
                ('force_on', models.JSONField(blank=True, default=list)),
                ('force_off', models.JSONField(blank=True, default=list)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'ordering': ['key']},
        ),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
