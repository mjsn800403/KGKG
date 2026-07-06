import secrets

from django.db import models
from django.contrib.auth.hashers import make_password, check_password


class Car(models.Model):
    brand_name = models.TextField()
    car_name = models.TextField()
    year = models.IntegerField()
    db_address = models.TextField()
    
    class Meta:
        db_table = 'main_db'  # Your actual table name


class PurchaseRequest(models.Model):
    """A legal-entity request to purchase technical documentation for a vehicle.

    The sales team follows up on these; the public form (frontend /purchase)
    writes here and the buyer sees a "we'll contact you" confirmation.
    """
    # Vehicle
    brand = models.CharField(max_length=120)
    model = models.CharField(max_length=200)
    year = models.CharField(max_length=20)
    # Requested documents (list of ids: parts / manual / standard_time /
    # special_tools / full_spec) stored as JSON so it stays flexible.
    documents = models.JSONField(default=list, blank=True)
    # Legal-entity contact
    company = models.CharField(max_length=200)
    landline = models.CharField(max_length=40)
    mobile = models.CharField(max_length=40)
    reg_no = models.CharField('registration number', max_length=60)
    note = models.TextField(blank=True, default='')
    # Sizing info — matters to the security/licensing team: how big is the
    # buyer, and for how many seats do they actually want access?
    employees_count = models.PositiveIntegerField(null=True, blank=True)
    seats_count = models.PositiveIntegerField(null=True, blank=True)
    # Per-role seat breakdown: [{role, department, count, note}, ...]
    seat_plan = models.JSONField(default=list, blank=True)
    # Optional extras (not part of the core documentation packages).
    wants_demo = models.BooleanField(default=False)
    wants_ai_assistant = models.BooleanField(default=False)
    # Bookkeeping
    STATUS_CHOICES = [
        ('new', 'جدید'),
        ('reviewing', 'در حال بررسی'),
        ('approved', 'تأیید شده'),
        ('rejected', 'رد شده'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new')
    handled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.company} — {self.brand} {self.model} {self.year}'


# ---------------------------------------------------------------------------
# Access control: Company -> PortalUser (role) -> per-user car/doc grants.
# ---------------------------------------------------------------------------

from .access import DOC_TYPE_CHOICES, ROLE_CHOICES  # noqa: E402


class Company(models.Model):
    """A legal entity that bought (or is evaluating) documentation access."""
    name = models.CharField(max_length=200, unique=True)
    # Configurable department label — hierarchy stays the same (e.g. گارانتی).
    department_label = models.CharField(max_length=80, default='خدمات پس از فروش')
    reg_no = models.CharField(max_length=60, blank=True, default='')
    landline = models.CharField(max_length=40, blank=True, default='')
    mobile = models.CharField(max_length=40, blank=True, default='')
    employees_count = models.PositiveIntegerField(null=True, blank=True)
    seats_count = models.PositiveIntegerField(null=True, blank=True)
    is_demo = models.BooleanField(default=False)
    ai_assistant_enabled = models.BooleanField(default=False)
    active = models.BooleanField(default=True)
    note = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class CompanyCarAccess(models.Model):
    """What a company purchased: which car, and which document layers.

    Per-user grants must stay inside the company's purchased scope.
    """
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='car_accesses')
    car = models.ForeignKey(Car, on_delete=models.CASCADE, related_name='+')
    # Subset of DOC_TYPE_CHOICES ids; empty list == all purchased layers.
    documents = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('company', 'car')]

    def __str__(self):
        return f'{self.company.name} → {self.car.brand_name} {self.car.car_name} {self.car.year}'


class PortalUser(models.Model):
    """A seat the admin issues under a company, tied to an organisational role."""
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='users')
    username = models.CharField(max_length=100, unique=True)
    password_hash = models.CharField(max_length=256)
    display_name = models.CharField(max_length=150, blank=True, default='')
    role = models.CharField(max_length=40, choices=ROLE_CHOICES)
    ai_assistant_enabled = models.BooleanField(default=False)
    active = models.BooleanField(default=True)
    locked = models.BooleanField(default=False)
    access_expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_login_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['company__name', 'username']

    def set_password(self, raw):
        self.password_hash = make_password(raw)

    def check_password(self, raw):
        return check_password(raw, self.password_hash)

    def __str__(self):
        return f'{self.username} ({self.company.name})'


class UserCarAccess(models.Model):
    """Per-user grant: which of the company's purchased cars this user sees,
    and which document layers within them (subset of the company grant)."""
    user = models.ForeignKey(PortalUser, on_delete=models.CASCADE, related_name='car_accesses')
    car = models.ForeignKey(Car, on_delete=models.CASCADE, related_name='+')
    documents = models.JSONField(default=list, blank=True)
    # Admin-assigned grants bypass purchase limits (admin always wins).
    admin_granted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('user', 'car')]

    def __str__(self):
        return f'{self.user.username} → {self.car.car_name}'


class AuthToken(models.Model):
    """Opaque bearer token for portal users (simple, DB-backed sessions)."""
    key = models.CharField(max_length=64, unique=True)
    user = models.ForeignKey(PortalUser, on_delete=models.CASCADE, related_name='tokens')
    created_at = models.DateTimeField(auto_now_add=True)

    @classmethod
    def issue(cls, user):
        return cls.objects.create(key=secrets.token_hex(32), user=user)

    def __str__(self):
        return f'token:{self.user.username}'


class ActivityLog(models.Model):
    """What users are doing — the admin's usage report."""
    user = models.ForeignKey(PortalUser, on_delete=models.CASCADE, related_name='activities')
    action = models.CharField(max_length=60)          # login / view_car / search / assist ...
    detail = models.CharField(max_length=400, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user.username}: {self.action}'


class PlatformAdmin(models.Model):
    """Platform superuser (separate from company portal seats)."""
    username = models.CharField(max_length=100, unique=True)
    password_hash = models.CharField(max_length=256)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def set_password(self, raw):
        self.password_hash = make_password(raw)

    def check_password(self, raw):
        return check_password(raw, self.password_hash)

    def __str__(self):
        return self.username


class AdminAuthToken(models.Model):
    """Session token issued after platform-admin username/password login."""
    key = models.CharField(max_length=64, unique=True)
    admin = models.ForeignKey(PlatformAdmin, on_delete=models.CASCADE, related_name='tokens')
    created_at = models.DateTimeField(auto_now_add=True)

    @classmethod
    def issue(cls, admin):
        return cls.objects.create(key=secrets.token_hex(32), admin=admin)

    def __str__(self):
        return f'admin-token:{self.admin.username}'