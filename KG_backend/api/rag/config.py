"""Central configuration for the RAG / relationship-graph subsystem.

Design (content-addressed, deduplicated):
  * Every manual page's cleaned text is hashed. Identical content across the
    fleet is stored and embedded ONCE (a "blob"); the places it appears live in
    an `occurrences` table. Across the 9 cars, 263k leaves collapse to ~73k
    unique blobs (72% are exact duplicates), so we embed ~4x less.
  * A single unified index DB (index.rag.db) holds blobs / occurrences / chunks
    / vectors / FTS / graph edges. No per-car sidecars.
  * Relationship graph is blob-level: `semantic` (kNN over embeddings),
    `crosslink` (the manual's own href references) and `labor_time` (a repair
    procedure linked to its Labor-Times page by matching component path).
    "Same procedure across brand / model / type" is NOT an edge -- it is simply
    the other `occurrences` of the same blob, which is exact and free.

Nothing here ever writes to the original car databases or db.sqlite3. Every
artefact lives under Database_warehouse/_rag/ and can be deleted to fully revert.
"""
import os
import re
from pathlib import Path
from django.conf import settings

# ---------------------------------------------------------------------------
# Filesystem layout
# ---------------------------------------------------------------------------
BASE_DIR = Path(settings.DATABASES['default']['NAME']).parent
WAREHOUSE_DIR = BASE_DIR / 'Database_warehouse'
RAG_DIR = WAREHOUSE_DIR / '_rag'              # all output (deletable)
# RAG_INDEX_DB lets an offline experiment point at an alternate index copy
# without touching production. Unset in .env.prod -> production is unaffected.
INDEX_DB = Path(os.environ.get('RAG_INDEX_DB') or (RAG_DIR / 'index.rag.db'))

# Bilingual terminology store (terms + generation queue) and the en->fa display
# artifact generated from it (consumed by the Next chat route). Both live under
# _rag/ like every other derived artefact. See api/rag/terms.py.
TERMS_DB = RAG_DIR / 'terms.db'
TERMS_JSON = RAG_DIR / 'terms_en_fa.json'

# Per-car diagnostic sidecars (the DTC / symptom rule-engine layer). One small,
# self-contained DB per car under _rag/diag/, derived from that car's `nodes`
# tree (DTC subtrees + Problem Symptoms Tables) plus the unified index's edges.
# Fully additive: delete the whole folder and the site degrades to general RAG.
DIAG_DIR = RAG_DIR / 'diag'


def diag_db_path(car_stem):
    """Sidecar DB path for one car (keyed by the on-disk DB filename stem)."""
    return DIAG_DIR / f'{car_stem}.diag.db'

# Folders / files inside the warehouse that are NOT cars (skip when globbing).
_NON_CAR_PREFIXES = ('_rag', '_backup')


# ---------------------------------------------------------------------------
# Parts translation dictionary (Persian <-> English part names)
# ---------------------------------------------------------------------------
# A user-maintained SQLite DB (translation.db, Book1 table: field1=English,
# field2=Persian). The glossary reads it at startup and reloads on mtime change.
# Resolution order: env override -> project root -> backend dir.
def _resolve_parts_db():
    candidates = []
    env = os.environ.get('RAG_PARTS_DB')
    if env:
        candidates.append(Path(env))
    candidates += [
        BASE_DIR.parent / 'translation.db',
        BASE_DIR / 'translation.db',
    ]
    for p in candidates:
        if p.exists():
            return p
    return candidates[-1]


PARTS_DB = _resolve_parts_db()
# Minimum normalised length (chars) for a CSV Persian phrase to be used as a
# query-expansion key -- guards against very short, ambiguous parts (e.g. "بست")
# polluting unrelated queries. The hand-curated map keeps its own short keys.
PARTS_MIN_KEY_CHARS = 5
# Cap on English terms appended to one query, so part-heavy matches never bloat
# (and dilute) the embedded query / FTS query.
GLOSSARY_MAX_TERMS = 16


def car_db_files():
    """All real car DB files on disk (top-level *.db, excluding our own
    sidecar/backup folders). Returns a sorted list of Path."""
    out = []
    for p in sorted(WAREHOUSE_DIR.glob('*.db')):
        if any(p.name.startswith(pre) for pre in _NON_CAR_PREFIXES):
            continue
        out.append(p)
    return out


# ---------------------------------------------------------------------------
# Car metadata registry
# ---------------------------------------------------------------------------
# Explicit, transparent mapping from the on-disk DB filename stem to
# (brand, model, variant, year). `model` groups "types of the same model"
# (e.g. the five bZ4X variants); `brand` groups "models of the same brand".
# Editable by hand as cars are added; a heuristic fallback keeps the build from
# crashing on an unregistered file.
CAR_REGISTRY = {
    'Corolla Cross Hybrid S':               dict(brand='Toyota', model='Corolla Cross', variant='Hybrid S',              year=2025),
    'Land Cruiser Base':                    dict(brand='Toyota', model='Land Cruiser',  variant='Base',                  year=2025),
    'RAV4 Hybrid SE, 2.5L Eng VIN 6 (1)':   dict(brand='Toyota', model='RAV4',          variant='Hybrid SE 2.5L VIN 6',  year=2025),
    'bZ4X Limited, AWD':                    dict(brand='Toyota', model='bZ4X',          variant='Limited AWD',           year=2025),
    'bZ4X Limited, FWD':                    dict(brand='Toyota', model='bZ4X',          variant='Limited FWD',           year=2025),
    'bZ4X Nightshade':                      dict(brand='Toyota', model='bZ4X',          variant='Nightshade',            year=2025),
    'bZ4X XLE, AWD':                        dict(brand='Toyota', model='bZ4X',          variant='XLE AWD',               year=2025),
    'bZ4X XLE, FWD':                        dict(brand='Toyota', model='bZ4X',          variant='XLE FWD',               year=2025),
    'NX 350h':                              dict(brand='Lexus',  model='NX 350h',       variant='',                      year=2025),
}

_LEXUS_PREFIXES = ('NX', 'RX', 'ES', 'IS', 'UX', 'GX', 'LX', 'LS', 'RC', 'LC')

# Multi-year stems: the 2025 fleet keeps plain names; other model years carry
# a " (YYYY)" suffix (e.g. 'Corolla Cross LE, FWD (2023)') so the same trim
# can exist for several years as distinct cars. See htmlparser_logical.
_STEM_YEAR_RE = re.compile(r'\s*\((\d{4})\)\s*$')


def split_stem_year(car_stem):
    """('Corolla Cross LE, FWD', 2023) for a year-suffixed stem;
    (stem, None) for a plain one."""
    m = _STEM_YEAR_RE.search(car_stem)
    if m:
        return car_stem[:m.start()].strip(), int(m.group(1))
    return car_stem, None


def display_name(car_stem):
    """Human-facing car name: the stem without the year suffix (the year is
    shown separately from the catalog's year column)."""
    return split_stem_year(car_stem)[0]

_CATALOG_CACHE = None


def _catalog_meta(car_stem):
    """(brand, year) for a stem from the main catalog DB (car_name == car_stem
    by convention, verified against occurrences). This is what actually makes a
    generated /brand/year/name link resolvable by car_view, so it outranks any
    heuristic. Read-only direct sqlite (builds may run without a warm ORM);
    cached for the process lifetime; never raises."""
    global _CATALOG_CACHE
    if _CATALOG_CACHE is None:
        rows = {}
        try:
            import sqlite3
            con = sqlite3.connect(
                f"file:{Path(settings.DATABASES['default']['NAME'])}?mode=ro",
                uri=True)
            try:
                for name, brand, year in con.execute(
                        'SELECT car_name, brand_name, year FROM main_db'):
                    rows[name] = (brand, year)
            finally:
                con.close()
        except Exception:
            pass                      # catalog unavailable -> heuristic fallback
        _CATALOG_CACHE = rows
    return _CATALOG_CACHE.get(car_stem)


def car_meta(car_stem):
    """Brand/model/variant/year for a car stem: explicit registry first, then
    the main catalog (authoritative brand/year — a wrong or missing year here
    produces app links car_view cannot resolve), then a conservative heuristic
    so the build never crashes on an unregistered file."""
    if car_stem in CAR_REGISTRY:
        return dict(CAR_REGISTRY[car_stem], car_stem=car_stem)
    base, stem_year = split_stem_year(car_stem)
    first = base.split()[0] if base.split() else base
    brand = 'Lexus' if first in _LEXUS_PREFIXES else 'Toyota'
    model = base.split(',')[0].strip()
    cat = _catalog_meta(car_stem)
    if cat:
        return dict(brand=cat[0] or brand, model=model, variant='',
                    year=cat[1] or stem_year, car_stem=car_stem)
    return dict(brand=brand, model=model, variant='', year=stem_year,
                car_stem=car_stem)


# ---------------------------------------------------------------------------
# Content classification (cheap, structural -- drives the labor<->repair graph)
# ---------------------------------------------------------------------------
# The shallowest breadcrumb level tells us what KIND of page this is.
LABOR_ROOTS = ('labor times',)
REPAIR_ROOTS = ('repair and diagnosis', 'repair and diagnosis (single page)')
# Breadcrumb tokens that are structural noise, dropped when building the
# component key used to align a Labor-Times page with its repair procedure.
_DROP_CRUMB_TOKENS = ('other variant',)


# Near-miss scope guard: warn when vehicle-scoping substituted a different
# component (see _evidence_scope). On by default; set RAG_NEARMISS_GUARD=0 to
# fall back to the title-anchored guard alone without a deploy.
NEARMISS_GUARD = os.environ.get('RAG_NEARMISS_GUARD', '1') != '0'

# comp_readable is a breadcrumb, not a component name: its last segments are
# actions and page kinds ("... > Millimeter Wave Radar Sensor > Removal >
# Procedure"). Walking back past those lands on the component itself. Shared by
# the labor<->repair graph gate and the retrieval scope guard so the two cannot
# drift apart.
_NON_COMPONENT = (
    'remove', 'replace', 'install', 'removal', 'installation', 'reassembly',
    'disassembly', 'overhaul', 'adjustment', 'adjust', 'inspection', 'inspect',
    'diagnosis', 'diagnostic', 'testing', 'test', 'procedure', 'components',
    'precaution', 'description', 'bleeding', 'bleed', 'balance', 'alignment',
    'rotation', 'refinish', 'calibration', 'initialization', 'registration',
    'reset', 'measurement', 'check', 'service information', 'parts location',
    'illustration', 'wiring diagram', 'system diagram', 'data list',
    'maintenance overview', 'operation check',
)
# Words too generic to be evidence that two names mean the same part.
_GENERIC_WORDS = frozenset((
    'assembly', 'assy', 'sub', 'system', 'systems', 'unit', 'and', 'the', 'for',
    'with', 'complete', 'type', 'side', 'set', 'kit', 'component', 'components',
))
# Qualifiers that make two otherwise-similar names DIFFERENT parts.
_DIRECTIONS = (
    frozenset(('front', 'rear')), frozenset(('front', 'back')),
    frozenset(('left', 'right')), frozenset(('lh', 'rh')),
    frozenset(('upper', 'lower')), frozenset(('inner', 'outer')),
    frozenset(('no1', 'no2')), frozenset(('no2', 'no3')), frozenset(('no1', 'no3')),
)


def _is_component_seg(seg):
    s = seg.lower().strip()
    return not any(s == kw or s.startswith(kw) for kw in _NON_COMPONENT)


def component_segment(comp_readable):
    """The component segment of a comp_readable breadcrumb ('' if none)."""
    segs = [s.strip() for s in (comp_readable or '').split(' › ') if s.strip()]
    for i in range(len(segs) - 1, -1, -1):
        if _is_component_seg(segs[i]):
            return segs[i]
    return ''


def component_words(comp_readable, with_parent=False):
    """Content words of the component segment.

    ``with_parent`` also folds in the segment above it, which is where the
    manual carries the directional qualifier on the Labor-Times side
    ("Axle Shafts - Front" > "Axle Shaft Assembly"); without it a REAR axle
    labor entry matches a FRONT drive shaft procedure."""
    segs = [s.strip() for s in (comp_readable or '').split(' › ') if s.strip()]
    picked = []
    for i in range(len(segs) - 1, -1, -1):
        if _is_component_seg(segs[i]):
            picked.append(segs[i])
            if with_parent and i > 0:
                picked.append(segs[i - 1])
            break
    out = set()
    for seg in picked:
        norm = ''.join(c.lower() if c.isalnum() else ' ' for c in seg)
        for w in norm.split():
            if len(w) > 2 and w not in _GENERIC_WORDS:
                out.add(w)
    return out


def components_compatible(a_comp, b_comp, a_with_parent=True):
    """True when two breadcrumbs name the same component.

    Deliberately conservative -- an unidentifiable component on either side is a
    reject, because the point is to stop a claim nobody checked."""
    aw = component_words(a_comp, with_parent=a_with_parent)
    bw = component_words(b_comp)
    if not aw or not bw:
        return False
    for pair in _DIRECTIONS:
        if (aw & pair) and (bw & pair) and (aw & pair) != (bw & pair):
            return False
    if aw <= bw or bw <= aw:
        return True
    return len(aw & bw) >= 2


# ---------------------------------------------------------------------------
# Embedding model (selectable; local + multilingual so a Persian query matches
# the English manual content directly, offline after first download)
# ---------------------------------------------------------------------------
# Pick with env RAG_EMBED_MODEL (bge-m3 | e5-base | minilm). The SAME value must
# be set when building and when serving -- the served vectors are model- and
# dimension-specific. A guard in retrieve.assist refuses to answer on a mismatch.
#
#   bge-m3  : best cross-lingual quality, 1024-dim, ~568M params (heavy: ~4 ch/s
#             and ~2.3GB resident on a RAM-limited Mac).
#   e5-base : strong cross-lingual, 768-dim, ~278M (≈2x faster, ~1.1GB) -- needs
#             "query:"/"passage:" instruction prefixes.
#   minilm  : lightest, 384-dim, ~118M (fastest, ~0.5GB; lower cross-lingual
#             recall, leans more on the keyword/FTS half of the hybrid search).
EMBED_PRESETS = {
    'bge-m3': dict(name='BAAI/bge-m3', dim=1024, query_prefix='', passage_prefix=''),
    'e5-base': dict(name='intfloat/multilingual-e5-base', dim=768,
                    query_prefix='query: ', passage_prefix='passage: '),
    'minilm': dict(name='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2',
                   dim=384, query_prefix='', passage_prefix=''),
}
EMBED_KEY = os.environ.get('RAG_EMBED_MODEL', 'bge-m3').strip().lower()
_PRESET = EMBED_PRESETS.get(EMBED_KEY, EMBED_PRESETS['bge-m3'])
EMBED_MODEL = _PRESET['name']
EMBED_DIM = _PRESET['dim']
QUERY_PREFIX = _PRESET['query_prefix']
PASSAGE_PREFIX = _PRESET['passage_prefix']

# Serving vectors are int8 (4x smaller, faster to scan, negligible recall loss
# for unit-normalised embeddings). Full-precision float is used only transiently
# while building the semantic graph, then dropped.
SERVE_QUANT = 'int8'

# Load the model in float16 on Apple-Silicon GPU (MPS). On this class of machine
# fp16 roughly TRIPLES embedding throughput (≈2 -> ≈6 pages/s for bge-m3) and
# halves resident memory (~2.3GB -> ~1.2GB), which also avoids the swap-induced
# slowdowns that made fp32 stall. Ignored on CPU (where fp32 is faster).
EMBED_FP16 = os.environ.get('RAG_EMBED_FP16', '1') != '0'

# ---------------------------------------------------------------------------
# Embedding granularity
# ---------------------------------------------------------------------------
# One vector PER PAGE (blob), not per chunk -- on a RAM-limited Mac this halves
# the vector count (~87k -> ~46k => ~3-4h instead of ~6-10h) and keeps each
# encode a short, uniform sequence (no long-sequence swap stalls -> stable).
# The page's component breadcrumb is prepended so the vector is self-describing;
# keyword recall for anything past the head is covered by the full-text (FTS)
# half of the hybrid search, which indexes the entire page.
# Hard cap on tokens per page. CRITICAL on MPS: bge-m3's max context is 8192,
# and the attention buffer is allocated for the model's max sequence length
# (16 heads x 8192 x 8192 x 4B = 4 GiB) which aborts Metal on a RAM-limited Mac.
# Capping to 256 makes that buffer ~4 MB. Our page head (~800 chars ≈ 250 tokens)
# fits comfortably, so retrieval quality is unaffected.
MAX_SEQ_LEN = 256
EMBED_TEXT_CHARS = 800      # chars of page text fed to the embedder (head).
                            # 800 @ fp16 ≈ 9 pages/s on this Mac (~1.5h full build)
                            # vs 1600 ≈ 6/s; the page's component breadcrumb +
                            # first ~800 chars is plenty to place it semantically,
                            # and FTS still indexes the entire page text.
MIN_TEXT_CHARS = 20         # skip essentially-empty pages

# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------
SEMANTIC_K = 8              # kNN neighbours per blob
SEMANTIC_MIN_SIM = 0.62     # cosine floor for a semantic edge (identical content
                            # is already merged into one blob, so this floor only
                            # captures genuinely related-but-distinct pages)

# labor_time edges (the "work-model" link: a repair procedure <-> its Labor-Times
# entry). Built by a dedicated pass over the ~hundreds of labor blobs only, so it
# is O(labor) regardless of fleet size. The labor and repair trees name the same
# component differently, so we match on embedding similarity (lower floor than
# the generic semantic edge), then REQUIRE a compatible action verb and a shared
# vehicle (no cross-brand leak). Tunable; rebuild with `build_rag --labor-only`.
LABOR_K = 60                # candidate neighbours scanned per labor blob
LABOR_MIN_SIM = 0.40        # cosine floor for a labor<->repair link (precision is
                            # carried by the verb + shared-vehicle filters, so the
                            # similarity floor can stay permissive for recall)
LABOR_MAX_PER_BLOB = 12     # cap repair links emitted per labor entry

# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------
RETRIEVE_VEC_K = 40         # chunk candidates from vector search
RETRIEVE_FTS_K = 40         # chunk candidates from keyword search
# Scope-aware retrieval: when the user is on a specific vehicle/model/brand we
# OVER-FETCH candidates so the car's own pages aren't crowded out of the global
# top-K by other vehicles, and we mildly penalise blobs that match NO part of
# the active scope (a foreign / cross-brand page). The graded BOOST_CAR/MODEL/
# BRAND below still does the fine ordering; this only stops truly out-of-scope
# content tying with in-scope content. Cross-vehicle corroboration is untouched
# (it is surfaced separately, not through the main ranking).
SCOPED_VEC_K = 120          # vector candidates when a scope is given
SCOPED_FTS_K = 120          # keyword candidates when a scope is given
SCOPE_PENALTY = 0.85        # multiplier for a blob absent from the active scope
RRF_K = 60                  # reciprocal-rank-fusion constant
FINAL_K = 8                 # blobs returned to the generator
GRAPH_EXPAND = 4            # related neighbours pulled in per top hit
CROSS_VEHICLE_MAX = 4       # sibling-vehicle corroborations shown per hit

# ---------------------------------------------------------------------------
# Hybrid scoring + adaptive depth (query-time only; no rebuild, no new model)
# ---------------------------------------------------------------------------
# Calibrated blend weights handed to scoring.calibrate() (sum need not be 1; the
# multiplicative boosts ride on top). Tune live — they only re-rank, never
# re-embed. See scoring.py for the formula.
# BM25 per-column weights for blobs_fts(text, title, comp). SQLite's bm25()
# defaults to 1.0 for every column, which rates a term in the page title exactly
# as highly as one buried in the body -- and in a service manual the title is the
# component name. Overridable so the A/B (hybrid_tw) can vary them without a
# code change.
#
# Title 8 / comp 4 measured against 1/1/1 on 250 queries per language (hybrid_tw):
#   EN  nDCG@5 +0.025 p<0.001   Hit@1 +0.052 p=0.004   Hit@5 +0.040 p<0.001
#   FA  nDCG@5 +0.012 p=0.021   MRR   +0.022 p=0.012
# Every metric improved on both languages at identical latency; Hit@5 on English
# moved on 10 queries with none regressing.
# Clean the FTS MATCH string before it is ORed together: drop English stopwords
# (glossary expansion drags in "and"/"for"/"with", which match 143k-207k of the
# 301,369 pages and flatten BM25), drop tokens that cannot match the English
# index at all (Persian query tokens -- measured at 9.0 per Persian query, all
# matching zero pages), and de-duplicate.
#
# Measured (hybrid_fc, n=250 EN + 250 FA + 51 FA-llm): ranking is UNCHANGED --
# Persian moved on 0 queries, English on 2 (Hit@1 -0.008, p=0.27). BM25 already
# discounts a term appearing on 67% of pages to near-zero IDF, so the stopwords
# were never the ranking problem they looked like. What it does buy is latency:
# p50 1168->819ms EN, 1048->842ms FA, from a much shorter MATCH string.
FTS_CLEAN = os.environ.get('RAG_FTS_CLEAN', '1') == '1'
# Functional words only. Deliberately NOT including "no": Toyota titles use
# "No. 1"/"No. 2" as part identifiers, and stripping it would lose real matches.
FTS_STOPWORDS = frozenset('''
and or the a an of to in on at by is are be was were from with for this that it
as its their there then than which when where while into over under
'''.split())

FTS_W_TEXT = float(os.environ.get('RAG_FTS_W_TEXT', '1.0'))
FTS_W_TITLE = float(os.environ.get('RAG_FTS_W_TITLE', '4.0'))
FTS_W_COMP = float(os.environ.get('RAG_FTS_W_COMP', '12.0'))

SCORE_W_RRF = 0.30          # fused reciprocal-rank weight
SCORE_W_SIM = 0.45          # dense cosine similarity weight
SCORE_W_BM25 = 0.20         # normalized BM25 (keyword strength) weight
SCORE_W_CENT = 0.05         # graph-centrality ("canonical hub") weight
CENTRALITY_C = 8.0          # degree/(degree+C) soft-normalisation constant

# Adaptive retrieval depth: an easy query (clear top winner + strong match)
# returns fewer hits and expands fewer graphs; an ambiguous one widens. Cuts the
# average request's work while spending more only where it helps accuracy.
# Per-car site search over-fetches, because it filters out hits whose occurrence
# belongs to another car and that filter runs after ranking. 4x covers the
# measured ~70% drop rate with headroom; the cap keeps a limit=50 request from
# asking for more candidates than the scoped pool (SCOPED_VEC_K) even holds.
# Depth of the car-scoped keyword pass (retrieve.assist(scope_fts=True)).
# 30 already yields a median of 30 in-car candidates where the global pool of 120
# yields 13, so deeper buys little.
SCOPE_FTS_K = int(os.environ.get('RAG_SCOPE_FTS_K', '30'))
# How deep the single-table FTS scan goes before intersecting with the car's own
# blobs. Deep enough that a car holding ~2% of the corpus still yields SCOPE_FTS_K.
SCOPE_FTS_SCAN = int(os.environ.get('RAG_SCOPE_FTS_SCAN', '4000'))
# Per-car blob-id sets cached in memory (~7k ints each).
CAR_BLOBS_CACHE = int(os.environ.get('RAG_CAR_BLOBS_CACHE', '8'))
# Site search's own corpus-boundary floor, applied per hit and only when the
# retriever already flagged the query as ungrounded. Measured: real queries land
# at 0.63-0.67 vector similarity, absent/gibberish ones at 0.45-0.52. Swept
# against both costs: 0.55 leaves 1 of 81 real queries empty and suppresses the
# same junk as 0.58, which leaves 3 empty -- so 0.55 strictly dominates it.
SEARCH_SIM_FLOOR = float(os.environ.get('RAG_SEARCH_SIM_FLOOR', '0.55'))
SEARCH_OVERFETCH = int(os.environ.get('RAG_SEARCH_OVERFETCH', '4'))
SEARCH_MAX_DEPTH = int(os.environ.get('RAG_SEARCH_MAX_DEPTH', '120'))

FINAL_K_MIN = 4             # hits returned for an easy/clear query
FINAL_K_MAX = FINAL_K       # hits returned for an ambiguous query
MARGIN_EASY = 0.20          # top1-top2 fused-score gap above which a query is "easy"
EASY_SIM = 0.72             # ...and the top cosine must clear this too
EXPAND_EASY = 2             # graphs expanded (top-N hits) on an easy query

# Confidence bands (high-stakes UI). Passed to scoring.confidence_band().
CONF_HIGH_SIM = 0.75
CONF_HIGH_MARGIN = 0.15
CONF_LOW_SIM = 0.45
# Grounding floor: if the best match's effective similarity is below this, the
# query is treated as OUT-OF-DOMAIN — band forced to 'low' and grounded=False,
# so the phraser refuses instead of inventing an answer. Measured separation on
# this corpus: real queries score >=0.64, nonsense <=0.49 (eval_rag surfaces it).
# Code queries clear it via BM25 (eff_sim = max(sim, bm25)).
#
# Raised 0.55 -> 0.60 on 2026-09-05 (Phase 3 Task 4). Non-automotive and nonsense
# queries were already refused 100% of the time; the gap was automotive questions
# about components genuinely absent from this corpus (diesel glow plugs, AdBlue),
# which scored 0.623 mean similarity against 0.676 for real queries — close enough
# that only 8.3% were refused. Measured trade at each threshold:
#
#     floor   absent caught   FA false-refusal   EN false-refusal
#     0.55           8.3%               0.0%               1.2%
#     0.60          33.3%               1.2%               1.2%
#     0.62          50.0%               6.2%               5.0%
#     0.64          75.0%              15.0%               6.2%
#
# 0.60 quadruples boundary refusal for ~1% false refusal; past it the cost rises
# far faster than the benefit. Note the absent set is only n=12, so "33.3%" is
# 4 queries and its confidence interval is wide — the gold set needs expanding
# before pushing this further.
#
# What was tried and rejected: checking whether the query's component vocabulary
# occurs in the index at all. Absent components are described with words that are
# all present ("diesel", "injector", "plug"), so corpus-vocabulary coverage scored
# 1.000 for absent and in-corpus queries alike — no separation whatsoever.
GROUND_SIM_FLOOR = float(os.environ.get('RAG_GROUND_SIM_FLOOR', '0.60'))

# ---------------------------------------------------------------------------
# Human-in-the-loop closed loop (all signals live in the feedback.db sidecar)
# ---------------------------------------------------------------------------
FEEDBACK_BOOST = os.environ.get('RAG_FEEDBACK_BOOST', '1') != '0'  # apply ratings to ranking
FB_MIN_COUNT = 3            # min total signals on a blob before it can move ranking
FB_CAP_LO = 0.85           # hardest down-rank a blob's feedback can cause
FB_CAP_HI = 1.20           # hardest up-rank
FB_HALF_LIFE_DAYS = 45.0   # exponential time-decay half-life for old feedback
FB_CACHE_TTL = float(os.environ.get('RAG_FB_CACHE_TTL', '300'))   # boost-map refresh (s)
PIN_SIM = 0.86             # cosine floor for an expert "pinned answer" to fire

# ---------------------------------------------------------------------------
# Semantic answer cache (paraphrase-tolerant; rides on the already-embedded qvec)
# ---------------------------------------------------------------------------
SEM_CACHE_ENABLED = os.environ.get('RAG_SEM_CACHE', '1') != '0'
# cosine >= this (same scope) serves a cached answer. Kept HIGH on purpose: on
# bge-m3, distinct-but-close intents collide dangerously — e.g. «تعویض روغن ترمز»
# (brake fluid) vs «تعویض روغن موتور» (engine oil) cosine ≈ 0.81, which is ABOVE
# some genuine paraphrases. Serving the wrong cached answer is unacceptable for a
# repair assistant, so this cache only catches near-duplicate phrasings (typos,
# punctuation, inflection: 0.96–0.98) — a latency win, never a semantic merge.
SEM_CACHE_SIM = float(os.environ.get('RAG_SEM_CACHE_SIM', '0.95'))
SEM_CACHE_MAX = 256         # recent (qvec, scope, result) entries kept

# ---------------------------------------------------------------------------
# Diagnostic rule engine (per-car DTC / symptom layer)
# ---------------------------------------------------------------------------
# A "DTC code" node title looks like  'DTC P0301: Cylinder 1 Misfire [11/2022 - ]'
# or 'DTC B27C0-57: ... '. We capture the code and the human-readable name; the
# trailing model-year window is stripped (reuses _DATE_WIN_RE-style handling).
import re as _re
# DTC codes are 1 letter + 4 alphanumerics (P0301, B27C0, U0129, C1A34), with an
# optional manufacturer sub-code suffix '-NN'. The body is alphanumeric, NOT
# digits-only (B27C0 has a letter in it), so match [0-9A-Za-z].
DTC_TITLE_RE = _re.compile(
    r'^DTC\s+([A-Za-z][0-9A-Za-z]{3,4}(?:-\d{1,3})?)\s*:\s*(.+?)\s*$')
# A bare code as typed by a user / read off a scan tool: P0301, b27c0-57, U0129:87
DTC_CODE_RE = _re.compile(r'\b([A-Za-z][0-9A-Za-z]{3,4}(?:[-:]\d{1,3})?)\b')
# Section roots under which DTC subtrees and Problem Symptoms Tables live.
DIAG_SECTION_ROOTS = ('repair and diagnosis', 'repair and diagnosis (single page)')
# Aspect ordering for a DTC's diagnostic chain (the manufacturer's flow). Lower
# rank = earlier step. Anything unlisted sorts after these by node sort_order.
DTC_ASPECT_ORDER = (
    'description', 'monitor description', 'monitor strategy',
    'typical enabling conditions', 'typical malfunction thresholds',
    'confirmation driving pattern', 'symptom tests', 'circuit tests',
    'procedure', 'inspection procedure', 'wiring diagram',
)
# Symptom-table cell whose text/links point at the suspected area/page.
DIAG_SYMPTOM_TABLE_TITLES = ('problem symptoms table',)

# Retrieval sizes for the (small) per-car diag index.
DIAG_SYMPTOM_K = 12         # candidate symptoms from vector + FTS
DIAG_DTC_K = 12             # candidate DTCs matched directly from the query
DIAG_DIRECT_SIM_FLOOR = 0.60  # min cosine to trust a direct query->DTC-name match
                            # (DTC names are terse; below this the match is noise)
DIAG_FINAL_CANDIDATES = 6   # ranked candidate DTCs returned to the phraser
DIAG_STEPS_MAX = 8          # diagnostic steps surfaced per candidate
# symptom_link weights by provenance (manufacturer link > inheritance proximity).
DIAG_W_TABLE_LINK = 1.0     # the symptom table's own <a> link to a DTC
DIAG_W_INHERITANCE = 0.45   # DTC shares the symptom's subsystem (vertical)
DIAG_W_TECHNICIAN = 1.5     # future: a confirmed technician case (highest)
DIAG_CACHE_TTL = float(os.environ.get('RAG_DIAG_CACHE_TTL', '900'))

# Context-scope ranking boosts (a blob that appears in the page the user is on
# ranks above the same content seen only in an unrelated vehicle).
BOOST_CAR = 1.5
BOOST_MODEL = 1.25
BOOST_BRAND = 1.1

# Generic boilerplate pages (safety notes, tool lists) that should rank below
# real procedures/specs. Applied as a query-time penalty only -- the content is
# still indexed and reachable, just not surfaced first. (Tuneable without a rebuild.)
BOILERPLATE_TITLES = {
    'caution / notice / hint', 'caution', 'notice', 'hint', 'caution/notice/hint',
    'precaution', 'precautions', 'recommended tools', 'sst', 'equipment',
    'lubricant', 'lubricants', 'warning', 'warnings', 'general information',
}
BOILERPLATE_PENALTY = 0.4

# ---------------------------------------------------------------------------
# Serving (keep the site fast; never block page loads)
# ---------------------------------------------------------------------------
# Answers are cached in-process by (normalised query + scope). Repeated/common
# questions return instantly without touching the model or the vector index.
CACHE_TTL = float(os.environ.get('RAG_CACHE_TTL', '900'))      # seconds (15 min)
CACHE_MAX = int(os.environ.get('RAG_CACHE_MAX', '512'))        # max cached answers
# Log every query to a sidecar feedback DB (for analytics + future tuning).
LOG_QUERIES = os.environ.get('RAG_LOG_QUERIES', '1') != '0'
FEEDBACK_DB = RAG_DIR / 'feedback.db'

# Optional cross-encoder reranker: a big precision boost for the top results,
# at the cost of loading a second model. OFF by default (heavier); turn on with
# RAG_RERANK=1 — best on a server. Reranks the top RERANK_CANDIDATES hits.
RERANK = os.environ.get('RAG_RERANK', '0') == '1'
RERANK_MODEL = os.environ.get('RAG_RERANK_MODEL', 'BAAI/bge-reranker-v2-m3')
RERANK_CANDIDATES = 20
