import datetime
import hashlib
import secrets

from django.db import models
from django.contrib.auth.hashers import make_password, check_password
from django.utils import timezone


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
    """A seat under a company, tied to an organisational role.

    Historically only the platform admin issued these. They can now also be
    created self-service by a company manager (``can_manage_team``): the new
    employee is emailed an invite and sets their own password. ``role`` still
    drives the label + ``ROLE_LEVEL`` hierarchy; feature access is per-user
    (the capability flags below + per-car grants in ``UserCarAccess``).
    """
    INVITE_STATUS_CHOICES = [
        ('active', 'فعال'),        # normal user with a password set
        ('invited', 'دعوت‌شده'),   # invited, hasn't accepted / set a password yet
        ('disabled', 'غیرفعال'),
    ]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='users')
    username = models.CharField(max_length=100, unique=True)
    email = models.EmailField(max_length=254, unique=True, null=True, blank=True)
    phone = models.CharField(max_length=40, blank=True, default='')
    personnel_code = models.CharField(max_length=60, blank=True, default='')
    password_hash = models.CharField(max_length=256)
    display_name = models.CharField(max_length=150, blank=True, default='')
    role = models.CharField(max_length=40, choices=ROLE_CHOICES)
    # Explicit org hierarchy: who this person reports to (same company).
    reports_to = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True, related_name='reports')
    # Per-user capabilities (seeded from role at creation, individually editable).
    can_manage_team = models.BooleanField(default=False)
    can_view_analytics = models.BooleanField(default=False)
    ai_assistant_enabled = models.BooleanField(default=False)
    active = models.BooleanField(default=True)
    locked = models.BooleanField(default=False)
    # Invite lifecycle. ``password_set`` gates login: an invited user cannot log
    # in until they accept the invite and choose a password.
    invite_status = models.CharField(max_length=20, choices=INVITE_STATUS_CHOICES, default='active')
    password_set = models.BooleanField(default=True)
    invited_by = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True, related_name='invited_users')
    access_expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_login_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['company__name', 'username']

    def set_password(self, raw):
        self.password_hash = make_password(raw)
        self.password_set = True

    def check_password(self, raw):
        return check_password(raw, self.password_hash)

    def set_unusable_password(self):
        """Invited-but-not-accepted users get an unusable hash (no login)."""
        self.password_hash = make_password(None)
        self.password_set = False

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


class InviteToken(models.Model):
    """Single-use, expiring invite for a self-service-created employee.

    Only the sha256 of the opaque token is stored; the raw token is returned
    once (put in the invite link) and never persisted.
    """
    DEFAULT_TTL = datetime.timedelta(days=7)

    key_hash = models.CharField(max_length=64, unique=True, db_index=True)
    user = models.ForeignKey(PortalUser, on_delete=models.CASCADE, related_name='invites')
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    @staticmethod
    def _hash(raw):
        return hashlib.sha256(raw.encode('utf-8')).hexdigest()

    @classmethod
    def issue(cls, user, ttl=None):
        """Create a fresh invite, invalidating any prior unused ones.

        Returns (instance, raw_token). Store only the instance; hand the raw
        token to the user via the invite link.
        """
        cls.objects.filter(user=user, used_at__isnull=True).delete()
        raw = secrets.token_urlsafe(32)
        obj = cls.objects.create(
            key_hash=cls._hash(raw), user=user,
            expires_at=timezone.now() + (ttl or cls.DEFAULT_TTL),
        )
        return obj, raw

    @classmethod
    def resolve(cls, raw):
        """Return a live (unused, unexpired) token for ``raw``, or None."""
        if not raw:
            return None
        obj = cls.objects.filter(key_hash=cls._hash(raw)).select_related('user', 'user__company').first()
        if not obj or obj.used_at is not None or obj.expires_at <= timezone.now():
            return None
        return obj

    def consume(self):
        self.used_at = timezone.now()
        self.save(update_fields=['used_at'])

    def __str__(self):
        return f'invite:{self.user.username}'


class ActivityLog(models.Model):
    """What users are doing — powers the usage report and analytics.

    ``category`` is a canonical content-category id (see access.CONTENT_CATEGORIES,
    e.g. engine / body / electrical) so usage can be sliced by technical area.
    """
    user = models.ForeignKey(PortalUser, on_delete=models.CASCADE, related_name='activities')
    action = models.CharField(max_length=60)          # login / view_car / view_node / search / assist ...
    detail = models.CharField(max_length=400, blank=True, default='')
    category = models.CharField(max_length=40, blank=True, default='', db_index=True)
    car = models.ForeignKey(Car, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    node_title = models.CharField(max_length=300, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['category', 'created_at']),
            models.Index(fields=['created_at']),
        ]

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


# ---------------------------------------------------------------------------
# Data quality / observability
# ---------------------------------------------------------------------------

class DataQualityRun(models.Model):
    """One full audit pass over the vehicle warehouse (see api/dataquality.py).

    The audit walks every per-car database, measures section completeness
    against the canonical manual schema, fingerprints content to detect
    duplicate vehicles, and cross-checks catalog / static assets / RAG
    coverage. Results are persisted here so the admin report is instant —
    scanning ~18GB of SQLite takes a minute+, far too slow for a request.
    """
    STATUS_CHOICES = [
        ('running', 'running'),
        ('done', 'done'),
        ('failed', 'failed'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='running')
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    # Aggregate counters: vehicles seen, complete, incomplete, duplicates, ...
    summary = models.JSONField(default=dict, blank=True)
    # Per-vehicle detail rows: [{stem, status, sections, missing, ...}, ...]
    vehicles = models.JSONField(default=list, blank=True)
    # Fix actions taken (when run with fix=True) or recommended.
    actions = models.JSONField(default=list, blank=True)
    error = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        return f'audit {self.started_at:%Y-%m-%d %H:%M} [{self.status}]'


class TrafficStat(models.Model):
    """Per-endpoint-group traffic rollup, one row per (bucket, endpoint).

    Written by api/monitoring.py's middleware flusher — requests are counted
    in memory and flushed periodically, so serving traffic never does a
    per-request write to the main DB (SQLite write contention stays near zero
    and the table grows by rows/hour, not rows/request — this is what keeps
    analytics viable at much larger traffic volumes).
    """
    bucket = models.DateTimeField(db_index=True)        # start of the hour (UTC)
    endpoint = models.CharField(max_length=80)          # normalized route group
    method = models.CharField(max_length=8, default='GET')
    requests = models.PositiveIntegerField(default=0)
    errors_4xx = models.PositiveIntegerField(default=0)
    errors_5xx = models.PositiveIntegerField(default=0)
    total_ms = models.BigIntegerField(default=0)        # sum of latencies
    max_ms = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = [('bucket', 'endpoint', 'method')]
        indexes = [models.Index(fields=['bucket'])]

    def __str__(self):
        return f'{self.bucket:%Y-%m-%d %H} {self.endpoint} n={self.requests}'


class VisitorSeen(models.Model):
    """One row per (day, salted-ip-hash): the exact daily-unique-visitor set.

    INSERT OR IGNOREd in batches by the metrics flusher, so uniqueness is
    correct across all gunicorn workers (an in-memory set per worker would
    overcount). Rows are pruned after ~90 days by check_alerts. The hash is
    salted with SECRET_KEY and truncated — it cannot be reversed to an IP.
    """
    day = models.DateField(db_index=True)
    ip_hash = models.CharField(max_length=32)

    class Meta:
        unique_together = [('day', 'ip_hash')]


class SystemAlert(models.Model):
    """An operational alert raised by the monitoring checks (api/monitoring.py
    evaluate_alerts / the check_alerts management command).

    De-duplicated by ``key``: an ongoing condition updates its open alert
    instead of raising a new row every check cycle. Resolved automatically
    when the condition clears.
    """
    SEVERITY_CHOICES = [('info', 'info'), ('warning', 'warning'), ('critical', 'critical')]
    key = models.CharField(max_length=120, db_index=True)   # e.g. 'disk_high', 'error_rate:assist'
    severity = models.CharField(max_length=12, choices=SEVERITY_CHOICES, default='warning')
    message = models.TextField()
    context = models.JSONField(default=dict, blank=True)
    is_open = models.BooleanField(default=True, db_index=True)
    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-last_seen']

    def __str__(self):
        return f'[{self.severity}] {self.key}'