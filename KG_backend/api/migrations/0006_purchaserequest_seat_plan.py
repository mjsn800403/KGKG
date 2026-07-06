from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0005_rbac_packages_platform_admin"),
    ]

    operations = [
        migrations.AddField(
            model_name="purchaserequest",
            name="seat_plan",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
