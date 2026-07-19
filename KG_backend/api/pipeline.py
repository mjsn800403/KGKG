"""Data-processing pipeline: admin-triggered, resumable, load-aware.

The problem this solves: after new vehicle databases land in the warehouse,
several server-side processes must run (catalog registration, RAG embedding,
diagnostic sidecars, audit refresh). The admin is not a shell user — they get
a button in the admin panel instead, and the system also starts processing by
itself when new data appears and the server is quiet.

Robustness model (every failure mode has an owner):

* Browser closes / admin disconnects   -> irrelevant: the worker is a detached
  process; the panel merely polls a DB row.
* gunicorn restarts / deploys          -> worker runs in its OWN systemd
  transient unit (systemd-run), outside the backend service's cgroup, so a
  backend restart cannot kill it. Fallback: setsid-detached subprocess.
* Server reboots / worker crashes      -> the pipeline_tick watchdog (systemd
  timer) sees a running job with a stale heartbeat and a dead pid, marks it
  'stalled', and relaunches it (bounded attempts). All stages are
  incremental/idempotent, so a resumed job continues where it stopped:
  - catalog sync is additive+idempotent by design;
  - RAG embedding skips blobs already in vec_blobs (a transactional,
    gap-free prefix — a killed embed run never leaves torn vectors);
  - diag builds are per-car files, only missing cars are built;
  - the audit is a read-only scan.
* Two runs at once (double-click, auto + manual, legacy shell run)
                                        -> single-flight: an atomic DB claim
  (rows can only move pending->running once), plus a scan for foreign
  build_rag/build_diag processes before launching.
* Heavy load while the site is busy    -> the worker unit is started with
  Nice/CPUWeight/IO-idle properties, so serving traffic always outranks it;
  auto-starts additionally require load1/cores below a threshold.
* Wrong/partial data                   -> the pipeline only ever writes
  derived artifacts (_rag sidecars, catalog rows via the validity-gated sync,
  audit reports). build_rag/build_diag checksum the original car DBs before
  and after and scream if anything changed. Nothing here writes car DBs.

The admin panel shows: pending work, live per-stage progress (computed from
the artifacts themselves, e.g. vec_blobs vs blobs — correct even mid-crash),
ETA from THIS server's observed throughput, current load and a plain-language
recommendation for when to run.
"""
import os
import shutil
import signal
import sqlite3
import subprocess
import sys

from django.conf import settings
from django.utils import timezone

from .rag import config

HEARTBEAT_EVERY_S = 5
STALL_AFTER_S = 180            # heartbeat older than this + dead pid => stalled
MAX_AUTO_ATTEMPTS = 5          # watchdog relaunch budget per job
LOG_TAIL_CHARS = 6000

PYTHON = sys.executable        # the venv interpreter that runs Django


# ---------------------------------------------------------------------------
# Pending-work scanner (cheap: file listings + two COUNT queries, no big scan)
# ---------------------------------------------------------------------------

def _index_counts():
    """(total_blobs, embedded_blobs) from the RAG index; (0, 0) if absent.

    Counts ``vec_blobs_rowids`` — the plain shadow table behind the vec0
    virtual table (one row per stored vector) — NOT ``vec_blobs`` itself,
    which is only queryable on connections that loaded the sqlite-vec
    extension. This keeps progress readable from any process."""
    if not config.INDEX_DB.exists():
        return 0, 0
    try:
        con = sqlite3.connect(f'file:{config.INDEX_DB}?mode=ro', uri=True)
        try:
            total = con.execute('SELECT count(*) FROM blobs').fetchone()[0]
            done = con.execute('SELECT count(*) FROM vec_blobs_rowids').fetchone()[0]
            return total, done
        finally:
            con.close()
    except sqlite3.Error:
        return 0, 0


def _occurrence_stems():
    if not config.INDEX_DB.exists():
        return set()
    try:
        con = sqlite3.connect(f'file:{config.INDEX_DB}?mode=ro', uri=True)
        try:
            return {r[0] for r in con.execute('SELECT DISTINCT car_stem FROM occurrences')}
        finally:
            con.close()
    except sqlite3.Error:
        return set()


def _graph_synced_vectors():
    """Vector count at the time the relationship graph was last (re)built —
    written by the worker's rag stage. -1 when unknown (e.g. legacy index),
    which reads as 'graph may be stale' exactly once and then self-heals."""
    if not config.INDEX_DB.exists():
        return 0
    try:
        con = sqlite3.connect(f'file:{config.INDEX_DB}?mode=ro', uri=True)
        try:
            row = con.execute(
                "SELECT v FROM meta WHERE k='graph_synced_vectors'").fetchone()
            return int(row[0]) if row else -1
        finally:
            con.close()
    except (sqlite3.Error, ValueError):
        return -1


def _queue_counts():
    """Remaining work in the download / parse queues (the stages that run
    BEFORE any warehouse .db exists, so the file scanner cannot see them)."""
    from .models import DownloadRequest, ZipPackage
    need_download = 0
    for total, done in (DownloadRequest.objects
                        .filter(status__in=DownloadRequest.ACTIVE)
                        .values_list('vehicles_total', 'vehicles_done')):
        # An active request always counts at least 1 (its listing may not
        # have been fetched yet, so vehicles_total can still be 0).
        need_download += max(1, (total or 0) - (done or 0))
    need_parse = ZipPackage.objects.filter(status='pending').count()
    return need_download, need_parse


def _schema_stale_stems():
    from . import vehicleschema
    try:
        return vehicleschema.stale_stems()
    except Exception:
        return []


def pending_work():
    """What still needs processing, fleet-wide. Fast enough for a GET."""
    from .models import Car
    stems = [p.stem for p in config.car_db_files()]
    cataloged = set(Car.objects.values_list('car_name', flat=True))
    occ = _occurrence_stems()
    diag_have = ({p.stem.replace('.diag', '') for p in config.DIAG_DIR.glob('*.diag.db')}
                 if config.DIAG_DIR.exists() else set())
    total_blobs, embedded = _index_counts()

    need_download, need_parse = _queue_counts()
    need_catalog = sorted(s for s in stems if s not in cataloged)
    need_schema = _schema_stale_stems()
    need_ingest = sorted(s for s in stems if s not in occ)
    need_diag = sorted(s for s in stems if s not in diag_have)
    pages_to_embed = max(0, total_blobs - embedded)
    # Graph is stale when vectors were added after its last rebuild — e.g. a
    # run interrupted between the embed and graph phases.
    graph_pending = bool(total_blobs) and _graph_synced_vectors() != embedded

    return {
        'vehicles_on_disk': len(stems),
        'need_download': need_download,
        'need_parse': need_parse,
        'need_catalog': need_catalog,
        'need_schema': need_schema,
        'need_rag_ingest': need_ingest,
        'pages_to_embed': pages_to_embed,
        'embed_total': total_blobs,
        'embed_done': embedded,
        'graph_pending': graph_pending,
        'need_diag': need_diag,
        'has_work': bool(need_download or need_parse or need_catalog
                         or need_schema or need_ingest or pages_to_embed
                         or graph_pending or need_diag),
    }


def estimate_duration_s(work, settings_row):
    """Whole-pipeline duration estimate from this server's observed rates."""
    rate = max(0.2, settings_row.embed_rate_pps or 1.5)
    est = 120.0                                    # catalog + audit overhead
    est += (settings_row.download_secs_per_vehicle or 120.0) * work.get('need_download', 0)
    est += (settings_row.parse_secs_per_zip or 180.0) * work.get('need_parse', 0)
    est += 5.0 * len(work.get('need_schema', []))
    est += work['pages_to_embed'] / rate
    if work['need_rag_ingest']:
        est += 60 * len(work['need_rag_ingest'])   # ingest+dedup is I/O bound
    est += (settings_row.diag_secs_per_car or 90.0) * len(work['need_diag'])
    return int(est)


def load_snapshot():
    load1 = os.getloadavg()[0] if hasattr(os, 'getloadavg') else 0.0
    cores = os.cpu_count() or 1
    ratio = load1 / cores
    level = 'low' if ratio < 0.35 else ('medium' if ratio < 0.7 else 'high')
    return {'load1': round(load1, 2), 'cores': cores,
            'ratio': round(ratio, 2), 'level': level}


def recommendation(work, load, est_s):
    """Plain-language advice for a non-technical admin (fa)."""
    if not work['has_work']:
        return 'همه پردازش‌ها انجام شده است — کاری در انتظار نیست.'
    hours = est_s / 3600
    dur = (f'حدود {max(1, round(est_s / 60))} دقیقه' if hours < 1
           else f'حدود {hours:.1f} ساعت')
    msg = f'حجم کار در انتظار {dur} پردازش نیاز دارد. '
    if load['level'] == 'low':
        msg += 'بار سرور اکنون کم است — الان زمان مناسبی برای شروع است.'
    elif load['level'] == 'medium':
        msg += ('بار سرور متوسط است؛ می‌توانید الان شروع کنید (پردازش با اولویت پایین اجرا '
                'می‌شود و سایت کند نمی‌شود) یا برای ساعات کم‌ترافیک زمان‌بندی کنید.')
    else:
        msg += ('بار سرور بالاست؛ پیشنهاد می‌شود اجرا را برای ساعات کم‌ترافیک (مثلاً بامداد) '
                'زمان‌بندی کنید. در هر صورت پردازش با اولویت پایین اجرا می‌شود.')
    if hours >= 2:
        msg += ' در طول اجرا لازم نیست مرورگر باز بماند؛ پردازش روی سرور ادامه می‌یابد.'
    return msg


# ---------------------------------------------------------------------------
# Stage registry
# ---------------------------------------------------------------------------
# Each stage: plan(work) -> items_total (0 = skip), run(job_ctx) -> None.
# Stages self-report progress through job_ctx; failures are isolated.

def stage_definitions():
    return [
        {'key': 'download', 'label': 'دانلود بسته‌های جدید از منبع',
         'plan': lambda w: w.get('need_download', 0)},
        {'key': 'parse', 'label': 'استخراج و پردازش بسته‌های فشرده',
         'plan': lambda w: w.get('need_parse', 0)},
        {'key': 'catalog', 'label': 'ثبت خودروهای جدید در کاتالوگ',
         'plan': lambda w: len(w['need_catalog'])},
        {'key': 'schema', 'label': 'ساخت مشخصات ساختاریافته خودروها',
         'plan': lambda w: len(w.get('need_schema', []))},
        {'key': 'rag', 'label': 'ساخت ایندکس جستجو و دستیار هوشمند (RAG)',
         'plan': lambda w: (len(w['need_rag_ingest']) + w['pages_to_embed']
                            + (1 if w.get('graph_pending') else 0))},
        {'key': 'diag', 'label': 'ساخت موتور عیب‌یابی خودروها',
         'plan': lambda w: len(w['need_diag'])},
        {'key': 'audit', 'label': 'به‌روزرسانی گزارش سلامت داده‌ها',
         'plan': lambda w: 1},
    ]


# ---------------------------------------------------------------------------
# Launch / cancel / resume — process management
# ---------------------------------------------------------------------------

def _foreign_build_running():
    """A build_rag/build_diag/run_pipeline started OUTSIDE job control (e.g. a
    shell run) — never start a second one on top of it."""
    me = os.getpid()
    try:
        for pid in os.listdir('/proc'):
            if not pid.isdigit() or int(pid) == me:
                continue
            try:
                with open(f'/proc/{pid}/cmdline', 'rb') as f:
                    cmd = f.read().decode('utf-8', 'replace').replace('\x00', ' ')
            except OSError:
                continue
            if 'manage.py' in cmd and any(k in cmd for k in
                                          ('build_rag', 'build_diag', 'run_pipeline')):
                return {'pid': int(pid), 'cmd': cmd.strip()}
    except OSError:
        pass
    return None


def active_job():
    from .models import ProcessingJob
    return (ProcessingJob.objects
            .filter(status__in=ProcessingJob.ACTIVE)
            .order_by('-created_at').first())


def _pid_alive(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


def launch_worker(job):
    """Start the detached worker for ``job``. systemd-run when available (own
    cgroup => survives backend restarts, kernel-enforced low priority);
    otherwise a setsid-detached subprocess. Records how it was started."""
    from .models import ProcessingJob
    base = settings.BASE_DIR
    attempt = job.attempts + 1
    unit = f'kgkg-pipeline-job{job.id}-a{attempt}'
    argv = [PYTHON, 'manage.py', 'run_pipeline', '--job', str(job.id)]

    env_pairs = {
        'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
        'TOKENIZERS_PARALLELISM': 'false',
        'RAG_EMBED_MODEL': os.environ.get('RAG_EMBED_MODEL', 'bge-m3'),
        'OMP_NUM_THREADS': os.environ.get('KG_PIPELINE_THREADS', '12'),
    }

    launched_via = ''
    if shutil.which('systemd-run'):
        cmd = ['systemd-run', '--collect', f'--unit={unit}',
               f'--working-directory={base}',
               '--property=Nice=15',
               '--property=IOSchedulingClass=idle',
               '--property=CPUWeight=25',
               f'--property=EnvironmentFile={base}/.env.prod']
        for k, v in env_pairs.items():
            cmd.append(f'--setenv={k}={v}')
        cmd += argv
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if res.returncode == 0:
                launched_via = unit
            # non-zero -> fall through to the plain-subprocess fallback
        except (OSError, subprocess.TimeoutExpired):
            pass

    if not launched_via:
        # Fallback: detached child. Inherits gunicorn's env (which systemd
        # already populated from .env.prod). Survives worker recycling via
        # its own session; a backend RESTART may still kill it — the watchdog
        # then resumes it, so the guarantee holds either way.
        log_path = config.RAG_DIR / f'pipeline-job{job.id}.log'
        config.RAG_DIR.mkdir(parents=True, exist_ok=True)
        with open(log_path, 'ab') as logf:
            subprocess.Popen(argv, cwd=str(base), start_new_session=True,
                             stdout=logf, stderr=subprocess.STDOUT,
                             env={**os.environ, **env_pairs})
        launched_via = ''

    ProcessingJob.objects.filter(id=job.id).update(
        unit_name=launched_via, attempts=attempt)
    return launched_via or 'subprocess'


def start_job(trigger='manual', scheduled_for=None):
    """Create (and unless scheduled, immediately launch) a job.
    Returns (job, error_fa)."""
    from .models import ProcessingJob

    existing = active_job()
    if existing:
        return None, f'یک پردازش دیگر در جریان است (کار #{existing.id}).'
    foreign = _foreign_build_running()
    if foreign:
        return None, ('یک فرایند ساخت ایندکس خارج از سامانه در حال اجراست '
                      f'(pid {foreign["pid"]}); تا پایان آن صبر کنید.')

    work = pending_work()
    if not work['has_work']:
        return None, 'کار در انتظاری وجود ندارد — همه پردازش‌ها انجام شده است.'

    stages = [{'key': s['key'], 'label': s['label'], 'status': 'pending',
               'items_total': s['plan'](work), 'items_done': 0, 'error': ''}
              for s in stage_definitions()]
    job = ProcessingJob.objects.create(
        trigger=trigger,
        status='scheduled' if scheduled_for else 'pending',
        scheduled_for=scheduled_for,
        stages=stages,
        progress={'overall_pct': 0, 'planned_work': {
            'need_download': work.get('need_download', 0),
            'need_parse': work.get('need_parse', 0),
            'pages_to_embed': work['pages_to_embed'],
            'need_diag': len(work['need_diag']),
            'need_catalog': len(work['need_catalog']),
            'need_schema': len(work.get('need_schema', [])),
            'need_rag_ingest': len(work['need_rag_ingest']),
        }},
    )
    if not scheduled_for:
        launch_worker(job)
    return job, None


def resume_job(job):
    """Relaunch a paused/stalled/failed job. Returns (ok, error_fa)."""
    from .models import ProcessingJob
    if job.status not in ProcessingJob.RESUMABLE:
        return False, 'این کار قابل ازسرگیری نیست.'
    if active_job():
        return False, 'یک پردازش دیگر در جریان است.'
    if _foreign_build_running():
        return False, 'یک فرایند ساخت دیگر بیرون از سامانه در حال اجراست.'
    ProcessingJob.objects.filter(id=job.id).update(
        status='pending', error='', finished_at=None)
    job.refresh_from_db()
    launch_worker(job)
    return True, None


def cancel_job(job):
    """Graceful stop: systemctl stop for unit-launched workers (SIGTERM to the
    whole cgroup), plain SIGTERM otherwise. The worker's handler checkpoints
    and marks the job 'paused' (resumable). A job that never started is simply
    canceled."""
    from .models import ProcessingJob
    if job.status in ('pending', 'scheduled'):
        ProcessingJob.objects.filter(id=job.id).update(
            status='canceled', finished_at=timezone.now())
        return True, None
    if job.status != 'running':
        return False, 'این کار در حال اجرا نیست.'
    stopped = False
    if job.unit_name:
        try:
            res = subprocess.run(['systemctl', 'stop', job.unit_name],
                                 capture_output=True, timeout=30)
            stopped = res.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            stopped = False
    if not stopped and job.pid and _pid_alive(job.pid):
        try:
            os.kill(job.pid, signal.SIGTERM)
            stopped = True
        except OSError:
            stopped = False
    if not stopped:
        # Worker already gone -> just mark it so the watchdog doesn't resume.
        ProcessingJob.objects.filter(id=job.id).update(
            status='canceled', finished_at=timezone.now())
    return True, None


# ---------------------------------------------------------------------------
# Watchdog / scheduler / auto-start — called by pipeline_tick (systemd timer)
# ---------------------------------------------------------------------------

def tick():
    """One scheduler pass. Returns a dict of what it did (for the command log)."""
    from .models import PipelineSettings, ProcessingJob
    from . import monitoring
    now = timezone.now()
    st = PipelineSettings.get()
    did = {'stalled': [], 'resumed': [], 'started_scheduled': [], 'auto_started': False}

    # 1. Stall detection: running job, stale heartbeat, dead worker.
    for job in ProcessingJob.objects.filter(status='running'):
        stale = (job.heartbeat_at is None
                 or (now - job.heartbeat_at).total_seconds() > STALL_AFTER_S)
        if stale and not _pid_alive(job.pid):
            ProcessingJob.objects.filter(id=job.id, status='running').update(status='stalled')
            did['stalled'].append(job.id)
            monitoring._raise_alert(
                'pipeline_stalled', 'warning',
                f'پردازش داده (کار #{job.id}) متوقف شده است'
                + (' — تلاش مجدد خودکار انجام می‌شود.' if st.auto_resume else '.'),
                {'job_id': job.id, 'attempts': job.attempts})

    # 2. Auto-resume stalled jobs (bounded attempts).
    if st.auto_resume:
        for job in ProcessingJob.objects.filter(status='stalled'):
            if job.attempts >= MAX_AUTO_ATTEMPTS:
                continue
            if active_job() or _foreign_build_running():
                break
            ok, _err = resume_job(job)
            if ok:
                did['resumed'].append(job.id)

    # 3. Scheduled jobs whose time has come (retried every tick until the
    #    execution slot is free).
    for job in ProcessingJob.objects.filter(status='scheduled',
                                            scheduled_for__lte=now):
        if active_job() or _foreign_build_running():
            break
        ProcessingJob.objects.filter(id=job.id).update(status='pending')
        job.refresh_from_db()
        launch_worker(job)
        did['started_scheduled'].append(job.id)

    # 4. Auto-processing of newly landed data, only while the box is quiet.
    if (st.auto_enabled and not active_job() and not _foreign_build_running()
            and not ProcessingJob.objects.filter(status='stalled').exists()):
        load = load_snapshot()
        if load['ratio'] < st.load_threshold:
            work = pending_work()
            if work['has_work']:
                recent = ProcessingJob.objects.filter(
                    created_at__gte=now - timezone.timedelta(minutes=30)).exists()
                if not recent:
                    job, err = start_job(trigger='auto')
                    did['auto_started'] = bool(job)

    return did


# ---------------------------------------------------------------------------
# Serialization for the admin API
# ---------------------------------------------------------------------------

def job_dict(job):
    if job is None:
        return None
    return {
        'id': job.id, 'status': job.status, 'trigger': job.trigger,
        'created_at': job.created_at.isoformat(),
        'scheduled_for': job.scheduled_for.isoformat() if job.scheduled_for else None,
        'started_at': job.started_at.isoformat() if job.started_at else None,
        'finished_at': job.finished_at.isoformat() if job.finished_at else None,
        'heartbeat_at': job.heartbeat_at.isoformat() if job.heartbeat_at else None,
        'worker_alive': _pid_alive(job.pid) if job.status == 'running' else None,
        'attempts': job.attempts,
        'stages': job.stages,
        'progress': job.progress,
        'log_tail': job.log_tail[-2500:],
        'error': job.error,
        'resumable': job.status in type(job).RESUMABLE,
    }
