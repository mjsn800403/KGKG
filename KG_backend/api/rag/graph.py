"""Stage 3: build the blob-level relationship graph.

Edge types (all blob -> blob):
  * semantic   : kNN over the full-precision anchor embeddings -- conceptually
                 related pages that are NOT identical (identical content is one
                 blob already, so this captures genuine "see also" relations).
  * labor_time : the SAME kNN edge, but tagged specially when it bridges a
                 Labor-Times page and a repair/other page. The two trees use
                 different taxonomies (labor: "Brakes › Brake Hose › Remove &
                 Replace"; repair: "Brakes › Front Brake › Removal"), so an
                 exact path join finds almost nothing -- semantic similarity is
                 the robust way to connect a procedure with its labor time.
  * crosslink  : the manual's own href cross-references (page A links page B),
                 resolved within each car and deduplicated across the fleet.

"Same procedure across brand / model / type" is NOT stored as an edge: it is
simply the other rows in `occurrences` for the same blob (exact + free).
"""
import multiprocessing as mp
import os
import re
import signal

from . import config, store

_HREF_RE = re.compile(r'href="([^"]+)"')

# Same columns as store.init_index_schema's `edges`; the full rebuild writes
# into this staging table and swaps it in only when complete.
_EDGES_BUILD_DDL = """
    CREATE TABLE edges_build (
        src_blob INTEGER NOT NULL,
        dst_blob INTEGER NOT NULL,
        relation TEXT NOT NULL,
        weight   REAL DEFAULT 1.0
    )"""


def _ensure_edge_uniq(index):
    """A unique edge key makes edge insertion idempotent, so incremental adds
    can run repeatedly without duplicating edges. Safe to create after a full
    build (whose in-run `seen` dedup already guarantees no duplicates)."""
    index.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_edges_uniq "
        "ON edges(src_blob, dst_blob, relation)")
    index.commit()


def _vec_table(index):
    """The vector table to read for graph building: the full-precision
    `vec_build` while it still exists (during a full build), else the persisted
    int8 `vec_blobs` (so `--graph-only` / `--labor-only` run standalone after the
    float anchors have been dropped). Both are read with the same MATCH form."""
    r = index.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='vec_build'").fetchone()
    return 'vec_build' if r else 'vec_blobs'


def build_all(index, log=print):
    """Full rebuild. The new graph is written to `edges_build` and swapped in
    at the end, so the served `edges` stay intact if the run is interrupted
    (the old code deleted `edges` first, and a cancel left the graph empty).
    The sync marker is set stale up front so an interrupted run is resumed."""
    index.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('graph_synced_vectors','-1')")
    index.execute("DROP TABLE IF EXISTS edges_build")
    index.execute(_EDGES_BUILD_DDL)
    index.execute("CREATE UNIQUE INDEX idx_edges_build_uniq "
                  "ON edges_build(src_blob, dst_blob, relation)")
    index.commit()
    seen = set()                          # (src, dst, relation) dedup
    n_sem, _ = _semantic_edges(index, seen, log, table='edges_build')
    n_xl = _crosslink_edges(index, seen, log, table='edges_build')
    index.commit()
    n_lt = rebuild_labor_edges(index, log=log, seen=seen, table='edges_build')
    _swap_edges(index)
    log(f"    edges: semantic={n_sem}  crosslink={n_xl}  labor_time={n_lt}")
    return {'semantic': n_sem, 'labor_time': n_lt, 'crosslink': n_xl}


def _swap_edges(index):
    """Replace `edges` with the finished `edges_build` in one transaction.
    WAL readers keep seeing the old graph until the commit."""
    index.commit()
    index.execute("BEGIN IMMEDIATE")
    try:
        index.execute("DROP TABLE edges")
        index.execute("ALTER TABLE edges_build RENAME TO edges")
        index.execute("DROP INDEX idx_edges_build_uniq")
        index.execute("CREATE UNIQUE INDEX idx_edges_uniq ON edges(src_blob, dst_blob, relation)")
        index.execute("CREATE INDEX idx_edges_src ON edges(src_blob)")
        index.execute("COMMIT")
    except Exception:
        index.execute("ROLLBACK")
        raise


def _add(index, seen, src, dst, relation, weight, table='edges'):
    if src == dst:
        return 0
    key = (src, dst, relation)
    if key in seen:
        return 0
    seen.add(key)
    cur = index.execute(
        f"INSERT OR IGNORE INTO {table}(src_blob, dst_blob, relation, weight) VALUES (?,?,?,?)",
        (src, dst, relation, weight))
    return cur.rowcount or 0


def _graph_workers():
    """Processes for the semantic kNN pass (RAG_GRAPH_WORKERS; default leaves
    4 cores for the site)."""
    try:
        n = int(os.environ.get('RAG_GRAPH_WORKERS', '0'))
    except ValueError:
        n = 0
    if n <= 0:
        n = (os.cpu_count() or 1) - 4
    return max(1, n)


# Per-worker state. `kind` is set in the parent before the pool forks, so the
# 300k-entry map is inherited instead of pickled to every worker.
_W = {}


def _sem_init(path, vtab):
    # the pipeline's SIGTERM handler raises _Canceled; workers must just exit
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    conn = store.open_index(path, write=False)
    conn.execute('PRAGMA query_only=1')
    _W['conn'] = conn
    _W['vtab'] = vtab


def _sem_chunk(blob_ids):
    """kNN for a slice of blobs -> [(src, dst, 'semantic', sim)]. Same rules as
    the old sequential loop."""
    conn, vtab, blob_kind = _W['conn'], _W['vtab'], _W['kind']
    qexpr = '?' if vtab == 'vec_build' else 'vec_int8(?)'
    k = config.SEMANTIC_K + 1
    out = []
    for blob in blob_ids:
        row = conn.execute(f"SELECT embedding FROM {vtab} WHERE rowid=?", (blob,)).fetchone()
        if row is None:
            continue
        res = conn.execute(
            f"SELECT rowid, distance FROM {vtab} WHERE embedding MATCH {qexpr} AND k=? ORDER BY distance",
            (row['embedding'], k)).fetchall()
        for nb in res:
            nbid = nb['rowid']
            if nbid == blob:
                continue
            sim = 1.0 - float(nb['distance'])
            if sim < config.SEMANTIC_MIN_SIM:
                continue
            # skip cross-kind (labor<->non-labor); the labor pass owns those
            if (blob_kind.get(blob) == 'labor') != (blob_kind.get(nbid) == 'labor'):
                continue
            out.append((blob, nbid, 'semantic', round(sim, 4)))
    return out


# --- semantic: same-kind "see also" kNN over blob vectors -------------------
def _semantic_edges(index, seen, log, table='edges'):
    """Connect conceptually-related, same-kind pages. labor<->repair links are
    NOT made here -- they are built by the dedicated, verb/scope-aware
    rebuild_labor_edges() pass, because the labor and repair taxonomies phrase
    the same component differently and need precision filters the raw cosine
    floor can't provide.

    Each blob's kNN is independent, so the queries run in a process pool (one
    read-only connection per worker); only this process writes. Edges are keyed
    (src, dst, 'semantic'), which no other pass produces, so `seen` is not
    needed here -- the unique index dedups."""
    vtab = _vec_table(index)
    blob_kind = {r['blob_id']: r['kind']
                 for r in index.execute("SELECT blob_id, kind FROM blobs")}
    ids = list(blob_kind.keys())
    path = index.execute("PRAGMA database_list").fetchone()['file']
    workers = _graph_workers()
    chunk = 500
    chunks = [ids[i:i + chunk] for i in range(0, len(ids), chunk)]
    log(f"    semantic kNN: {len(ids)} blobs, {workers} workers")
    _W['kind'] = blob_kind
    n_sem = 0
    done = 0
    step = max(1, len(chunks) // 20)
    try:
        with mp.get_context('fork').Pool(workers, initializer=_sem_init,
                                         initargs=(path, vtab)) as pool:
            for i, rows in enumerate(pool.imap_unordered(_sem_chunk, chunks), 1):
                if rows:
                    before = index.total_changes
                    index.executemany(
                        f"INSERT OR IGNORE INTO {table}(src_blob, dst_blob, relation, weight) "
                        "VALUES (?,?,?,?)", rows)
                    n_sem += index.total_changes - before
                done += 1
                if i % step == 0:
                    index.commit()
                    log(f"    semantic kNN: {done}/{len(chunks)} chunks, {n_sem} edges")
    finally:
        _W.pop('kind', None)
    index.commit()
    return n_sem, 0


# --- labor_time: dedicated, verb- and scope-aware procedure<->labor linker ---
# Action verb classes (the "work-model"): a labor entry's verb is the last
# breadcrumb segment ("Remove & Replace", "Bleed", "Check"...); a repair page's
# verb is in its leaf title ("Removal", "Installation", "Bleeding"...). A link is
# only made between compatible verbs, which kills the "check vs adjust" and
# "R&R vs overview-page" mismatches that a pure-similarity link produces.
_ACTION_CLASSES = [
    ('replace',  ('remove & replace', 'remove and replace', 'removal', 'install',
                  'installation', 'replacement', 'replace', 'r & r', 'r&r')),
    ('overhaul', ('overhaul', 'disassembly', 'reassembly', 'assembly')),
    ('refinish', ('refinish', 'resurface', 'machining')),
    ('bleed',    ('bleeding', 'bleed')),
    ('fluid',    ('drain & refill', 'drain and refill', 'flush', 'refill',
                  'recover', 'recharge', 'evacuate', 'charge')),
    ('inspect',  ('on-vehicle inspection', 'inspection', 'inspect', 'testing',
                  'test', 'measurement', 'measure', 'check')),
    ('adjust',   ('adjustment', 'adjust', 'calibrat', 'initializ', 'registration', 'reset')),
    ('diagnose', ('diagnosis', 'diagnostic', 'trouble', 'dtc')),
    ('balance',  ('balance', 'alignment', 'rotation', 'rotate')),
]
# verb pairs that are compatible across (but not within) classes
_VERB_COMPAT = {('replace', 'overhaul'), ('replace', 'refinish'), ('fluid', 'bleed'),
                ('inspect', 'diagnose')}


def _action_class(text):
    t = (text or '').lower()
    for cls, kws in _ACTION_CLASSES:
        for kw in kws:
            if kw in t:
                return cls
    return None


def _verb_compatible(a, b):
    # require a recognisable action on BOTH sides -> excludes nav/overview pages
    if not a or not b:
        return False
    if a == b:
        return True
    return (a, b) in _VERB_COMPAT or (b, a) in _VERB_COMPAT


# --- component agreement (the gate that stops cross-component labor links) ---
# The parser lives in config alongside the other breadcrumb rules, because the
# retrieval scope guard applies the same test and the two must not drift.
# with_parent=True on the labor side: that is where the manual carries the
# directional qualifier ("Axle Shafts - Front" > "Axle Shaft Assembly").
def _component_compatible(labor_comp, repair_comp):
    return config.components_compatible(labor_comp, repair_comp, a_with_parent=True)


def _component_words(comp_readable, with_parent=False):
    return config.component_words(comp_readable, with_parent=with_parent)


def _blob_cars(index):
    cars = {}
    for r in index.execute("SELECT blob_id, car_stem FROM occurrences"):
        cars.setdefault(r['blob_id'], set()).add(r['car_stem'])
    return cars


def rebuild_labor_edges(index, log=print, seen=None, table='edges'):
    """(Re)build labor_time edges only -- the work-model link between a repair
    procedure and its Labor-Times entry.

    For each labor blob (only hundreds, so O(labor) regardless of fleet size):
    kNN over the PERSISTED int8 vectors to find the most similar repair pages,
    then keep a link only when (a) similarity >= LABOR_MIN_SIM, (b) a compatible
    action verb, and (c) a shared vehicle (so a Toyota labor time never attaches
    to a Lexus procedure). Edges are written BOTH ways so _expand finds them from
    either side. Idempotent; safe to run standalone (uses vec_blobs, not the
    transient float anchors), so `build_rag --labor-only` needs no re-embed."""
    _ensure_edge_uniq(index)
    if seen is None:
        seen = set()
    index.execute(f"DELETE FROM {table} WHERE relation='labor_time'")
    index.commit()

    kind = {r['blob_id']: r['kind'] for r in index.execute("SELECT blob_id, kind FROM blobs")}
    # action verb is read from the LEAF TITLE only (labor titles end with the
    # action, e.g. "Brake Hose: Remove & Replace"; repair titles are the page
    # type, e.g. "Removal"/"Bleeding"/"Components"). Using the title -- not the
    # full breadcrumb -- keeps boilerplate sub-pages ("Caution / Notice / Hint")
    # actionless, so they are never linked as a procedure.
    title = {r['blob_id']: (r['title'] or '')
             for r in index.execute("SELECT blob_id, title FROM blobs")}
    # component breadcrumb, for the component-agreement gate below
    comp = {r['blob_id']: (r['comp_readable'] or '')
            for r in index.execute("SELECT blob_id, comp_readable FROM blobs")}
    cars = _blob_cars(index)
    labor_ids = [b for b, k in kind.items() if k == 'labor']

    n = 0
    k = config.LABOR_K + 1
    for lb in labor_ids:
        vrow = index.execute("SELECT embedding FROM vec_blobs WHERE rowid=?", (lb,)).fetchone()
        if vrow is None:
            continue
        l_act = _action_class(title.get(lb, ''))
        if not l_act:
            continue
        l_cars = cars.get(lb, set())
        res = index.execute(
            "SELECT rowid, distance FROM vec_blobs WHERE embedding MATCH vec_int8(?) AND k=? ORDER BY distance",
            (vrow['embedding'], k)).fetchall()
        made = 0
        for nb in res:
            rid = nb['rowid']
            if rid == lb or kind.get(rid) == 'labor':
                continue
            sim = 1.0 - float(nb['distance'])
            if sim < config.LABOR_MIN_SIM:
                continue
            if l_cars and cars.get(rid) and not (l_cars & cars[rid]):
                continue                       # scope guard: must share a vehicle
            if not _verb_compatible(l_act, _action_class(title.get(rid, ''))):
                continue
            # component gate: similarity + verb + shared car still let a brake
            # labor entry attach to a transaxle inspection, because page vectors
            # are dominated by page-kind boilerplate. Require the two
            # breadcrumbs to name the same part.
            if not _component_compatible(comp.get(lb, ''), comp.get(rid, '')):
                continue
            added = False
            for a, b in ((lb, rid), (rid, lb)):
                if _add(index, seen, a, b, 'labor_time', round(sim, 4), table=table):
                    added = True
                    n += 1
            if added:
                made += 1
                if made >= config.LABOR_MAX_PER_BLOB:
                    break
    index.commit()
    log(f"    labor_time edges (sim+verb+scope): {n}")
    return n


# --- incremental: edges for a set of newly-added blobs ----------------------
def add_for_blobs(index, new_ids, new_cars, log=print):
    """Wire newly-added pages into the existing graph WITHOUT rebuilding it.

    For each new blob: kNN over the served int8 vectors (which already hold every
    page) to find neighbours, adding edges in BOTH directions so the new page is
    reachable from existing pages and vice versa. Then add crosslink edges for
    just the new cars. Idempotent (INSERT OR IGNORE on the unique edge key), so
    re-running an add is harmless. This is O(new pages), not O(all)."""
    new_ids = list(new_ids)
    if not new_ids:
        log("    no new pages -> graph unchanged")
        return {'semantic': 0, 'labor_time': 0, 'crosslink': 0}
    _ensure_edge_uniq(index)
    blob_kind = {r['blob_id']: r['kind']
                 for r in index.execute("SELECT blob_id, kind FROM blobs")}
    seen = set()
    n_sem = n_lt = 0
    k = config.SEMANTIC_K + 1
    for blob in new_ids:
        # read the new blob's vector from the PERSISTED int8 table (always
        # present), so this works whether or not the float anchors still exist
        row = index.execute("SELECT embedding FROM vec_blobs WHERE rowid=?", (blob,)).fetchone()
        if row is None:
            continue
        res = index.execute(
            "SELECT rowid, distance FROM vec_blobs WHERE embedding MATCH vec_int8(?) AND k=? ORDER BY distance",
            (row['embedding'], k)).fetchall()
        for nb in res:
            nbid = nb['rowid']
            if nbid == blob:
                continue
            sim = 1.0 - float(nb['distance'])
            if sim < config.SEMANTIC_MIN_SIM:
                continue
            # same-kind "see also" only; labor<->repair handled below
            if (blob_kind.get(blob) == 'labor') != (blob_kind.get(nbid) == 'labor'):
                continue
            for a, b in ((blob, nbid), (nbid, blob)):
                if _add(index, seen, a, b, 'semantic', round(sim, 4)):
                    n_sem += 1
    n_xl = _crosslink_edges(index, seen, log, cars=new_cars)
    index.commit()
    # labor linkage is O(labor) and global, so just rebuild it after any add
    n_lt = rebuild_labor_edges(index, log=log, seen=seen)
    log(f"    +edges: semantic={n_sem}  crosslink={n_xl}  labor_time(total)={n_lt}")
    return {'semantic': n_sem, 'labor_time': n_lt, 'crosslink': n_xl}


# --- crosslink: the manual's own href references ----------------------------
def _crosslink_edges(index, seen, log, cars=None, table='edges'):
    n = 0
    files = config.car_db_files()
    if cars is not None:
        cars = set(cars)
        files = [f for f in files if f.stem in cars]
    for f in files:
        stem = f.stem
        node2blob = {r['node_id']: r['blob_id'] for r in index.execute(
            "SELECT node_id, blob_id FROM occurrences WHERE car_stem=?", (stem,))}
        if not node2blob:
            continue
        src = store.open_car_ro(f)
        try:
            href_index = {}
            for r in src.execute("SELECT id, href FROM nodes WHERE href IS NOT NULL"):
                fn = r['href'].rstrip('/').split('/')[-1]
                href_index.setdefault(fn, r['id'])
            rows = src.execute(
                "SELECT id, content FROM nodes WHERE content IS NOT NULL").fetchall()
        finally:
            src.close()
        for r in rows:
            s_blob = node2blob.get(r['id'])
            if s_blob is None:
                continue
            done = set()
            for href in _HREF_RE.findall(r['content'] or ''):
                fn = href.split('#')[0].rstrip('/').split('/')[-1]
                if not fn or fn in done:
                    continue
                done.add(fn)
                tgt_node = href_index.get(fn)
                if tgt_node is None:
                    continue
                d_blob = node2blob.get(tgt_node)
                if d_blob is not None:
                    n += _add(index, seen, s_blob, d_blob, 'crosslink', 1.0, table=table)
    index.commit()
    return n
