"""Manage the bilingual terminology store (terms.db) and its runtime artifacts.

    python manage.py build_terms --import-legacy   # ingest Book1.csv + translation.sql (idempotent)
    python manage.py build_terms --export           # regenerate Book1.csv + terms_en_fa.json
    python manage.py build_terms --report           # vocabulary/coverage/cost report (read-only)
    python manage.py build_terms --mine --top 2000  # queue most-frequent untranslated EN terms
    python manage.py build_terms --fa-gaps          # Persian queries the glossary fails to expand
    python manage.py build_terms --import-review reviewed.csv   # ingest human-reviewed pairs

Never touches the car DBs, db.sqlite3 or index.rag.db (index is opened
read-only for mining). All writes go to Database_warehouse/_rag/terms.db and
the two generated artifacts (Book1.csv, terms_en_fa.json).
"""
import csv
import math
import re
import sqlite3
from collections import Counter
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from api.rag import config, glossary, terms

# Candidate filtering for --mine / --report.
_DATE_WIN = re.compile(r'\s*\[[^\]]*\]\s*$')
_DTC_CODE = re.compile(r'^[A-Za-z][0-9A-Za-z]{3,4}(?:[-:]\d{1,3})?$')
_HAS_ALPHA3 = re.compile(r'[A-Za-z].*[A-Za-z].*[A-Za-z]')
_STOP_ONLY = {
    'and', 'or', 'the', 'for', 'with', 'from', 'of', 'to', 'in', 'on', 'at',
    'by', 'a', 'an', 'other', 'others', 'etc', 'page', 'section', 'general',
}


def _clean_candidate(s):
    """Normalise a raw title/segment into a translatable EN term (or None)."""
    if not s:
        return None
    s = _DATE_WIN.sub('', str(s)).strip()
    m = config.DTC_TITLE_RE.match(s)
    if m:                      # 'DTC P0301: Cylinder 1 Misfire' -> the name part
        s = m.group(2).strip()
    if not (3 <= len(s) <= 80):
        return None
    if glossary.has_persian(s):
        return None
    if not _HAS_ALPHA3.search(s):
        return None
    if _DTC_CODE.match(s):
        return None
    toks = [t for t in terms.norm_en(s).split() if t]
    if not toks or all(t in _STOP_ONLY for t in toks):
        return None
    return s


def _iter_index_candidates(index_db):
    """Yield (term, weight) pairs from the read-only RAG index: page titles,
    readable component names, and breadcrumb segments (car root excluded)."""
    con = sqlite3.connect(f'file:{index_db}?mode=ro', uri=True)
    try:
        for title, n_occ in con.execute(
                'SELECT title, n_occ FROM blobs'):
            yield title, max(1, n_occ or 1)
        for comp, n_occ in con.execute(
                "SELECT comp_readable, n_occ FROM blobs WHERE comp_readable<>''"):
            yield comp, max(1, n_occ or 1)
        for (tp,) in con.execute('SELECT title_path FROM occurrences'):
            if not tp:
                continue
            segs = tp.split(' › ')
            for seg in segs[1:]:           # segment 0 is the vehicle root
                yield seg, 1
    finally:
        con.close()


def _iter_diag_candidates():
    """Yield (term, weight) pairs from every car's diag sidecar (read-only)."""
    if not config.DIAG_DIR.exists():
        return
    for db in sorted(config.DIAG_DIR.glob('*.diag.db')):
        con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
        try:
            for name, in con.execute('SELECT DISTINCT name FROM dtc'):
                yield name, 2
            for col in ('system', 'subsystem', 'component'):
                try:
                    for v, in con.execute(
                            f"SELECT DISTINCT {col} FROM dtc WHERE {col}<>''"):
                        yield v, 2
                except sqlite3.OperationalError:
                    pass
            try:
                for v, in con.execute('SELECT DISTINCT suspected FROM symptom '
                                      "WHERE suspected<>''"):
                    yield v, 2
            except sqlite3.OperationalError:
                pass
        except sqlite3.OperationalError:
            pass
        finally:
            con.close()


def _known_en_norms(con):
    return {r[0] for r in con.execute('SELECT DISTINCT en_norm FROM terms')}


def _collect_candidates(con, log=lambda s: None):
    """Frequency-weighted untranslated EN vocabulary across index + diag."""
    known = _known_en_norms(con)
    freq = Counter()
    display = {}
    n_raw = 0
    for raw, w in _iter_index_candidates(config.INDEX_DB):
        n_raw += 1
        c = _clean_candidate(raw)
        if not c:
            continue
        key = terms.norm_en(c)
        if not key or key in known:
            continue
        freq[key] += w
        # prefer the most title-cased/compact display variant seen
        if key not in display or (c.istitle() and not display[key].istitle()) \
                or len(c) < len(display[key]):
            display[key] = c
    log(f'  index scan: {n_raw:,} raw values')
    for raw, w in _iter_diag_candidates():
        c = _clean_candidate(raw)
        if not c:
            continue
        key = terms.norm_en(c)
        if not key or key in known:
            continue
        freq[key] += w
        if key not in display:
            display[key] = c
    return freq, display


def _cost_estimate(n, batch=25):
    """Metis message estimate: 2 samples + ~20% third-sample + back-translation."""
    if n <= 0:
        return 0
    return math.ceil(n / batch) * 2 + math.ceil(0.2 * n / batch) \
        + math.ceil(0.9 * n / batch)


class Command(BaseCommand):
    help = 'Build/inspect the bilingual terminology store and its artifacts.'

    def add_arguments(self, parser):
        parser.add_argument('--import-legacy', action='store_true',
                            help='Ingest Book1.csv + translation.sql into terms.db (idempotent).')
        parser.add_argument('--export', action='store_true',
                            help='Regenerate Book1.csv and terms_en_fa.json from terms.db.')
        parser.add_argument('--report', action='store_true',
                            help='Vocabulary / coverage / cost report (read-only, no Metis).')
        parser.add_argument('--mine', action='store_true',
                            help='Queue the top untranslated EN terms into gen_queue.')
        parser.add_argument('--top', type=int, default=2000,
                            help='--mine: how many top-frequency terms to queue.')
        parser.add_argument('--fa-gaps', action='store_true',
                            help='Report Persian user queries the glossary fails to expand.')
        parser.add_argument('--import-review', metavar='FILE',
                            help='Ingest a human-reviewed CSV (en,fa[,domain]) as source=reviewed.')
        parser.add_argument('--translation-sql', default=None,
                            help='Path to legacy translation.sql (default: <project root>/translation.sql).')
        parser.add_argument('--force', action='store_true',
                            help='Allow --import-legacy on a non-empty store (it is a one-time '
                                 'bootstrap: after the first --export, Book1.csv is GENERATED '
                                 'and re-importing it would relabel generated rows as curated).')

    def handle(self, *args, **opts):
        actions = [k for k in ('import_legacy', 'export', 'report', 'mine',
                               'fa_gaps') if opts.get(k)]
        if opts.get('import_review'):
            actions.append('import_review')
        if not actions:
            raise CommandError('Pick an action: --import-legacy / --export / --report / '
                               '--mine / --fa-gaps / --import-review FILE')
        con = terms.connect()
        try:
            if opts['import_legacy']:
                self._import_legacy(con, opts)
            if opts.get('import_review'):
                self._import_review(con, opts['import_review'])
            if opts['export']:
                self._export(con)
            if opts['mine']:
                self._mine(con, opts['top'])
            if opts['report']:
                self._report(con)
            if opts['fa_gaps']:
                self._fa_gaps(con)
        finally:
            con.close()

    # ---- actions ----------------------------------------------------------

    def _import_legacy(self, con, opts):
        self.stdout.write(self.style.MIGRATE_HEADING('=== import legacy pairs ==='))
        existing = con.execute('SELECT COUNT(*) FROM terms').fetchone()[0]
        if existing and not opts.get('force'):
            raise CommandError(
                f'terms.db already holds {existing} pairs — --import-legacy is a one-time '
                'bootstrap (Book1.csv is generated after the first --export). '
                'Pass --force if you really mean to re-ingest.')
        csv_path = config.PARTS_CSV
        if csv_path.exists():
            s = terms.import_book1_csv(con, csv_path, source='curated')
            self.stdout.write(f'  Book1.csv ({csv_path}): {s}')
        else:
            self.stdout.write(self.style.WARNING(f'  Book1.csv not found at {csv_path}'))
        sql_path = Path(opts['translation_sql']) if opts['translation_sql'] \
            else config.BASE_DIR.parent / 'translation.sql'
        if sql_path.exists():
            s = terms.import_translation_sql(con, sql_path, source='imported')
            self.stdout.write(f'  translation.sql ({sql_path}): {s}')
        else:
            self.stdout.write(self.style.WARNING(f'  translation.sql not found at {sql_path}'))
        s = terms.seed_service_pairs(con)
        self.stdout.write(f'  curated service vocabulary: {s}')
        n = con.execute('SELECT COUNT(*) FROM terms').fetchone()[0]
        self.stdout.write(self.style.SUCCESS(f'  terms.db now holds {n} pairs'))

    def _import_review(self, con, path):
        self.stdout.write(self.style.MIGRATE_HEADING(f'=== import reviewed pairs: {path} ==='))
        p = Path(path)
        if not p.exists():
            raise CommandError(f'{p} not found')
        n = 0
        with open(p, encoding='utf-8-sig', newline='') as f:
            for row in csv.reader(f):
                if len(row) < 2 or terms._is_header_artifact(row[0], row[1]):
                    continue
                domain = row[2].strip() if len(row) > 2 and row[2].strip() else 'part'
                r = terms.upsert_term(con, row[0], row[1], domain=domain,
                                      source='reviewed', confidence=1.0)
                if r in ('inserted', 'updated'):
                    n += 1
                    con.execute(
                        "UPDATE gen_queue SET state='accepted', updated_at=datetime('now')"
                        ' WHERE en_norm=?', (terms.norm_en(row[0]),))
        con.commit()
        self.stdout.write(self.style.SUCCESS(f'  {n} reviewed pairs ingested '
                                             f'(run --export to publish)'))

    def _export(self, con):
        self.stdout.write(self.style.MIGRATE_HEADING('=== export artifacts ==='))
        n_csv = terms.export_book1(con)
        self.stdout.write(f'  Book1.csv  <- {n_csv} query pairs  ({config.PARTS_CSV})')
        n_json = terms.export_display_json(con)
        self.stdout.write(f'  terms_en_fa.json <- {n_json} display entries  ({config.TERMS_JSON})')
        self.stdout.write(self.style.SUCCESS('  both artifacts hot-reload; no restart needed'))

    def _mine(self, con, top):
        self.stdout.write(self.style.MIGRATE_HEADING('=== mine untranslated vocabulary ==='))
        if not config.INDEX_DB.exists():
            raise CommandError('index.rag.db not found — build the RAG index first')
        freq, display = _collect_candidates(con, log=self.stdout.write)
        queued = 0
        for key, w in freq.most_common(top):
            en = display[key]
            cur = con.execute('SELECT id FROM gen_queue WHERE en_norm=?', (key,)).fetchone()
            if cur:
                con.execute('UPDATE gen_queue SET freq=? WHERE en_norm=?', (w, key))
                continue
            con.execute(
                'INSERT OR IGNORE INTO gen_queue(en, en_norm, freq, domain, updated_at)'
                " VALUES(?,?,?,?,datetime('now'))", (en, key, w, 'mined'))
            queued += 1
        con.commit()
        states = dict(con.execute(
            'SELECT state, COUNT(*) FROM gen_queue GROUP BY state').fetchall())
        self.stdout.write(self.style.SUCCESS(
            f'  {queued} new terms queued (gen_queue states: {states})'))

    def _report(self, con):
        self.stdout.write(self.style.MIGRATE_HEADING('=== terminology coverage report ==='))
        lines = []

        def out(s):
            self.stdout.write(s)
            lines.append(s)

        n_terms = con.execute('SELECT COUNT(*) FROM terms').fetchone()[0]
        by_src = dict(con.execute(
            'SELECT source, COUNT(*) FROM terms GROUP BY source').fetchall())
        by_status = dict(con.execute(
            'SELECT status, COUNT(*) FROM terms GROUP BY status').fetchall())
        out(f'terms.db: {n_terms} pairs  by source={by_src}  by status={by_status}')

        if config.INDEX_DB.exists():
            freq, _ = _collect_candidates(con, log=out)
            n_unique = len(freq)
            total_w = sum(freq.values())
            out(f'untranslated EN vocabulary: {n_unique:,} unique terms '
                f'(weighted occurrences: {total_w:,})')
            for n in (300, 1000, 2000, 5000, min(n_unique, 20000)):
                if n <= 0:
                    continue
                cover = sum(w for _, w in freq.most_common(n)) / max(1, total_w)
                out(f'  top {n:>6,}: covers {cover:5.1%} of weighted occurrences, '
                    f'~{_cost_estimate(n):,} Metis messages')
        else:
            out('index.rag.db missing — skipped vocabulary scan')

        states = dict(con.execute(
            'SELECT state, COUNT(*) FROM gen_queue GROUP BY state').fetchall())
        out(f'gen_queue: {states or "empty"}')
        rp = config.RAG_DIR / 'terms_report.txt'
        rp.write_text('\n'.join(lines), encoding='utf-8')
        out(f'report saved -> {rp}')

    def _fa_gaps(self, con):
        self.stdout.write(self.style.MIGRATE_HEADING('=== Persian query coverage gaps ==='))
        fb = config.FEEDBACK_DB
        if not fb.exists():
            raise CommandError('feedback.db not found — no logged queries yet')
        src = sqlite3.connect(f'file:{fb}?mode=ro', uri=True)
        try:
            rows = src.execute(
                'SELECT query, COUNT(*) n, MAX(n_hits) FROM queries '
                'GROUP BY query ORDER BY n DESC').fetchall()
        finally:
            src.close()
        gaps = []
        for q, n, n_hits in rows:
            if not q or ' — ' in q:          # skip contextualised follow-up joins
                continue
            if not glossary.has_persian(q):
                continue
            _, matched = glossary.expand(q)
            if len(matched) < 2:
                gaps.append((q, n, n_hits or 0, len(matched)))
        out_path = config.RAG_DIR / 'fa_gaps_report.csv'
        with open(out_path, 'w', encoding='utf-8-sig', newline='') as f:
            w = csv.writer(f)
            w.writerow(['query', 'times_asked', 'max_hits', 'glossary_terms_matched'])
            w.writerows(gaps)
        self.stdout.write(self.style.SUCCESS(
            f'  {len(gaps)} under-expanded Persian queries -> {out_path}'))
