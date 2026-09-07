import datetime
import hashlib
import os
import secrets

from django.db import models
from django.contrib.auth.hashers import make_password, check_password
from django.utils import timezone


def _env_timedelta(name, default):
    """Read a day-count (or hour-count for *_HOURS) override from the env.

    Session TTLs are the kind of knob you want to retune during an incident
    without shipping code, so they're env-overridable — but garbage input falls
    back to the compiled-in default rather than accidentally disabling expiry.
    """
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    if value <= 0:
        return default
    return datetime.timedelta(hours=value) if name.endswith('_HOURS') else datetime.timedelta(days=value)


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
    """A company employee account.

    Historically only the platform admin issued these. They can now also be
    created self-service (via a seat invite) or assigned into a seat on the org
    graph. ``role`` is a legacy label kept for compat; the live organisational
    structure and every permission now come from the org-graph canvas
    (OrgNode / NodePermission — see api/orggraph.py). Feature access is per-user
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
    # Legacy reporting pointer, retained for analytics visibility. The live org
    # structure is the graph (OrgNode.parent); this is no longer authoritative.
    reports_to = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True, related_name='reports')
    # Per-user capabilities (seeded from role at creation, individually editable).
    can_manage_team = models.BooleanField(default=False)
    can_view_analytics = models.BooleanField(default=False)
    ai_assistant_enabled = models.BooleanField(default=False)
    # Which car-content UI this user prefers: 'modern' (sidebar tree +
    # adaptive flatten) or 'classic' (the original card-by-card drill-down,
    # no sidebar). Source of truth for the per-user browsing-mode toggle.
    browse_mode = models.CharField(max_length=10, default='modern')
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


class SessionTokenBase(models.Model):
    """Shared machinery for opaque, hashed-at-rest bearer session tokens.

    Only the sha256 of the token is persisted — same discipline InviteToken
    already uses. A stolen database (ours lived in git history for a while) no
    longer hands over live sessions, because the raw bearer value is returned
    exactly once at issue time and never written down.

    Two independent clocks bound a session:
      * ``IDLE_TTL``    — how long a token may go unused before it dies;
      * ``ABSOLUTE_TTL`` — a hard ceiling no amount of activity extends.
    ``expires_at`` always holds the earlier of (last_used + idle, absolute cap),
    so a single indexed comparison answers "is this still live?".

    Subclasses set the two TTLs and declare their own owner FK.
    """
    IDLE_TTL = datetime.timedelta(days=14)
    ABSOLUTE_TTL = datetime.timedelta(days=90)

    # How stale last_used_at may get before a refresh is worth a DB write.
    # portal_user() runs on EVERY content request; writing per request would
    # put SQLite under pointless write pressure for no security gain.
    TOUCH_INTERVAL = datetime.timedelta(minutes=5)

    key_hash = models.CharField(max_length=64, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        abstract = True

    @staticmethod
    def _hash(raw):
        return hashlib.sha256(raw.encode('utf-8')).hexdigest()

    @classmethod
    def _ttls(cls):
        """TTL overrides, so ops can retune without a deploy."""
        prefix = 'KG_ADMIN_TOKEN' if cls.__name__.startswith('Admin') else 'KG_TOKEN'
        return (
            _env_timedelta(f'{prefix}_IDLE_DAYS', cls.IDLE_TTL),
            _env_timedelta(f'{prefix}_MAX_DAYS', cls.ABSOLUTE_TTL),
        )

    @classmethod
    def issue(cls, owner):
        """Mint a token for ``owner``.

        Returns the instance with the raw bearer value attached as ``.key`` —
        an in-memory attribute only (``key`` is deliberately not a field any
        more), so callers keep reading ``token.key`` right after issuing while
        the database never sees it.
        """
        idle, absolute = cls._ttls()
        now = timezone.now()
        raw = secrets.token_urlsafe(48)
        obj = cls.objects.create(
            key_hash=cls._hash(raw),
            last_used_at=now,
            expires_at=now + min(idle, absolute),
            **{cls.OWNER_FIELD: owner},
        )
        obj.absolute_deadline = now + absolute
        obj.key = raw
        return obj

    @classmethod
    def resolve(cls, raw, select_related=()):
        """Return the live token for ``raw``, or None if unknown/expired.

        Expiry is enforced in the query itself, so a stale row can never be
        resolved even if a later `touch()` would have extended it.
        """
        if not raw:
            return None
        qs = cls.objects.filter(key_hash=cls._hash(raw), expires_at__gt=timezone.now())
        if select_related:
            qs = qs.select_related(*select_related)
        return qs.first()

    def touch(self):
        """Slide the idle window forward, never past the absolute ceiling.

        The expiry is recomputed from scratch rather than only ever pushed
        outward: the ceiling can sit *earlier* than the stored expiry (an old
        session whose idle window would otherwise reach past its hard limit),
        and in that case the value has to come down, not stay put.

        TOUCH_INTERVAL is what keeps this from writing on every request; past
        that gate a single UPDATE covers both fields.
        """
        idle, absolute = self._ttls()
        now = timezone.now()
        if self.last_used_at and (now - self.last_used_at) < self.TOUCH_INTERVAL:
            return
        new_expiry = min(now + idle, self.created_at + absolute)
        self.last_used_at = now
        self.expires_at = new_expiry
        self.__class__.objects.filter(pk=self.pk).update(
            last_used_at=now, expires_at=new_expiry)

    @classmethod
    def prune(cls):
        """Delete tokens past their expiry. Returns how many went."""
        return cls.objects.filter(expires_at__lte=timezone.now()).delete()[0]


class AuthToken(SessionTokenBase):
    """Opaque bearer token for portal users (simple, DB-backed sessions)."""
    OWNER_FIELD = 'user'

    user = models.ForeignKey(PortalUser, on_delete=models.CASCADE, related_name='tokens')

    class Meta:
        ordering = ['-created_at']

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


class AdminAuthToken(SessionTokenBase):
    """Session token issued after platform-admin username/password login.

    Deliberately much shorter-lived than a portal session: this token opens the
    whole platform (data-quality fixes, pipeline control, every company's
    users), so an unattended browser is a far bigger liability than it is for a
    specialist reading a manual.
    """
    OWNER_FIELD = 'admin'
    IDLE_TTL = datetime.timedelta(hours=12)
    ABSOLUTE_TTL = datetime.timedelta(days=7)

    admin = models.ForeignKey(PlatformAdmin, on_delete=models.CASCADE, related_name='tokens')

    class Meta:
        ordering = ['-created_at']

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
    """A queued request to fetch vehicle-manual ZIPs from the upstream source site.

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

# ---------------------------------------------------------------------------
# Org-graph canvas (n8n-style). Replaces the OrgRole/rank/scope authoring model.
#
# The organisation is a GRAPH DOCUMENT owned by exactly one root node (layer 0).
# The root node's occupant is the company super-admin: only they may edit the
# graph (create/delete seats, assign people, set permissions). Every other node
# is a SEAT with an explicit, root-assigned permission set; parent edges are
# PURELY VISUAL reporting lines and carry no authorisation meaning. One employee
# occupies at most one seat. Permissions live on the node and are compiled down
# (see api/orggraph.py) into the existing enforcement primitives — UserCarAccess
# rows + PortalUser.ai_assistant_enabled + granted admin panels — so content /
# RAG / chat gating stays unchanged.
# ---------------------------------------------------------------------------


class OrgGraph(models.Model):
    """The single org-structure document for a company."""
    company = models.OneToOneField(Company, on_delete=models.CASCADE, related_name='org_graph')
    updated_at = models.DateTimeField(auto_now=True)
    # Occupant PortalUser who last edited (root), for audit.
    updated_by = models.ForeignKey(
        'PortalUser', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    def __str__(self):
        return f'graph:{self.company.name}'

    @property
    def root_node(self):
        return self.nodes.filter(is_root=True).first()


class OrgNode(models.Model):
    """A seat on the canvas. May be empty or occupied by one PortalUser."""
    graph = models.ForeignKey(OrgGraph, on_delete=models.CASCADE, related_name='nodes')
    parent = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True, related_name='children')
    # Exactly one node per graph has is_root=True; only its occupant can edit.
    is_root = models.BooleanField(default=False)
    label = models.CharField(max_length=120, blank=True, default='')
    # Canvas position (React Flow coordinates).
    canvas_x = models.FloatField(default=0)
    canvas_y = models.FloatField(default=0)
    # The employee sitting in this seat (one seat per person is enforced by the
    # OneToOne: a PortalUser can occupy at most one node).
    occupant = models.OneToOneField(
        'PortalUser', on_delete=models.SET_NULL, null=True, blank=True, related_name='seat')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['graph_id', 'id']
        indexes = [models.Index(fields=['graph', 'parent'])]
        constraints = [
            models.UniqueConstraint(
                fields=['graph'], condition=models.Q(is_root=True),
                name='one_root_per_graph'),
        ]

    def __str__(self):
        who = self.occupant.username if self.occupant_id else '(empty)'
        return f'node:{self.label or who}'


class NodePermission(models.Model):
    """Root-assigned permission set for a seat. Source of truth; compiled into
    the enforcement primitives whenever it changes (see api/orggraph.py)."""
    node = models.OneToOneField(OrgNode, on_delete=models.CASCADE, related_name='permission')
    # Car/content access, same shape as apply_user_access accepts:
    # [{car_id: int, documents: [package_id, ...]}, ...]. Empty documents list
    # for a car == all layers the root grants for it. Root is super-admin, so
    # these are applied as admin grants (bypass the company purchase cap).
    car_access = models.JSONField(default=list, blank=True)
    ai_eligible = models.BooleanField(default=False)
    # Granted admin-panel keys (subset of orggraph.ADMIN_PANEL_KEYS), e.g.
    # ['metrics', 'data_quality', 'ingest', 'terminology']. Empty == none.
    admin_panels = models.JSONField(default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'perm:{self.node_id}'


class NodeInvite(models.Model):
    """Invite bound to a specific empty seat: the invitee registers straight
    into ``node``. Only the sha256 of the opaque token is stored."""
    DEFAULT_TTL = datetime.timedelta(days=7)

    node = models.ForeignKey(OrgNode, on_delete=models.CASCADE, related_name='invites')
    email = models.EmailField(max_length=254)
    display_name = models.CharField(max_length=150, blank=True, default='')
    key_hash = models.CharField(max_length=64, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    @staticmethod
    def _hash(raw):
        return hashlib.sha256(raw.encode('utf-8')).hexdigest()

    @classmethod
    def issue(cls, node, email, display_name='', ttl=None):
        cls.objects.filter(node=node, used_at__isnull=True).delete()
        raw = secrets.token_urlsafe(32)
        obj = cls.objects.create(
            node=node, email=email, display_name=display_name,
            key_hash=cls._hash(raw),
            expires_at=timezone.now() + (ttl or cls.DEFAULT_TTL))
        return obj, raw

    @classmethod
    def resolve(cls, raw):
        if not raw:
            return None
        obj = cls.objects.filter(key_hash=cls._hash(raw)).select_related(
            'node', 'node__graph', 'node__graph__company').first()
        if not obj or obj.used_at is not None or obj.expires_at <= timezone.now():
            return None
        return obj

    def consume(self):
        self.used_at = timezone.now()
        self.save(update_fields=['used_at'])


class OtpChallenge(models.Model):
    """Pending SMS second factor between the password step and token issue.

    DB-backed rather than in-process: gunicorn runs several workers, so a
    challenge created while serving the login request must be verifiable by
    whichever worker happens to serve the verify request. Only the sha256 of
    the code is stored.
    """
    DEFAULT_TTL = datetime.timedelta(minutes=2)
    RESEND_INTERVAL = datetime.timedelta(seconds=60)
    MAX_ATTEMPTS = 5

    key_hash = models.CharField(max_length=64, unique=True, db_index=True)
    user = models.ForeignKey(PortalUser, on_delete=models.CASCADE, related_name='otp_challenges')
    phone = models.CharField(max_length=40)
    code_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    last_sent_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'otp:{self.user.username}'

    @staticmethod
    def _hash(raw):
        return hashlib.sha256(str(raw).encode('utf-8')).hexdigest()

    @classmethod
    def issue(cls, user, phone, code, ttl=None):
        """Start a challenge, dropping any earlier one for this user.

        Returns (instance, raw_key); hand the raw key to the client and keep
        nothing else.
        """
        cls.objects.filter(user=user).delete()
        raw = secrets.token_urlsafe(32)
        now = timezone.now()
        obj = cls.objects.create(
            key_hash=cls._hash(raw), user=user, phone=phone,
            code_hash=cls._hash(code),
            expires_at=now + (ttl or cls.DEFAULT_TTL),
            last_sent_at=now,
        )
        return obj, raw

    @classmethod
    def recent_send_wait(cls, user):
        """Seconds to wait before another OTP SMS may be sent to ``user``.

        Enforced at the login send path too (not only resend) so no endpoint
        can push more than one SMS per RESEND_INTERVAL to the same account.
        """
        obj = (cls.objects.filter(user=user)
               .filter(expires_at__gt=timezone.now())
               .order_by("-last_sent_at").first())
        if not obj:
            return 0
        remaining = cls.RESEND_INTERVAL - (timezone.now() - obj.last_sent_at)
        return max(0, int(remaining.total_seconds() + 0.999))

    @classmethod
    def resolve(cls, raw):
        """Return the live (unexpired) challenge for ``raw``, or None."""
        if not raw:
            return None
        obj = (cls.objects.filter(key_hash=cls._hash(raw))
               .select_related('user', 'user__company').first())
        if not obj or obj.expires_at <= timezone.now():
            return None
        return obj

    def check_code(self, code):
        """Spend one attempt. True only on a match; the challenge is then
        consumed so a code cannot be replayed."""
        self.attempts += 1
        if self.attempts > self.MAX_ATTEMPTS:
            self.delete()
            return False
        if self._hash(code) != self.code_hash:
            self.save(update_fields=['attempts'])
            return False
        self.delete()
        return True

    def resend_wait(self):
        """Seconds still to wait before another SMS may be sent (0 if ready)."""
        elapsed = timezone.now() - self.last_sent_at
        remaining = self.RESEND_INTERVAL - elapsed
        return max(0, int(remaining.total_seconds() + 0.999))

    def rotate(self, code):
        self.code_hash = self._hash(code)
        self.last_sent_at = timezone.now()
        self.attempts = 0
        self.save(update_fields=['code_hash', 'last_sent_at', 'attempts'])
