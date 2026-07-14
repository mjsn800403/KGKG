"""The pipeline WORKER. Never run by hand in normal operation — the admin
panel (api/pipeline.start_job) or the pipeline_tick timer launches it as a
detached process:

    python manage.py run_pipeline --job <id>

Contract:
* claims the job atomically (loses the race gracefully if another worker got it);
* heartbeats progress into the ProcessingJob row every few seconds — progress
  for the embedding stage is computed from the index itself (vec_blobs vs
  blobs), so it is correct even across crashes and resumes;
* SIGTERM (admin cancel / systemctl stop / shutdown) checkpoints and marks the
  job 'paused' — every stage is incremental, so a later resume continues
  exactly where this run stopped;
* a stage failure is recorded on that stage and — where safe — later stages
  still run; the job ends 'failed' only when the core work could not proceed.
"""
import os
import signal
import threading
import time
import traceback

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils import timezone

from api import dataquality, events, monitoring, pipeline
from api.models import PipelineSettings, ProcessingJob


class _Canceled(Exception):
    pass


class _Tee:
    """Line stream for call_command/build logs -> rolling job log tail."""

    def __init__(self, runner):
        self.runner = runner

    def write(self, msg):
        text = str(msg).strip('\n')
        if text.strip():
            self.runner.log(text)

    def flush(self):
        pass


class Runner:
    def __init__(self, job):
        self.job = job
        self.cancel = threading.Event()
        self.stop_hb = threading.Event()
        self._log_lines = []
        self._lock = threading.Lock()
        self._samples = []           # [(t, embedded)] for live rate/ETA
        self.settings_row = PipelineSettings.get()
        self.tee = _Tee(self)

    # ---- logging ----------------------------------------------------------
    def log(self, line):
        stamp = timezone.now().strftime('%H:%M:%S')
        with self._lock:
            self._log_lines.append(f'[{stamp}] {line}')
            if len(self._log_lines) > 400:
                del self._log_lines[:100]

    def _log_tail(self):
        with self._lock:
            return '\n'.join(self._log_lines)[-pipeline.LOG_TAIL_CHARS:]

    # ---- persisted state --------------------------------------------------
    def save(self, **fields):
        ProcessingJob.objects.filter(id=self.job.id).update(**fields)

    # ---- real-time events -------------------------------------------------
    def emit(self, etype, force=False):
        """Push a pipeline event to the admin dashboard. Progress events are
        throttled to whole-percent moves so the stream carries signal, not spam;
        lifecycle events (stage change, completion) always send (force=True)."""
        try:
            pct = (self.job.progress or {}).get('overall_pct', 0)
            if not force and abs(pct - getattr(self, '_last_emit_pct', -99)) < 2.0:
                return
            self._last_emit_pct = pct
            events.emit(etype, {'job': pipeline.job_dict(self.job)}, audience='admin')
        except Exception:
            pass

    def persist_progress(self):
        self.job.progress['updated_at'] = timezone.now().isoformat()
        self.save(stages=self.job.stages, progress=self.job.progress,
                  log_tail=self._log_tail(), heartbeat_at=timezone.now())

    def stage(self, key):
        return next(s for s in self.job.stages if s['key'] == key)

    # ---- overall progress model -------------------------------------------
    # Percentages weight each stage by its estimated time share, so the bar
    # moves honestly (100 diag cars ≠ 100 embedded pages).
    def _stage_cost(self, s):
        rate = max(0.2, self.settings_row.embed_rate_pps or 1.5)
        per_item = {'catalog': 1.0,
                    'rag': 1.0 / rate,
                    'diag': self.settings_row.diag_secs_per_car or 90.0,
                    'audit': 90.0}[s['key']]
        return max(1.0, s['items_total'] * per_item)

    def update_overall(self):
        total = sum(self._stage_cost(s) for s in self.job.stages)
        done = 0.0
        for s in self.job.stages:
            c = self._stage_cost(s)
            if s['status'] in ('done', 'skipped', 'failed'):
                done += c
            elif s['items_total']:
                done += c * min(1.0, s['items_done'] / s['items_total'])
        self.job.progress['overall_pct'] = round(100 * done / total, 1)

    # ---- heartbeat thread ---------------------------------------------------
    def heartbeat_loop(self):
        while not self.stop_hb.wait(pipeline.HEARTBEAT_EVERY_S):
            try:
                self._heartbeat_once()
            except Exception:
                # A heartbeat bug must never kill the actual work.
                pass
            finally:
                close_old_connections()

    def _heartbeat_once(self):
        prog = self.job.progress
        # Live embedding progress straight from the artifact (crash-proof).
        rag = self.stage('rag')
        if rag['status'] == 'running':
            total, embedded = pipeline._index_counts()
            base = prog.get('embed_baseline', 0)
            rag['items_done'] = max(0, embedded - base)
            now = time.monotonic()
            self._samples.append((now, embedded))
            self._samples = [(t, n) for t, n in self._samples if now - t <= 300]
            if len(self._samples) >= 2:
                (t0, n0), (t1, n1) = self._samples[0], self._samples[-1]
                if t1 > t0 and n1 >= n0:
                    rate = (n1 - n0) / (t1 - t0)
                    prog['rate_pps'] = round(rate, 2)
                    remaining = max(0, total - embedded)
                    prog['eta_s'] = int(remaining / rate) if rate > 0.05 else None
            prog['embed_done'] = embedded
            prog['embed_total'] = total
        self.update_overall()
        self.persist_progress()
        self.emit('pipeline.progress')          # throttled to ~2% moves
        # Cooperative cancel (the admin pressed stop but SIGTERM didn't land).
        row = ProcessingJob.objects.filter(id=self.job.id).values_list(
            'status', flat=True).first()
        if row == 'canceled':
            self.cancel.set()

    # ---- stages -------------------------------------------------------------
    def check_cancel(self):
        if self.cancel.is_set():
            raise _Canceled()

    def run_stage(self, key, fn):
        s = self.stage(key)
        if s['items_total'] <= 0:
            s['status'] = 'skipped'
            self.persist_progress()
            return True
        s['status'] = 'running'
        s['started_at'] = timezone.now().isoformat()
        self.job.progress['stage'] = key
        self.persist_progress()
        self.emit('pipeline.progress', force=True)   # stage boundary: always send
        try:
            fn(s)
            s['status'] = 'done'
            s['items_done'] = s['items_total']
            return True
        except _Canceled:
            raise
        except Exception as e:
            s['status'] = 'failed'
            s['error'] = f'{e.__class__.__name__}: {e}'[:500]
            self.log(f'!! stage {key} failed: {s["error"]}')
            self.log(traceback.format_exc().splitlines()[-1])
            return False
        finally:
            s['finished_at'] = timezone.now().isoformat()
            self.update_overall()
            self.persist_progress()

    def stage_catalog(self, s):
        call_command('sync_car_catalog', stdout=self.tee, stderr=self.tee)

    def stage_rag(self, s):
        """Bring the semantic index fully up to date, resumable at any point.

        Three sub-phases, each independently idempotent:
          1. new cars on disk           -> ``build_rag --add`` (ingest + embed
             + incremental graph, O(new content) only);
          2. blobs still lacking vectors (a previously interrupted embed)
             -> resume ``embed_index`` directly (it continues from MAX(rowid);
             every window commits, so SIGKILL can never tear it);
          3. graph out of sync with the vectors -> full edge rebuild from the
             PERSISTED int8 vectors. The transient float table (vec_build) is
             dropped first: after a resumed embed it only covers newer blobs,
             and letting graph.build_all read that incomplete table would
             silently drop edges for every older page — the int8 fallback
             covers ALL blobs. A meta marker (graph_synced_vectors) records
             what the graph has seen, so an interrupt between embed and graph
             still resumes correctly.
        """
        batch = int(os.environ.get('KG_PIPELINE_BATCH', '32'))
        total, embedded = pipeline._index_counts()
        self.job.progress['embed_baseline'] = embedded
        self.persist_progress()

        work = pipeline.pending_work()
        if work['need_rag_ingest']:
            self.log(f"ingesting {len(work['need_rag_ingest'])} new car(s)")
            call_command('build_rag', add=True, batch_size=batch,
                         stdout=self.tee, stderr=self.tee)

        from api.rag import embed, graph, store
        total, embedded = pipeline._index_counts()
        need_embed = total - embedded > 0
        need_graph = pipeline._graph_synced_vectors() != embedded or need_embed
        if need_embed or need_graph:
            index = store.open_index()
            try:
                store.init_index_schema(index)
                if need_embed:
                    self.log(f'resuming embedding: {total - embedded} pages remain')
                    embed.embed_index(index, batch_size=batch, log=self.tee.write)
                self.check_cancel()
                self.log('rebuilding relationship graph from persisted vectors')
                store.drop_build_vec(index)
                graph.build_all(index, log=self.tee.write)
                _, embedded_now = pipeline._index_counts()
                index.execute(
                    "INSERT OR REPLACE INTO meta(k,v) VALUES('graph_synced_vectors',?)",
                    (str(embedded_now),))
                index.execute(
                    "INSERT OR REPLACE INTO meta(k,v) VALUES('built_at', datetime('now'))")
                index.commit()
                store.optimize(index, log=self.tee.write)
            finally:
                index.close()

        # Verify against the artifact itself (never trust assumptions).
        total, embedded = pipeline._index_counts()
        if total and total - embedded > 0:
            raise RuntimeError(f'{total - embedded} pages still lack vectors '
                               'after the rag stage — see log')

    def stage_diag(self, s):
        from api.rag import diag_build
        from api.rag import config as ragcfg
        have = ({p.stem.replace('.diag', '') for p in ragcfg.DIAG_DIR.glob('*.diag.db')}
                if ragcfg.DIAG_DIR.exists() else set())
        todo = [p.stem for p in ragcfg.car_db_files() if p.stem not in have]
        errors = []
        for i, stem in enumerate(todo):
            self.check_cancel()
            self.job.progress['current_item'] = stem
            self.persist_progress()
            t0 = time.monotonic()
            try:
                diag_build.build_car(stem, rebuild=False, log=self.tee.write)
                dt = time.monotonic() - t0
                # Learn this server's real per-car cost for future estimates.
                prev = self.settings_row.diag_secs_per_car or dt
                self.settings_row.diag_secs_per_car = round(0.7 * prev + 0.3 * dt, 1)
            except Exception as e:
                errors.append(f'{stem}: {e.__class__.__name__}: {e}')
                self.log(f'!! diag failed for {stem}: {e}')
            s['items_done'] = i + 1
            self.update_overall()
            self.persist_progress()
        self.settings_row.save(update_fields=['diag_secs_per_car', 'updated_at'])
        self.job.progress.pop('current_item', None)
        if errors:
            s['error'] = ' | '.join(errors)[:800]
            if len(errors) == len(todo) and todo:
                raise RuntimeError('every diag build failed')

    def stage_audit(self, s):
        run = dataquality.run_audit_to_db(fix=False)
        if run.status != 'done':
            raise RuntimeError(f'audit run #{run.id} ended {run.status}')
        self.log(f'audit refreshed (run #{run.id}): '
                 f"{run.summary.get('complete')}/{run.summary.get('total_dbs')} complete")

    # ---- main ---------------------------------------------------------------
    def run(self):
        job = self.job
        self.log(f'worker started (pid {os.getpid()}, attempt {job.attempts})')
        hb = threading.Thread(target=self.heartbeat_loop, daemon=True)
        hb.start()
        failed_stages = []
        try:
            ok_catalog = self.run_stage('catalog', self.stage_catalog)
            self.check_cancel()
            ok_rag = self.run_stage('rag', self.stage_rag)
            self.check_cancel()
            if ok_rag:
                ok_diag = self.run_stage('diag', self.stage_diag)
            else:
                d = self.stage('diag')
                if d['items_total'] > 0:
                    d['status'] = 'skipped'
                    d['error'] = 'به دلیل خطا در مرحله RAG اجرا نشد'
                ok_diag = False
            self.check_cancel()
            ok_audit = self.run_stage('audit', self.stage_audit)
            failed_stages = [s['key'] for s in job.stages if s['status'] == 'failed']
            final = 'done' if not failed_stages else 'failed'
        except _Canceled:
            self.log('cancel requested — checkpointed cleanly; resume later')
            final = 'paused'
        except Exception as e:
            self.log(f'!! worker crashed: {e}')
            self.log(traceback.format_exc().splitlines()[-1])
            final = 'failed'
            failed_stages = ['worker']
        finally:
            self.stop_hb.set()
            hb.join(timeout=10)

        # Learn the observed embedding rate for future ETAs.
        if self.job.progress.get('rate_pps'):
            prev = self.settings_row.embed_rate_pps or self.job.progress['rate_pps']
            self.settings_row.embed_rate_pps = round(
                0.7 * prev + 0.3 * self.job.progress['rate_pps'], 2)
            self.settings_row.save(update_fields=['embed_rate_pps', 'updated_at'])

        self.update_overall()
        if final == 'done':
            self.job.progress['overall_pct'] = 100.0
            monitoring.evaluate_alerts()   # resolves pipeline alerts if clean
            try:
                from api.models import SystemAlert
                SystemAlert.objects.filter(
                    key__in=['pipeline_stalled', 'pipeline_errors'],
                    is_open=True).update(is_open=False, resolved_at=timezone.now())
            except Exception:
                pass
        elif final == 'failed':
            monitoring._raise_alert(
                'pipeline_errors', 'warning',
                f'پردازش داده (کار #{job.id}) با خطا تمام شد: {", ".join(failed_stages)}',
                {'job_id': job.id, 'stages': failed_stages})

        self.save(status=final,
                  finished_at=timezone.now() if final in ('done', 'failed') else None,
                  stages=job.stages, progress=job.progress,
                  log_tail=self._log_tail(),
                  error='; '.join(failed_stages) if failed_stages else '')
        self.log(f'worker finished: {final}')
        self.save(log_tail=self._log_tail())

        # Terminal event + refreshed "pending processing" picture so the admin
        # dashboard flips from "processing…" to the new clean/partial state live.
        self.job.refresh_from_db()
        _terminal = {'done': 'pipeline.completed', 'failed': 'pipeline.failed',
                     'paused': 'pipeline.paused'}.get(final, 'pipeline.progress')
        self.emit(_terminal, force=True)
        try:
            events.detect_and_emit()
        except Exception:
            pass


class Command(BaseCommand):
    help = 'Pipeline worker (launched by the admin panel / pipeline_tick).'

    def add_arguments(self, parser):
        parser.add_argument('--job', type=int, required=True)

    def handle(self, *args, **opts):
        job = ProcessingJob.objects.filter(id=opts['job']).first()
        if job is None:
            self.stderr.write('no such job')
            return
        # Atomic claim — exactly one worker can move the row into 'running'.
        claimed = ProcessingJob.objects.filter(
            id=job.id, status__in=['pending', 'scheduled']).update(
            status='running', pid=os.getpid(),
            started_at=job.started_at or timezone.now(),
            heartbeat_at=timezone.now())
        if not claimed:
            self.stderr.write(f'job #{job.id} not claimable ({job.status})')
            return
        job.refresh_from_db()

        runner = Runner(job)

        def _sigterm(signum, frame):
            runner.cancel.set()
            raise _Canceled()

        signal.signal(signal.SIGTERM, _sigterm)
        signal.signal(signal.SIGINT, _sigterm)
        runner.run()
