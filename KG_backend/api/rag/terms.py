"""Bilingual terminology store (English <-> Persian) for display + retrieval.

Why a store and not just Book1.csv: the CSV is a flat pair list with no
provenance, no confidence and no review state, which is exactly what a
machine-assisted translation pipeline needs. The SQLite store (terms.db) is
the single source of truth; the two runtime artifacts are GENERATED from it:

  * Book1.csv           — the fa->en query-expansion dictionary. glossary.py
                          keeps reading it unchanged (mtime hot-reload), so the
                          retrieval path needs no code change and no restart.
  * terms_en_fa.json    — the en->fa display dictionary consumed by the Next
                          chat route (faTerms.js) to render professional
                          Persian titles/labels; also hot-reloaded by mtime.

Direction matters: one English term may have several Persian phrasings — ALL
of them are valuable as fa->en query keys (use_query), while the display side
picks exactly one best Persian per English term (export_display_json).

Normalisation contract: fa_norm reuses glossary._norm_fa so the store can
never disagree with query-time matching; the display form `fa` keeps ZWNJ
(نیم‌فاصله) for professional rendering while fa_norm strips it.
"""
import csv
import json
import os
import re
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import config, glossary

norm_fa = glossary._norm_fa          # matching form (ZWNJ/diacritics stripped)
norm_en = glossary._norm_en          # lowercase tokens, catalogue punctuation dropped

# Display-form cleanup: unify Arabic->Persian characters and drop directional
# marks/tatweel/diacritics like _norm_fa, but PRESERVE ZWNJ — the display form
# is what users read, and «کمک‌فنر» must not degrade to «کمک فنر».
_DISPLAY_MAP = {
    'ي': 'ی', 'ك': 'ک', 'ى': 'ی', 'ۀ': 'ه', 'ة': 'ه',
    'أ': 'ا', 'إ': 'ا', 'ٱ': 'ا', 'ؤ': 'و',
    '‏': '', '‎': '', 'ـ': '',
}
_DISPLAY_TABLE = str.maketrans(_DISPLAY_MAP)
_DIACRITICS = re.compile(r'[ً-ْ]')
_SPACES = re.compile("[ \t\u00a0]+")

# The legacy data carries ~135 rows prefixed with inconsistent "standard part"
# noise from the source catalogue export: 'standard part BOLT, SERRATION',
# 'standard partBOLT(FOR ...)', 'standard part( BOLT, FLANGE)'. Strip the
# prefix (and an outer paren wrapper if that is all that remains around the
# name) so the term keys match how the manuals actually name the part.
_NOISE_PREFIX = re.compile(r'^\s*standard\s*part\s*', re.IGNORECASE)
_OUTER_PARENS = re.compile(r'^\(\s*(.+?)\s*\)$')
# The Persian side of those rows carries the same catalogue noise («قطعه
# استاندارد پیچ فلنجی» = "standard part flange bolt") — strip it for display.
_FA_NOISE_PREFIX = re.compile(r'^\s*قطعه\s+استاندارد\s+')

SOURCE_RANK = {'curated': 3, 'reviewed': 3, 'imported': 2, 'generated': 1}

# Curated service vocabulary (actions / sections / common systems) — the
# dictionary the chat route's inline EN_FA softener used to hold. Seeded into
# the store so the generated display artifact is a SUPERSET of the pre-store
# behaviour (the parts CSV alone has none of these high-frequency title words).
SERVICE_PAIRS = [
    ('remove and replace', 'باز و بست'), ('removal and installation', 'باز و بست'),
    ('on-vehicle inspection', 'بازرسی روی خودرو'), ('how to proceed', 'روند عیب‌یابی'),
    ('monitor description', 'شرح پایش'), ('circuit description', 'شرح مدار'),
    ('problem symptoms table', 'جدول علائم مشکل'), ('diagnostic trouble code', 'کد خطای عیب‌یابی'),
    ('freeze frame data', 'داده فریز فریم'), ('service data', 'داده سرویس'),
    ('torque specification', 'مشخصات گشتاور'), ('tightening torque', 'گشتاور سفت‌کردن'),
    ('labor time', 'زمان کار'), ('flat rate', 'زمان استاندارد'),
    ('wiring diagram', 'نقشه سیم‌کشی'), ('parts catalog', 'کاتالوگ قطعات'),
    ('special service tool', 'ابزار مخصوص'), ('special tool', 'ابزار مخصوص'),
    ('replacement', 'تعویض'), ('installation', 'نصب'), ('removal', 'باز کردن'),
    ('reassembly', 'مونتاژ مجدد'), ('disassembly', 'دمونتاژ'), ('assembly', 'مونتاژ'),
    ('inspection', 'بازرسی'), ('adjustment', 'تنظیم'), ('diagnosis', 'عیب‌یابی'),
    ('diagnostic', 'عیب‌یابی'), ('procedure', 'رویه'), ('overhaul', 'اورهال'),
    ('specifications', 'مشخصات فنی'), ('specification', 'مشخصه'), ('description', 'شرح'),
    ('precaution', 'احتیاط'), ('operation', 'عملکرد'), ('definition', 'تعریف'),
    ('calibration', 'کالیبراسیون'), ('initialization', 'مقداردهی اولیه'),
    ('registration', 'ثبت'), ('maintenance', 'نگهداری'), ('service', 'سرویس'),
    ('brake fluid', 'روغن ترمز'), ('engine oil', 'روغن موتور'),
    ('transmission fluid', 'روغن گیربکس'), ('power steering', 'فرمان هیدرولیک'),
    ('spark plug', 'شمع'), ('timing belt', 'تسمه تایم'), ('timing chain', 'زنجیر تایم'),
    ('drive belt', 'تسمه دینام'), ('water pump', 'واتر پمپ'), ('fuel pump', 'پمپ بنزین'),
    ('fuel injector', 'انژکتور'), ('cylinder head', 'سرسیلندر'), ('camshaft', 'میل سوپاپ'),
    ('crankshaft', 'میل لنگ'), ('oil filter', 'فیلتر روغن'), ('air filter', 'فیلتر هوا'),
    ('cabin air filter', 'فیلتر کابین'), ('fuel filter', 'فیلتر بنزین'),
    ('shock absorber', 'کمک‌فنر'), ('control arm', 'طبق'), ('ball joint', 'سیبک'),
    ('wheel bearing', 'بلبرینگ چرخ'), ('wheel alignment', 'تنظیم فرمان'),
    ('air conditioning', 'کولر'), ('brake pad', 'لنت ترمز'), ('brake rotor', 'دیسک ترمز'),
    ('brake disc', 'دیسک ترمز'), ('parking brake', 'ترمز دستی'), ('master cylinder', 'سیلندر اصلی'),
    ('throttle body', 'دریچه گاز'), ('catalytic converter', 'کاتالیزور'),
    ('oxygen sensor', 'سنسور اکسیژن'), ('coolant temperature', 'دمای خنک‌کننده'),
    ('high voltage', 'فشار قوی'), ('hybrid battery', 'باتری هیبرید'),
    ('electric motor', 'موتور برقی'), ('inverter', 'اینورتر'), ('alternator', 'دینام'),
    ('starter', 'استارت'), ('radiator', 'رادیاتور'), ('thermostat', 'ترموستات'),
    ('transmission', 'گیربکس'), ('differential', 'دیفرانسیل'), ('driveshaft', 'گاردان'),
    ('suspension', 'سیستم تعلیق'), ('steering', 'فرمان'), ('clutch', 'کلاچ'),
    ('coolant', 'مایع خنک‌کننده'), ('battery', 'باتری'), ('sensor', 'سنسور'),
    ('relay', 'رله'), ('fuse', 'فیوز'), ('airbag', 'ایربگ'), ('engine', 'موتور'),
    ('brake', 'ترمز'), ('circuit', 'مدار'), ('system', 'سیستم'), ('component', 'قطعه'),
    ('module', 'ماژول'), ('valve', 'سوپاپ'), ('pump', 'پمپ'),
    ('filter', 'فیلتر'), ('belt', 'تسمه'), ('wheel', 'چرخ'),
    ('tire', 'لاستیک'), ('lamp', 'چراغ'), ('light', 'چراغ'), ('fluid', 'مایع'),
    ('front', 'جلو'), ('rear', 'عقب'), ('left', 'چپ'), ('right', 'راست'),
    ('upper', 'بالا'), ('lower', 'پایین'), ('torque', 'گشتاور'), ('test', 'تست'),
    ('misfire', 'میس‌فایر'), ('detected', 'شناسایی‌شده'),
    ('remove & replace', 'باز و بست'),
    ('cylinder', 'سیلندر'), ('symptom', 'علامت'), ('symptoms', 'علائم'),
    ('cooling fan', 'فن خنک‌کننده'), ('fuel tank', 'باک بنزین'),
    ('shoes', 'کفشک‌ها'), ('pads', 'لنت‌ها'), ('rotor', 'دیسک'),
]


def seed_service_pairs(con):
    """Idempotently seed the curated service vocabulary (query side is served
    by glossary.GLOSSARY already, so these are display-only)."""
    stats = {'inserted': 0, 'updated': 0, 'kept': 0, 'skipped': 0}
    for en, fa in SERVICE_PAIRS:
        r = upsert_term(con, en, fa, domain='service', source='curated',
                        use_query=0, use_display=1)
        stats[r] += 1
    con.commit()
    return stats

_SQL_INSERT_RE = re.compile(
    r"INSERT INTO \"?Book1\"? VALUES\s*\('((?:[^']|'')*)','((?:[^']|'')*)'\)",
    re.IGNORECASE)


def terms_db_path():
    return config.TERMS_DB


def connect(path=None):
    p = Path(path) if path else terms_db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    con.execute('PRAGMA journal_mode=WAL')
    ensure_schema(con)
    return con


def ensure_schema(con):
    con.executescript("""
    CREATE TABLE IF NOT EXISTS terms (
      id          INTEGER PRIMARY KEY,
      en          TEXT NOT NULL,
      fa          TEXT NOT NULL,
      en_norm     TEXT NOT NULL,
      fa_norm     TEXT NOT NULL,
      domain      TEXT DEFAULT '',
      source      TEXT NOT NULL,
      confidence  REAL DEFAULT 1.0,
      status      TEXT DEFAULT 'active',
      use_query   INTEGER DEFAULT 1,
      use_display INTEGER DEFAULT 1,
      notes       TEXT DEFAULT '',
      created_at  TEXT DEFAULT (datetime('now')),
      updated_at  TEXT DEFAULT (datetime('now')),
      UNIQUE(en_norm, fa_norm)
    );
    CREATE INDEX IF NOT EXISTS idx_terms_en_norm ON terms(en_norm);
    CREATE INDEX IF NOT EXISTS idx_terms_fa_norm ON terms(fa_norm);
    CREATE TABLE IF NOT EXISTS gen_queue (
      id INTEGER PRIMARY KEY,
      en TEXT NOT NULL UNIQUE,
      en_norm TEXT NOT NULL,
      freq INTEGER DEFAULT 0,
      domain TEXT DEFAULT '',
      sample_context TEXT DEFAULT '',
      state TEXT DEFAULT 'queued',
      attempts INTEGER DEFAULT 0,
      samples_json TEXT,
      fa_result TEXT,
      agreement REAL,
      backtrans_en TEXT,
      backtrans_sim REAL,
      confidence REAL,
      updated_at TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_genq_state ON gen_queue(state);
    """)
    con.commit()


def clean_fa_display(s):
    """Professional display form: unified Persian characters, single spaces,
    no directional marks / tatweel / diacritics — ZWNJ preserved."""
    if not s:
        return ''
    s = str(s).translate(_DISPLAY_TABLE)
    s = _DIACRITICS.sub('', s)
    s = _SPACES.sub(' ', s)
    # trim spaces and stray ZWNJ at the edges
    return s.strip().strip('‌').strip()


def clean_en_display(s):
    if not s:
        return ''
    return _SPACES.sub(' ', str(s)).strip()


def strip_noise_prefixes(en):
    """Return (clean_en, stripped_flag)."""
    s = clean_en_display(en)
    m = _NOISE_PREFIX.match(s)
    if not m:
        return s, False
    rest = s[m.end():].strip()
    pm = _OUTER_PARENS.match(rest)
    if pm:
        rest = pm.group(1).strip()
    return (rest or s), bool(rest)


def strip_noise_fa(fa):
    """Drop the Persian «قطعه استاندارد» catalogue prefix (kept if that is the
    entire value)."""
    s = clean_fa_display(fa)
    rest = _FA_NOISE_PREFIX.sub('', s).strip()
    return rest or s


def _is_header_artifact(en, fa):
    return norm_en(en) == 'english' or norm_fa(fa) == 'فارسی'


def upsert_term(con, en, fa, *, domain='', source='imported', confidence=1.0,
                status='active', use_query=1, use_display=1, notes=''):
    """Insert or update one pair. On an existing (en_norm, fa_norm) pair a
    lower-ranked source never downgrades a higher-ranked row; confidence only
    ever increases; display forms are refreshed from the higher-ranked source.
    Returns 'inserted' | 'updated' | 'kept' | 'skipped'."""
    en_d = clean_en_display(en)
    fa_d = clean_fa_display(fa)
    en_n, fa_n = norm_en(en_d), norm_fa(fa_d)
    if not en_d or not fa_d or not en_n or not fa_n:
        return 'skipped'
    row = con.execute(
        'SELECT id, source, confidence, status FROM terms WHERE en_norm=? AND fa_norm=?',
        (en_n, fa_n)).fetchone()
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    if row is None:
        con.execute(
            'INSERT INTO terms(en, fa, en_norm, fa_norm, domain, source, confidence,'
            ' status, use_query, use_display, notes, created_at, updated_at)'
            ' VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (en_d, fa_d, en_n, fa_n, domain, source, confidence, status,
             int(use_query), int(use_display), notes, now, now))
        return 'inserted'
    old_rank = SOURCE_RANK.get(row[1], 0)
    new_rank = SOURCE_RANK.get(source, 0)
    if new_rank < old_rank:
        return 'kept'
    con.execute(
        'UPDATE terms SET en=?, fa=?, domain=CASE WHEN ?<>\'\' THEN ? ELSE domain END,'
        ' source=?, confidence=MAX(confidence, ?), status=?, updated_at=? WHERE id=?',
        (en_d, fa_d, domain, domain, source, confidence,
         status if new_rank > old_rank else row[3], now, row[0]))
    return 'updated'


def import_book1_csv(con, path, source='curated'):
    """Ingest the live Book1.csv (EN,FA rows). Returns stats dict."""
    stats = {'rows': 0, 'inserted': 0, 'updated': 0, 'kept': 0, 'skipped': 0,
             'header_dropped': 0, 'prefix_stripped': 0}
    with open(path, encoding='utf-8-sig', newline='') as f:
        for row in csv.reader(f):
            if len(row) < 2:
                continue
            en, fa = row[0], row[1]
            stats['rows'] += 1
            if _is_header_artifact(en, fa):
                stats['header_dropped'] += 1
                continue
            en2, stripped = strip_noise_prefixes(en)
            if stripped:
                stats['prefix_stripped'] += 1
            note = 'prefix:standard-part' if stripped else ''
            r = upsert_term(con, en2, strip_noise_fa(fa), domain='part', source=source,
                            notes=note)
            stats[r] += 1
    con.commit()
    return stats


def import_translation_sql(con, path, source='imported'):
    """Ingest the legacy translation.sql dump (INSERT INTO Book1 VALUES(...))."""
    stats = {'rows': 0, 'inserted': 0, 'updated': 0, 'kept': 0, 'skipped': 0,
             'header_dropped': 0, 'prefix_stripped': 0}
    text = Path(path).read_text(encoding='utf-8')
    for m in _SQL_INSERT_RE.finditer(text):
        en = m.group(1).replace("''", "'")
        fa = m.group(2).replace("''", "'")
        stats['rows'] += 1
        if _is_header_artifact(en, fa):
            stats['header_dropped'] += 1
            continue
        en2, stripped = strip_noise_prefixes(en)
        if stripped:
            stats['prefix_stripped'] += 1
        note = 'prefix:standard-part' if stripped else ''
        r = upsert_term(con, en2, strip_noise_fa(fa), domain='part', source=source, notes=note)
        stats[r] += 1
    con.commit()
    return stats


def _atomic_write(path, data_str):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f'.{path.name}.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as f:
            f.write(data_str)
        os.chmod(tmp, 0o644)   # mkstemp defaults to 0600; artifacts are read by services
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _backup_once_per_day(path):
    p = Path(path)
    if not p.exists():
        return None
    bak = p.with_name(f'{p.name}.bak.{datetime.now().strftime("%Y%m%d")}')
    if not bak.exists():
        bak.write_bytes(p.read_bytes())
    return bak


def export_book1(con, path=None):
    """Regenerate the fa->en query dictionary CSV (glossary.py consumes it).
    Atomic replace so the mtime hot-reload sees exactly one transition."""
    path = Path(path) if path else config.PARTS_CSV
    rows = con.execute(
        "SELECT en, fa FROM terms WHERE status='active' AND use_query=1"
        ' ORDER BY en_norm, fa_norm').fetchall()
    _backup_once_per_day(path)
    import io
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator='\n')
    for en, fa in rows:
        w.writerow([en, fa])
    _atomic_write(path, buf.getvalue())
    return len(rows)


def export_display_json(con, path=None):
    """Regenerate the en->fa display artifact for the chat route. One best
    Persian per English term: highest source rank, then confidence, then the
    shortest display form (labels should stay compact)."""
    path = Path(path) if path else config.TERMS_JSON
    best = {}
    for en, fa, en_n, source, conf in con.execute(
            "SELECT en, fa, en_norm, source, confidence FROM terms"
            " WHERE status='active' AND use_display=1"):
        # Display-quality gates (query side is untouched by these):
        #  * a comma-alternatives translation («میله، شمش، میله گرد») is a
        #    glossary entry, not a label — inline only the first alternative;
        #  * a single-word EN key mapped to a long specific Persian phrase
        #    (FAN -> «پره فن رادیاتور») would MIStranslate longer titles it
        #    appears inside, so it is excluded from display.
        fa_disp = fa.split('،')[0].strip() if '،' in fa else fa
        if not fa_disp:
            continue
        if len(en.split()) == 1 and len(fa_disp.split()) >= 3:
            continue
        key = en_n
        cand = (SOURCE_RANK.get(source, 0), conf, -len(fa_disp), en, fa_disp)
        if key not in best or cand > best[key]:
            best[key] = cand
    entries = sorted([[c[3], c[4]] for c in best.values()],
                     key=lambda e: (-len(e[0]), e[0].lower()))
    fa_terms = sorted({r[0] for r in con.execute(
        "SELECT DISTINCT fa_norm FROM terms WHERE status='active'")})
    payload = {
        'version': 1,
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'count': len(entries),
        'entries': entries,
        'fa_terms': fa_terms,
    }
    _atomic_write(path, json.dumps(payload, ensure_ascii=False))
    return len(entries)
