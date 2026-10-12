"""Build (or rebuild) the unified, deduplicated RAG index + relationship graph.

    python manage.py build_rag                 # full fleet, fresh build
    python manage.py build_rag --rebuild        # wipe index.rag.db and start over
    python manage.py build_rag --pilot bZ4X     # only cars of one model (validation)
    python manage.py build_rag --skip-embed     # ingest + dedup only (no vectors)
    python manage.py build_rag --graph-only     # rebuild edges only (needs vectors)

NEVER writes to the original car DBs or db.sqlite3 -- only to
Database_warehouse/_rag/index.rag.db. Verifies the originals are byte-identical
before and after the build and prints the proof.
"""
import time
import hashlib
from django.core.management.base import BaseCommand, CommandError

from api.rag import config, store, ingest, embed, graph


def _checksums():
    out = {}
    for f in config.car_db_files():
        h = hashlib.sha256()
        with open(f, 'rb') as fh:
            for blk in iter(lambda: fh.read(1 << 20), b''):
                h.update(blk)
        out[f.name] = (f.stat().st_size, h.hexdigest())
    return out


class Command(BaseCommand):
    help = 'Build the unified local RAG index + relationship graph (sidecar files only).'

    def add_arguments(self, parser):
        parser.add_argument('--rebuild', action='store_true', help='Wipe index.rag.db first.')
        parser.add_argument('--add', action='store_true',
                            help='Incrementally index only car DBs not yet in the index '
                                 '(embeds only genuinely-new pages). For adding new models at scale.')
        parser.add_argument('--pilot', help='Only cars whose model matches this (e.g. "bZ4X").')
        parser.add_argument('--skip-embed', action='store_true', help='Ingest/dedup only.')
        parser.add_argument('--graph-only', action='store_true', help='Rebuild edges only.')
        parser.add_argument('--labor-only', action='store_true',
                            help='Rebuild only the labor_time (work-model) edges. Fast, no '
                                 'embed; uses the persisted int8 vectors.')
        parser.add_argument('--batch-size', type=int, default=16,
                            help='Embedding batch size (16 keeps MPS memory low/stable).')

    def handle(self, *args, **opts):
        config.RAG_DIR.mkdir(parents=True, exist_ok=True)
        t0 = time.time()

        only = None
        if opts['pilot']:
            # Resolve against every car DB actually on disk, not just
            # CAR_REGISTRY: only 9 stems are registered explicitly, so matching
            # the registry alone made --pilot a no-op for 96% of the fleet.
            want = opts['pilot'].lower()
            only = {f.stem for f in config.car_db_files()
                    if want in (config.car_meta(f.stem)['model'] or '').lower()
                    or want in f.stem.lower()}
            if not only:
                # ingest() treats an empty set as "no filter", so returning one
                # here would quietly start a full-fleet rebuild instead of the
                # pilot the caller asked for.
                raise CommandError(
                    f"--pilot {opts['pilot']!r} matched no car DB. Nothing was "
                    f"built. Check the model name against "
                    f"Database_warehouse/*.db.")
            self.stdout.write(f"  pilot mode: {len(only)} car(s): {sorted(only)}")

        # --- safety: snapshot original checksums BEFORE touching anything ---
        self.stdout.write(self.style.MIGRATE_HEADING("=== safety: checksumming original car DBs ==="))
        pre = _checksums()
        cks_path = config.RAG_DIR / 'checksums_pre_build.txt'
        cks_path.write_text('\n'.join(f"{n}\t{sz}\t{dg}" for n, (sz, dg) in sorted(pre.items())))
        self.stdout.write(f"  {len(pre)} originals snapshotted -> {cks_path}")


        if opts['rebuild']:
            for suffix in ('', '-wal', '-shm'):
                p = config.INDEX_DB.with_name(config.INDEX_DB.name + suffix)
                if p.exists():
                    p.unlink()
            self.stdout.write("  index.rag.db wiped (rebuild).")

        index = store.open_index()
        store.init_index_schema(index)
        self.stdout.write(f"  embedding model: {config.EMBED_MODEL} (dim={config.EMBED_DIM})")

        # guard: vectors are model/dimension-specific. Refuse to mix models in
        # one index unless the user explicitly rebuilds.
        prev = index.execute("SELECT v FROM meta WHERE k='embed_model'").fetchone()
        if prev and prev[0] != config.EMBED_MODEL and not opts['rebuild']:
            index.close()
            raise CommandError(
                f"index was built with '{prev[0]}' but RAG_EMBED_MODEL resolves to "
                f"'{config.EMBED_MODEL}'. Re-run with --rebuild to switch models.")
        index.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('embed_model',?)", (config.EMBED_MODEL,))
        index.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('embed_dim',?)", (str(config.EMBED_DIM),))
        index.commit()

        if opts['graph_only']:
            self.stdout.write(self.style.MIGRATE_HEADING("=== graph (edges only) ==="))
            graph.build_all(index, log=self.stdout.write)
        elif opts['labor_only']:
            self.stdout.write(self.style.MIGRATE_HEADING("=== labor_time edges (rebuild only) ==="))
            graph.rebuild_labor_edges(index, log=self.stdout.write)
        elif opts['add']:
            self._add_cars(index)
        else:
            ingest_done = index.execute("SELECT v FROM meta WHERE k='ingest_done'").fetchone()
            if ingest_done and ingest_done[0] == '1' and not opts['rebuild']:
                n = index.execute("SELECT COUNT(*) FROM occurrences").fetchone()[0]
                self.stdout.write(self.style.WARNING(
                    f"=== stage 1: SKIPPED (already ingested: {n} occurrences) -> resuming ==="))
            else:
                # ingest not yet complete (fresh, or interrupted mid-ingest):
                # wipe any partial content so we never duplicate occurrences.
                store.clear_data(index)
                self.stdout.write(self.style.MIGRATE_HEADING("=== stage 1: scan + dedup + chunk ==="))
                stats = ingest.ingest(index, only_cars=only, log=self.stdout.write)
                self.stdout.write(
                    f"  leaves={stats['leaves']}  unique blobs={stats['blobs']}  "
                    f"occurrences={stats['occ']}  (dedup {100*(1-stats['blobs']/max(stats['leaves'],1)):.1f}%)")
                index.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('ingest_done','1')")
                index.commit()

            if not opts['skip_embed']:
                self.stdout.write(self.style.MIGRATE_HEADING("=== stage 2: embed (int8 serve + float anchors) ==="))
                embed.embed_index(index, batch_size=opts['batch_size'], log=self.stdout.write)
                self.stdout.write(self.style.MIGRATE_HEADING("=== stage 3: relationship graph ==="))
                graph.build_all(index, log=self.stdout.write)

        # drop the transient float table; register cars + meta
        if not opts['skip_embed']:
            store.drop_build_vec(index)
        self._register(index)
        index.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('built_at', datetime('now'))")
        index.commit()
        # refresh planner stats + merge FTS segments so serving queries are fast.
        self.stdout.write(self.style.MIGRATE_HEADING("=== optimize (ANALYZE + FTS) ==="))
        store.optimize(index, log=self.stdout.write)
        self._report_sizes(index)
        index.close()

        # --- safety: prove originals are byte-identical ---------------------
        self.stdout.write(self.style.MIGRATE_HEADING("=== safety: re-checksumming originals ==="))
        post = _checksums()
        changed = [n for n in pre if pre[n] != post.get(n)]
        if changed:
            self.stdout.write(self.style.ERROR(f"  !! ORIGINALS CHANGED: {changed}"))
        else:
            self.stdout.write(self.style.SUCCESS(f"  all {len(pre)} original DBs byte-identical (untouched)."))

        self.stdout.write(self.style.SUCCESS(f"\nRAG build complete in {time.time()-t0:.0f}s."))

    def _add_cars(self, index):
        """Incrementally index car DBs that are on disk but not yet in the index.
        Only genuinely-new pages (unseen content hashes) get embedded; everything
        else just gains an `occurrence`. O(new pages), not O(whole fleet)."""
        done = index.execute("SELECT v FROM meta WHERE k='ingest_done'").fetchone()
        if not (done and done[0] == '1'):
            raise CommandError("No complete index yet. Run a full build first, then --add.")
        indexed = {r[0] for r in index.execute("SELECT DISTINCT car_stem FROM occurrences")}
        new_cars = [f.stem for f in config.car_db_files() if f.stem not in indexed]
        if not new_cars:
            self.stdout.write(self.style.SUCCESS("  no new car DBs to add — index is up to date."))
            return
        self.stdout.write(self.style.MIGRATE_HEADING(f"=== adding {len(new_cars)} new car(s) ==="))
        for c in new_cars:
            self.stdout.write(f"    + {c}")

        prev_max = index.execute("SELECT COALESCE(MAX(blob_id),0) FROM blobs").fetchone()[0]
        stats = ingest.ingest(index, only_cars=set(new_cars), log=self.stdout.write)
        new_ids = [r[0] for r in index.execute(
            "SELECT blob_id FROM blobs WHERE blob_id > ?", (prev_max,))]
        self.stdout.write(
            f"  +{stats['occ']} occurrences, {len(new_ids)} genuinely-new pages "
            f"({stats['occ'] - len(new_ids)} reused existing content)")
        embed.embed_index(index, batch_size=16, log=self.stdout.write)
        self.stdout.write(self.style.MIGRATE_HEADING("=== graph (incremental) ==="))
        graph.add_for_blobs(index, new_ids, new_cars, log=self.stdout.write)

    def _register(self, index):
        """Register every car actually present in the index (scales past the
        hand-maintained CAR_REGISTRY; unknown stems fall back to car_meta's
        heuristic)."""
        index.execute("DELETE FROM cars")
        rows = index.execute(
            "SELECT car_stem, COUNT(*) AS n FROM occurrences GROUP BY car_stem").fetchall()
        for r in rows:
            m = config.car_meta(r['car_stem'])
            index.execute(
                "INSERT OR REPLACE INTO cars(car_stem,brand,model,variant,year,n_occ,built_at) "
                "VALUES (?,?,?,?,?,?,datetime('now'))",
                (r['car_stem'], m['brand'], m['model'], m['variant'], m['year'], r['n']))
        index.commit()

    def _report_sizes(self, index):
        b = index.execute("SELECT COUNT(*) FROM blobs").fetchone()[0]
        o = index.execute("SELECT COUNT(*) FROM occurrences").fetchone()[0]
        e = index.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        try:
            v = index.execute("SELECT COUNT(*) FROM vec_blobs").fetchone()[0]
        except Exception:
            v = '?'
        self.stdout.write(f"  index: blobs={b}  vectors={v}  occurrences={o}  edges={e}")
