"""Persian -> English automotive glossary + query normalisation.

The manuals are in English; user questions are in Persian. A bare multilingual
embedding sometimes drifts (e.g. "روغن ترمز" / brake fluid drifting toward engine
oil). Expanding a Persian query with its English service terms — added to BOTH
the keyword (FTS) side, where Persian can never match English data, and the
embedded query — sharply improves recall and precision.

Two sources, merged at query time:
  1. a small, hand-curated map of common service vocabulary (systems, fluids,
     actions) — high precision, includes short high-value keys;
  2. a large, USER-MAINTAINED parts dictionary loaded from a CSV (config.PARTS_CSV,
     e.g. Book1.csv: "ENGLISH PART NAME, فارسی"). The CSV is reloaded automatically
     whenever the file changes, so the user can keep adding translations with no
     rebuild and no restart.

This is a cheap, build-free accuracy lever: no embedding model is involved.
"""
import re
import csv

from . import config

# Persian term -> canonical English service term(s). Ordered longest-first at use.
GLOSSARY = {
    # fluids / consumables
    'روغن ترمز': 'brake fluid',
    'روغن موتور': 'engine oil',
    'روغن گیربکس': 'transmission fluid',
    'روغن هیدرولیک': 'hydraulic fluid power steering fluid',
    'مایع خنک کننده': 'coolant antifreeze',
    'ضد یخ': 'coolant antifreeze',
    'مایع شیشه شور': 'washer fluid',
    'گریس': 'grease',
    'بنزین': 'fuel gasoline',
    'سوخت': 'fuel',
    'باتری': 'battery',
    'فیلتر روغن': 'oil filter',
    'فیلتر هوا': 'air filter',
    'فیلتر بنزین': 'fuel filter',
    'فیلتر کابین': 'cabin air filter',
    # brakes
    'ترمز': 'brake',
    'لنت': 'brake pad',
    'لنت ترمز': 'brake pad',
    'دیسک ترمز': 'brake rotor disc',
    'دیسک': 'rotor disc',
    'کالیپر': 'caliper',
    'کاسه چرخ': 'brake drum',
    'ترمز دستی': 'parking brake',
    'abs': 'anti-lock brake abs',
    'خلاصی ترمز': 'brake bleed',
    'هواگیری ترمز': 'brake bleed',
    # engine / powertrain
    'موتور': 'engine',
    'شمع': 'spark plug',
    'تسمه تایم': 'timing belt timing chain',
    'تسمه دینام': 'drive belt serpentine belt',
    'تسمه': 'belt',
    'واتر پمپ': 'water pump',
    'رادیاتور': 'radiator',
    'ترموستات': 'thermostat',
    'انژکتور': 'fuel injector',
    'سوپاپ': 'valve',
    'سرسیلندر': 'cylinder head',
    'میل لنگ': 'crankshaft',
    'میل سوپاپ': 'camshaft',
    'دینام': 'alternator',
    'استارت': 'starter motor',
    'استارتر': 'starter motor',
    'گیربکس': 'transmission',
    'کلاچ': 'clutch',
    'دیفرانسیل': 'differential',
    'پلوس': 'axle shaft cv joint',
    'گاردان': 'driveshaft',
    # hybrid / EV
    'هیبرید': 'hybrid',
    'باتری هیبرید': 'hybrid battery high voltage battery',
    'موتور برقی': 'electric motor',
    'اینورتر': 'inverter',
    'شارژر': 'charger charging',
    'برق فشار قوی': 'high voltage',
    # suspension / steering / wheels
    'فرمان': 'steering',
    'جعبه فرمان': 'steering gear rack',
    'کمک فنر': 'shock absorber strut',
    'فنر': 'spring',
    'طبق': 'control arm',
    'سیبک': 'ball joint',
    'بلبرینگ چرخ': 'wheel bearing hub',
    'رینگ': 'wheel rim',
    'لاستیک': 'tire',
    'تایر': 'tire',
    'بالانس': 'wheel balance',
    'تنظیم فرمان': 'wheel alignment',
    'فرمان هیدرولیک': 'power steering',
    # electrical / body / hvac
    'باتری خودرو': 'battery',
    'فیوز': 'fuse',
    'رله': 'relay',
    'سنسور': 'sensor',
    'ایربگ': 'airbag srs',
    'کیسه هوا': 'airbag srs',
    'کولر': 'air conditioning ac',
    'بخاری': 'heater',
    'کمپرسور کولر': 'ac compressor',
    'برف پاک کن': 'wiper',
    'چراغ': 'lamp light',
    'چراغ جلو': 'headlight',
    'چراغ ترمز': 'brake light',
    'دزدگیر': 'anti-theft alarm',
    'سیم کشی': 'wiring harness',
    'ecu': 'engine control module ecu',
    'کامپیوتر خودرو': 'engine control module ecu',
    'دیاگ': 'diagnostic dtc scan',
    'کد خطا': 'diagnostic trouble code dtc',
    # actions
    'تعویض': 'remove and replace replacement',
    'عوض کردن': 'remove and replace',
    'باز کردن': 'removal remove',
    'بستن': 'installation install',
    'نصب': 'installation install',
    'تعمیر': 'repair',
    'تنظیم': 'adjustment adjust',
    'بازرسی': 'inspection inspect',
    'سرویس': 'service maintenance',
    'گشتاور': 'torque specification',
    'مشخصات فنی': 'specifications service data',
    'زمان کار': 'labor time',
    'زمان تعمیر': 'labor time',
    'مدت زمان': 'labor time',
    # symptoms / faults (help a Persian fault description hit the English DTC /
    # symptom-table wording: e.g. "موتور تک می‌زند" -> misfire). Query-time only.
    'تک می زند': 'misfire rough idle',
    'تک زنی': 'misfire rough running',
    'ریپ می زند': 'misfire hesitation',
    'لرزش موتور': 'engine vibration rough idle misfire',
    'لرزش': 'vibration',
    'روشن نمی شود': 'does not start no start cranks',
    'استارت نمی خورد': 'no start does not crank',
    'جرقه نمی زند': 'no spark ignition',
    'خاموش می شود': 'stall stalling engine dies',
    'چراغ چک': 'malfunction indicator lamp mil check engine warning',
    'چراغ چک روشن': 'malfunction indicator lamp mil on illuminated',
    'چراغ هشدار': 'warning indicator light',
    'گرم می کند': 'overheating high temperature',
    'جوش می آورد': 'overheating coolant boiling',
    'دود سیاه': 'black smoke rich mixture',
    'دود آبی': 'blue smoke oil burning',
    'دود سفید': 'white smoke coolant',
    'نشتی روغن': 'oil leak',
    'نشتی': 'leak',
    'مصرف روغن': 'oil consumption',
    'کشش ندارد': 'lack of power poor acceleration hesitation',
    'شتاب ندارد': 'poor acceleration hesitation lack of power',
    'مصرف بنزین بالا': 'poor fuel economy rich',
    'بوی بنزین': 'fuel odor smell',
    'گیربکس قاطی می کند': 'transmission slipping harsh shift',
    'دنده نمی رود': 'will not shift transmission',
    'فرمان سنگین': 'hard steering heavy effort',
    'کولر کار نمی کند': 'air conditioning not cooling',
    'باتری خالی می شود': 'battery discharge parasitic drain',
    'صدای ترمز': 'brake noise squeal',
    'صدای موتور': 'engine noise knocking',
}

_FA_RE = re.compile(r'[؀-ۿ]')

# Persian/Arabic character unification for robust matching (ي/ك Arabic forms,
# alef variants, etc.) + ZWNJ / tatweel / diacritic removal.
_CHAR_MAP = {
    'ي': 'ی', 'ك': 'ک', 'ى': 'ی', 'ئ': 'ی', 'ۀ': 'ه', 'ة': 'ه',
    'أ': 'ا', 'إ': 'ا', 'آ': 'ا', 'ٱ': 'ا', 'ؤ': 'و',
    '‌': ' ', '‏': ' ', '‎': ' ', 'ـ': '',
}
_CHAR_TABLE = str.maketrans(_CHAR_MAP)
_DIACRITICS = re.compile(r'[ً-ْ]')
_WS = re.compile(r'\s+')
_PARENS = re.compile(r'\([^)]*\)')
_NONWORD_EN = re.compile(r'[^a-z0-9]+')


def has_persian(text):
    return bool(_FA_RE.search(text or ''))


def _norm_fa(s):
    """Normalise a Persian string for matching: unify chars, drop diacritics/
    ZWNJ, collapse whitespace, lowercase (latin)."""
    if not s:
        return ''
    s = s.translate(_CHAR_TABLE)
    s = _DIACRITICS.sub('', s)
    s = _WS.sub(' ', s).strip().lower()
    return s


def _norm_en(s):
    """English part name -> space-joined lowercase tokens (len>=2). Catalogue
    punctuation ('SUPPORT, RADIATOR, LOWER') becomes plain search terms."""
    s = _NONWORD_EN.sub(' ', (s or '').lower())
    return ' '.join(t for t in s.split() if len(t) >= 2)


# Pre-normalised curated map: normalised-fa-key -> english terms.
_CURATED_NORM = {_norm_fa(k): v for k, v in GLOSSARY.items()}

# CSV parts dictionary, reloaded on file change. {norm_fa_key: english terms}.
_CSV_CACHE = {'mtime': None, 'data': {}, 'tokens': {}}


def _parse_csv(path):
    data = {}
    with open(path, encoding='utf-8-sig', newline='') as f:
        for row in csv.reader(f):
            if len(row) < 2:
                continue
            en_terms = _norm_en(row[0])
            fa_key = _norm_fa(_PARENS.sub(' ', row[1]))
            if not en_terms or len(fa_key) < config.PARTS_MIN_KEY_CHARS:
                continue
            data.setdefault(fa_key, set()).update(en_terms.split())
    return {k: ' '.join(sorted(v)) for k, v in data.items()}


def _csv_glossary():
    """Return {norm_fa_key: english terms} from the parts CSV, reloading only
    when the file's mtime changes. Tolerates a missing/broken file (returns {})."""
    p = config.PARTS_CSV
    try:
        m = p.stat().st_mtime
    except OSError:
        return {}, {}
    if _CSV_CACHE['mtime'] != m:
        try:
            data = _parse_csv(p)
        except Exception:
            data = {}
        # precompute token sets for multi-word subset matching
        toks = {k: set(t for t in k.split() if len(t) >= 3)
                for k in data if len(k.split()) >= 2}
        _CSV_CACHE.update(mtime=m, data=data, tokens=toks)
    return _CSV_CACHE['data'], _CSV_CACHE['tokens']


def expand(query):
    """Return (english_terms_str, matched_list).

    Matches the (normalised) query against the curated map and the parts CSV:
      * phrase match: a known Persian phrase is a substring of the query;
      * token-subset match (CSV multi-word parts only): all of the part's
        significant tokens appear in the query (handles word order).
    English equivalents are de-duplicated (order-preserving) and capped.
    """
    nq = _norm_fa(query)
    if not nq:
        return '', []
    q_tokens = set(t for t in nq.split() if len(t) >= 3)
    found, seen = [], set()

    def add(terms):
        for w in terms.split():
            if w not in seen:
                seen.add(w)
                found.append(w)

    # curated first (longest normalised key first so phrases beat single words)
    for fa in sorted(_CURATED_NORM, key=len, reverse=True):
        if fa and fa in nq:
            add(_CURATED_NORM[fa])

    csv_data, csv_tokens = _csv_glossary()
    # CSV phrase matches (longest first)
    for fa in sorted(csv_data, key=len, reverse=True):
        if len(found) >= config.GLOSSARY_MAX_TERMS:
            break
        if fa in nq:
            add(csv_data[fa])
    # CSV token-subset matches (all part tokens present in the query)
    if len(found) < config.GLOSSARY_MAX_TERMS:
        for fa, ks in csv_tokens.items():
            if len(found) >= config.GLOSSARY_MAX_TERMS:
                break
            if ks and ks <= q_tokens:
                add(csv_data[fa])

    if len(found) > config.GLOSSARY_MAX_TERMS:
        found = found[:config.GLOSSARY_MAX_TERMS]
    return ' '.join(found), found
