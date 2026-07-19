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


class OrgRole(models.Model):
    """A company-defined position in its own organisational hierarchy.

    Companies are not forced into the fixed 4-level after-sales ladder any
    more: a manager can create, rename, re-rank and delete positions freely.
    ``rank`` orders the hierarchy (1 = top; a smaller rank outranks a larger
    one). ``manage_scope`` decides WHO a member of this position can see and
    manage in the team area:

      * ``org``     — everyone in the company with a strictly larger rank
                      (e.g. the head sees every supervisor/specialist,
                      regardless of reporting lines, but never the manager);
      * ``subtree`` — only people who transitively report to them;
      * ``none``    — nobody (a pure member).

    The capability flags are the DEFAULTS seeded onto new members of the
    position (each member's own flags stay individually editable), and
    ``default_accesses`` is an optional car/package template applied to new
    members (and bulk-applicable to existing ones).
    """
    MANAGE_SCOPE_CHOICES = [
        ('org', 'همه رده‌های پایین‌تر'),
        ('subtree', 'فقط زیرمجموعه مستقیم'),
        ('none', 'بدون دسترسی مدیریتی'),
    ]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='org_roles')
    name = models.CharField(max_length=80)
    rank = models.PositiveIntegerField(default=1)
    manage_scope = models.CharField(max_length=12, choices=MANAGE_SCOPE_CHOICES, default='org')
    can_manage_team = models.BooleanField(default=False)
    can_view_analytics = models.BooleanField(default=False)
    ai_assistant_enabled = models.BooleanField(default=True)
    # UI accent for the org chart / badges (hex like '#7c6cf0' or named token).
    color = models.CharField(max_length=16, blank=True, default='')
    # Access template: [{car_id, documents: [...]}, ...]. Applied (clamped to
    # the granting manager's own scope) when a member joins the position.
    default_accesses = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['company_id', 'rank', 'id']
        unique_together = [('company', 'name')]
        indexes = [models.Index(fields=['company', 'rank'])]

    def __str__(self):
        return f'{self.company.name} · {self.name} (rank {self.rank})'


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
    # The company-defined position (see OrgRole). ``role`` stays as a legacy
    # fallback/compat label; when ``org_role`` is set it wins everywhere.
    org_role = models.ForeignKey(
        OrgRole, on_delete=models.SET_NULL, null=True, blank=True, related_name='members')
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
    # In-app URL of the viewed content (when applicable) so the recommendation
    # engine can offer exact "continue reading" / "related section" deep-links.
    app_url = models.CharField(max_length=600, blank=True, default='')
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


class ProcessingJob(models.Model):
    """One admin-triggered (or automatic) run of the data-processing pipeline.

    The heavy work (RAG embedding, diagnostic sidecars) runs in a DETACHED
    worker process — its own systemd transient unit when available — so it
    survives gunicorn restarts, admin browser disconnects, and deploys. This
    row is the single source of truth the admin panel polls: the worker
    heartbeats progress into it, and the pipeline_tick watchdog uses it to
    detect stalls and resume. See api/pipeline.py.
    """
    STATUS_CHOICES = [
        ('pending', 'pending'),        # created, about to be launched
        ('scheduled', 'scheduled'),    # will start at scheduled_for
        ('running', 'running'),
        ('paused', 'paused'),          # stopped gracefully (cancel/SIGTERM); resumable
        ('stalled', 'stalled'),        # worker died without finishing; resumable
        ('done', 'done'),
        ('failed', 'failed'),
        ('canceled', 'canceled'),
    ]
    TRIGGER_CHOICES = [('manual', 'manual'), ('auto', 'auto'), ('schedule', 'schedule')]

    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='pending', db_index=True)
    trigger = models.CharField(max_length=16, choices=TRIGGER_CHOICES, default='manual')
    scheduled_for = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    # Worker identity — used by the watchdog (liveness) and cancel (stop).
    pid = models.IntegerField(null=True, blank=True)
    unit_name = models.CharField(max_length=120, blank=True, default='')
    attempts = models.PositiveIntegerField(default=0)
    # Per-stage state: [{key, label, status, items_total, items_done, error, ...}]
    stages = models.JSONField(default=list, blank=True)
    # Live progress the admin panel renders: {overall_pct, stage, eta_s, rate, ...}
    progress = models.JSONField(default=dict, blank=True)
    log_tail = models.TextField(blank=True, default='')
    error = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-created_at']

    RESUMABLE = ('paused', 'stalled', 'failed')
    # "Active" = occupying the single execution slot NOW. A job scheduled for
    # later does not block starting/resuming other work; the scheduler simply
    # retries it at its time until the slot is free.
    ACTIVE = ('pending', 'running')

    def __str__(self):
        return f'job #{self.id} [{self.status}]'


class PipelineSettings(models.Model):
    """Singleton knobs for automatic background processing (row id=1).

    ``auto_enabled``: when new vehicle data lands in the warehouse, the
    pipeline_tick timer starts processing by itself — but only while the
    server is quiet (1-min load per core below ``load_threshold``).
    Observed throughput fields are updated by finished jobs so duration
    estimates shown to the admin come from THIS server's real history,
    not guesses.
    """
    auto_enabled = models.BooleanField(default=True)
    load_threshold = models.FloatField(default=0.55)     # load1/cores gate for auto starts
    auto_resume = models.BooleanField(default=True)      # watchdog relaunches stalled jobs
    # Max-power mode: run the pipeline worker at normal OS priority and use
    # (almost) all CPU cores for parallel ZIP parsing + embedding — much faster,
    # but competes with live serving. Off (default) keeps the worker low-priority
    # (Nice/idle-IO) and reserves cores so the site always stays responsive.
    max_power = models.BooleanField(default=False)
    embed_rate_pps = models.FloatField(default=1.5)      # observed pages/second
    diag_secs_per_car = models.FloatField(default=90.0)  # observed seconds/car
    parse_secs_per_zip = models.FloatField(default=180.0)        # observed seconds/zip (parse stage)
    download_secs_per_vehicle = models.FloatField(default=120.0)  # observed seconds/vehicle (download stage)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(id=1)
        return obj


class DownloadRequest(models.Model):
    """A queued request to fetch vehicle-manual ZIPs from the LEMON source site.

    Created from the admin panel (optionally narrowed by ``name_filter``, e.g.
    'corolla cross'); executed by the pipeline worker's download stage, which
    lists the Brand/Year page, downloads each matching vehicle's ZIP into the
    inbox, and registers the ZIPs as ZipPackage rows for the parse stage.
    ``listing`` snapshots the per-vehicle state so the panel can show exactly
    which vehicles were fetched/skipped/failed.
    """
    STATUS_CHOICES = [
        ('pending', 'pending'), ('running', 'running'), ('done', 'done'),
        ('failed', 'failed'), ('canceled', 'canceled'),
    ]
    url = models.TextField()                                     # Brand/Year page URL
    brand = models.CharField(max_length=40, blank=True, default='')
    year = models.IntegerField(null=True, blank=True)
    name_filter = models.CharField(max_length=120, blank=True, default='')
    status = models.CharField(max_length=12, choices=STATUS_CHOICES,
                              default='pending', db_index=True)
    # [{name, bundle_url, state: pending|ok|skip|fail}] — filled at creation
    # (from the source listing) and updated per vehicle by the worker.
    listing = models.JSONField(default=list, blank=True)
    vehicles_total = models.IntegerField(default=0)
    vehicles_done = models.IntegerField(default=0)
    error = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    ACTIVE = ('pending', 'running')

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'download #{self.id} {self.brand} {self.year} [{self.status}]'


class ZipPackage(models.Model):
    """One vehicle-manual ZIP discovered in the inbox — the parse queue.

    Registered by ``scan_zips`` (or by the download stage right after a
    fetch). Identity is the absolute path; a changed size/mtime resets a
    non-pending row back to pending so replaced files are reprocessed. The
    duplicate guard marks a ZIP whose target warehouse stem already exists
    (catalog row + .db on disk, or an earlier queued package for the same
    stem) as ``skipped_duplicate`` so re-downloads under new names never
    clobber or duplicate an ingested car.
    """
    STATUS_CHOICES = [
        ('pending', 'pending'),                    # waiting for the parse stage
        ('parsing', 'parsing'),
        ('done', 'done'),
        ('failed', 'failed'),
        ('skipped_duplicate', 'skipped_duplicate'),
    ]
    path = models.TextField(unique=True)           # absolute path of the ZIP
    zip_name = models.CharField(max_length=300)
    size = models.BigIntegerField(default=0)
    mtime = models.FloatField(default=0.0)
    brand = models.CharField(max_length=40, blank=True, default='')
    year = models.IntegerField(null=True, blank=True)
    car_name = models.TextField(blank=True, default='')   # e.g. 'Corolla Cross LE, FWD'
    stem = models.TextField(blank=True, default='')       # warehouse stem (year rule applied)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES,
                              default='pending', db_index=True)
    pages_processed = models.IntegerField(default=0)
    error = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'zip {self.zip_name} [{self.status}]'


class VehicleSpec(models.Model):
    """schema.org-automotive-shaped structured data for one vehicle.

    ``data`` is a schema.org ``Car`` dict (JSON-LD-ready, without @context):
    only fields we can fill RELIABLY are present — an absent key means
    "unknown", never guessed. ``provenance`` records, per dotted field path,
    where the value came from ('catalog' | 'stem' | 'manual' | 'curated') and
    the exact detail (stem token / manual section path), so every value is
    auditable. Built by build_vehicle_schema / the pipeline schema stage from
    the catalog, the name stem, and spec tables parsed out of the repair
    manuals themselves.
    """
    car = models.OneToOneField(Car, on_delete=models.CASCADE, related_name='spec')
    data = models.JSONField(default=dict, blank=True)
    provenance = models.JSONField(default=dict, blank=True)
    sections_used = models.JSONField(default=list, blank=True)  # manual paths parsed
    builder_version = models.CharField(max_length=16, blank=True, default='')
    built_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'spec for {self.car.car_name}'


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


# ---------------------------------------------------------------------------
# Event-driven backbone
# ---------------------------------------------------------------------------

class Event(models.Model):
    """Append-only event log — the spine of the real-time layer.

    Every meaningful state change (new data detected, pipeline progress, a
    company request opened/closed, an alert, a login, an activity) appends one
    row here. The SSE endpoint (api/events.py) tails this table and pushes new
    rows to connected dashboards, so the admin/manager/user UIs update live
    without polling their individual REST endpoints.

    Why a DB table and not an in-process bus: the app runs as several gunicorn
    worker processes plus a DETACHED pipeline worker, and there is no Redis. A
    shared SQLite table (WAL mode) is the one medium every process can both
    write to and tail, and it gives durability + ``Last-Event-ID`` resume for
    free. The autoincrement ``id`` is the monotonic cursor clients resume from.

    ``audience`` scopes delivery; ``company_id`` / ``user_id`` are stored as
    plain integers (not FKs) so an event outlives the row it describes (a
    deleted user's login still shows in history) and emitting stays a single
    cheap INSERT with no integrity lookups.
    """
    AUDIENCE_CHOICES = [
        ('admin', 'admin'),        # platform admins only
        ('company', 'company'),    # everyone in company_id who may see team data
        ('user', 'user'),          # a single portal user (user_id)
        ('all', 'all'),            # broadcast (rare — e.g. global maintenance)
    ]
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    type = models.CharField(max_length=48, db_index=True)   # dotted, e.g. 'request.updated'
    audience = models.CharField(max_length=12, choices=AUDIENCE_CHOICES, default='admin')
    company_id = models.IntegerField(null=True, blank=True, db_index=True)
    user_id = models.IntegerField(null=True, blank=True, db_index=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['id']
        indexes = [
            models.Index(fields=['audience', 'id']),
            models.Index(fields=['company_id', 'id']),
        ]

    def __str__(self):
        return f'#{self.id} {self.type} [{self.audience}]'

    def to_sse(self):
        """The wire shape a client receives (kept small and stable)."""
        return {
            'id': self.id,
            'type': self.type,
            'ts': self.created_at.isoformat(),
            'payload': self.payload or {},
        }


class SystemState(models.Model):
    """Tiny key→JSON store for cross-worker singletons that the (per-process)
    LocMemCache cannot hold — e.g. the last "pending processing" fingerprint the
    change-detector compares against so it only emits an event when the real
    picture actually changes. One row per key."""
    key = models.CharField(max_length=64, primary_key=True)
    data = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def get(cls, key, default=None):
        row = cls.objects.filter(key=key).first()
        return row.data if row else (default if default is not None else {})

    @classmethod
    def put(cls, key, data):
        cls.objects.update_or_create(key=key, defaults={'data': data})


class CompanyRequest(models.Model):
    """A request a company manager files for the platform admin to action —
    e.g. "grant us access to vehicle X", "we need 5 more seats", "enable the AI
    assistant", or free-form support. The whole lifecycle is event-emitting, so
    the manager's dashboard reflects admin progress (in_progress → completed) in
    real time, and the admin's dashboard shows new requests the moment they land.
    """
    KIND_CHOICES = [
        ('vehicle_access', 'درخواست دسترسی به خودرو'),
        ('seats', 'افزایش ظرفیت کاربران'),
        ('ai_assistant', 'فعال‌سازی دستیار هوشمند'),
        ('documents', 'افزودن بسته مستندات'),
        ('support', 'پشتیبانی'),
        ('other', 'سایر'),
    ]
    STATUS_CHOICES = [
        ('pending', 'در انتظار بررسی'),
        ('in_progress', 'در حال انجام'),
        ('completed', 'انجام شد'),
        ('rejected', 'رد شد'),
    ]
    PRIORITY_CHOICES = [('low', 'کم'), ('normal', 'عادی'), ('high', 'زیاد')]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='requests')
    created_by = models.ForeignKey(PortalUser, on_delete=models.SET_NULL, null=True,
                                   blank=True, related_name='requests_made')
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default='support')
    subject = models.CharField(max_length=200)
    body = models.TextField(blank=True, default='')
    # Structured ask (e.g. {"car_ids":[3,4], "documents":["manual"]} or {"seats":5}).
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='pending', db_index=True)
    priority = models.CharField(max_length=8, choices=PRIORITY_CHOICES, default='normal')
    admin_note = models.TextField(blank=True, default='')     # admin's reply / resolution
    handled_by = models.CharField(max_length=100, blank=True, default='')   # admin username
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    OPEN_STATUSES = ('pending', 'in_progress')
    CLOSED_STATUSES = ('completed', 'rejected')

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['company', 'status']),
            models.Index(fields=['status', 'created_at']),
        ]

    def __str__(self):
        return f'req #{self.id} {self.kind} [{self.status}]'