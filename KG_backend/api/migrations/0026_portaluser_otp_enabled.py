from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0025_qa11_allcars_quota_adminotp'),
    ]

    operations = [
        migrations.AddField(
            model_name='portaluser',
            name='otp_enabled',
            field=models.BooleanField(default=True),
        ),
    ]
