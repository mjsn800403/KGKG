from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0032_search_log'),
    ]

    operations = [
        migrations.AddField(model_name='chatlog', name='client_key',
                            field=models.CharField(blank=True, db_index=True, default='', max_length=40)),
        migrations.AddField(model_name='chatlog', name='feedback',
                            field=models.SmallIntegerField(blank=True, null=True)),
        migrations.AddField(model_name='chatlog', name='feedback_reason',
                            field=models.CharField(blank=True, default='', max_length=20)),
        migrations.AddField(model_name='chatlog', name='feedback_comment',
                            field=models.TextField(blank=True, default='')),
        migrations.AddField(model_name='chatlog', name='feedback_at',
                            field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name='chatlog', name='copied',
                            field=models.BooleanField(default=False)),
        migrations.AddField(model_name='chatlog', name='source_clicks',
                            field=models.IntegerField(default=0)),
        migrations.AddField(model_name='chatlog', name='rephrased',
                            field=models.BooleanField(default=False)),
    ]
