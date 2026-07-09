"""Shared RBAC, subscription package, and AI eligibility helpers."""

# Top-down hierarchy (1 = highest). Department name is configurable per company;
# the level numbers never change.
ROLE_CHOICES = [
    ('after_sales_manager', 'مدیر خدمات پس از فروش'),
    ('after_sales_head', 'رئیس خدمات پس از فروش'),
    ('after_sales_supervisor', 'سرپرست خدمات پس از فروش'),
    ('after_sales_specialist', 'کارشناس خدمات پس از فروش'),
]

ROLE_LEVEL = {
    'after_sales_manager': 1,
    'after_sales_head': 2,
    'after_sales_supervisor': 3,
    'after_sales_specialist': 4,
}

# Legacy role ids mapped to the new hierarchy (migration + runtime tolerance).
LEGACY_ROLE_MAP = {
    'technical_expert': 'after_sales_specialist',
    'technical_staff': 'after_sales_specialist',
}

# Subscription packages (modular — add new ids here and in DOC_TYPE_CHOICES).
PACKAGE_CHOICES = [
    ('manual', 'راهنمای تعمیرات'),
    ('special_tools', 'ابزارهای مخصوص'),
    ('parts', 'کاتالوگ قطعات یدکی'),
    ('standard_time', 'زمان استاندارد تعمیرات'),
    ('full_spec', 'مشخصات کامل خودرو'),
]

DOC_TYPE_CHOICES = PACKAGE_CHOICES  # same ids, used in car/doc grants

VALID_PACKAGES = {p for p, _ in PACKAGE_CHOICES}
VALID_DOCS = VALID_PACKAGES
VALID_ROLES = {r for r, _ in ROLE_CHOICES}

AI_REQUIRED_PACKAGE = 'manual'


def normalize_role(role):
    return LEGACY_ROLE_MAP.get(role, role)


def role_label(role, department_label=''):
    rid = normalize_role(role)
    base = dict(ROLE_CHOICES).get(rid, rid)
    if department_label and department_label != 'خدمات پس از فروش':
        return base.replace('خدمات پس از فروش', department_label)
    return base


def role_can_manage(actor_role, target_role):
    """Higher-level roles inherit authority over lower-level roles."""
    a = ROLE_LEVEL.get(normalize_role(actor_role), 99)
    t = ROLE_LEVEL.get(normalize_role(target_role), 99)
    return a < t


def effective_documents(access_row, company_scope=None):
    """Resolved package list for one car grant."""
    docs = access_row.documents or []
    if docs:
        return [d for d in docs if d in VALID_PACKAGES]
    if company_scope is not None:
        return [d for d in company_scope if d in VALID_PACKAGES]
    return list(VALID_PACKAGES)


def user_package_set(user):
    """All subscription packages a user effectively holds (any car)."""
    pkgs = set()
    company_scope = {
        a.car_id: (a.documents or list(VALID_PACKAGES))
        for a in user.company.car_accesses.all()
    }
    for a in user.car_accesses.select_related('car'):
        if a.admin_granted:
            pkgs.update(effective_documents(a))
        elif a.car_id in company_scope:
            scope = company_scope[a.car_id] or list(VALID_PACKAGES)
            pkgs.update(effective_documents(a, scope))
    return pkgs


def parse_seat_plan(raw):
    """Validate and normalize seat_plan rows from a purchase request.

    Returns (rows, total_seats) on success or (None, error_message) on failure.
    """
    if not isinstance(raw, list) or not raw:
        return None, 'حداقل یک نقش/واحد سازمانی را مشخص کنید.'
    rows = []
    total = 0
    for item in raw[:50]:
        if not isinstance(item, dict):
            continue
        role = normalize_role(str(item.get('role') or '').strip())
        if role not in VALID_ROLES:
            return None, 'نقش سازمانی نامعتبر است.'
        department = (str(item.get('department') or 'خدمات پس از فروش')).strip()[:80]
        try:
            count = int(item.get('count'))
            if count < 1 or count > 1000:
                return None, 'تعداد کاربر هر نقش باید بین ۱ تا ۱۰۰۰ باشد.'
        except (TypeError, ValueError):
            return None, 'تعداد کاربر هر نقش الزامی است.'
        note = (str(item.get('note') or '')).strip()[:500]
        rows.append({'role': role, 'department': department, 'count': count, 'note': note})
        total += count
    if not rows:
        return None, 'حداقل یک نقش/واحد سازمانی را مشخص کنید.'
    return rows, total


def user_ai_eligible(user):
    """AI requires Repair Manual (manual) in the user's effective packages."""
    if not user.ai_assistant_enabled:
        return False
    if not user.company.ai_assistant_enabled:
        return False
    return AI_REQUIRED_PACKAGE in user_package_set(user)


def car_db_path(car):
    """Absolute path to a car's content database on this server."""
    from django.conf import settings
    from pathlib import Path
    main_dir = Path(settings.DATABASES['default']['NAME']).parent
    return main_dir / (car.db_address or '').replace('\\', '/')


def car_db_ready(car):
    """True when the car's per-vehicle database file exists on disk."""
    path = car_db_path(car)
    return bool(car.db_address) and path.is_file()
