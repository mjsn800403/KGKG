"""Company-defined organisational hierarchy (OrgRole) + PortalUser.org_role.

Seeds every existing company with the 4 canonical after-sales positions
(matching the legacy fixed ladder) and points each user's ``org_role`` at the
seeded position that corresponds to their legacy ``role``. Idempotent per
company (unique (company, name)).
"""
from django.db import migrations, models
import django.db.models.deletion


# Legacy ladder -> seed data. Mirrors access.ROLE_CHOICES / ROLE_LEVEL /
# default_capabilities_for_role at the time of this migration (frozen here on
# purpose — migrations must not drift with later code changes).
_SEED = [
    # (rank, legacy_id, base_name, scope, manage, analytics, color)
    (1, 'after_sales_manager', 'مدیر خدمات پس از فروش', 'org', True, True, '#e8b04b'),
    (2, 'after_sales_head', 'رئیس خدمات پس از فروش', 'org', True, True, '#7c6cf0'),
    (3, 'after_sales_supervisor', 'سرپرست خدمات پس از فروش', 'org', False, True, '#4bb3e8'),
    (4, 'after_sales_specialist', 'کارشناس خدمات پس از فروش', 'none', False, False, '#5ecf8a'),
]

_LEGACY_MAP = {
    'technical_expert': 'after_sales_specialist',
    'technical_staff': 'after_sales_specialist',
}


def seed_org_roles(apps, schema_editor):
    Company = apps.get_model('api', 'Company')
    OrgRole = apps.get_model('api', 'OrgRole')
    PortalUser = apps.get_model('api', 'PortalUser')

    for company in Company.objects.all():
        dept = (company.department_label or '').strip()
        by_legacy = {}
        for rank, legacy_id, base_name, scope, manage, analytics, color in _SEED:
            name = base_name
            if dept and dept != 'خدمات پس از فروش':
                name = base_name.replace('خدمات پس از فروش', dept)
            role, _created = OrgRole.objects.get_or_create(
                company=company, name=name,
                defaults={
                    'rank': rank, 'manage_scope': scope,
                    'can_manage_team': manage, 'can_view_analytics': analytics,
                    'ai_assistant_enabled': True, 'color': color,
                })
            by_legacy[legacy_id] = role
        for user in PortalUser.objects.filter(company=company, org_role__isnull=True):
            legacy = _LEGACY_MAP.get(user.role, user.role)
            role = by_legacy.get(legacy)
            if role is not None:
                user.org_role = role
                user.save(update_fields=['org_role'])


def unseed_org_roles(apps, schema_editor):
    # Dropping the tables in the reverse schema operation is enough.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0009_pipelinesettings_processingjob'),
    ]

    operations = [
        migrations.CreateModel(
            name='OrgRole',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=80)),
                ('rank', models.PositiveIntegerField(default=1)),
                ('manage_scope', models.CharField(choices=[('org', 'همه رده‌های پایین‌تر'), ('subtree', 'فقط زیرمجموعه مستقیم'), ('none', 'بدون دسترسی مدیریتی')], default='org', max_length=12)),
                ('can_manage_team', models.BooleanField(default=False)),
                ('can_view_analytics', models.BooleanField(default=False)),
                ('ai_assistant_enabled', models.BooleanField(default=True)),
                ('color', models.CharField(blank=True, default='', max_length=16)),
                ('default_accesses', models.JSONField(blank=True, default=list)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('company', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='org_roles', to='api.company')),
            ],
            options={
                'ordering': ['company_id', 'rank', 'id'],
            },
        ),
        migrations.AddField(
            model_name='portaluser',
            name='org_role',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='members', to='api.orgrole'),
        ),
        migrations.AddIndex(
            model_name='orgrole',
            index=models.Index(fields=['company', 'rank'], name='api_orgrole_company_rank_idx'),
        ),
        migrations.AlterUniqueTogether(
            name='orgrole',
            unique_together={('company', 'name')},
        ),
        migrations.RunPython(seed_org_roles, unseed_org_roles),
    ]
