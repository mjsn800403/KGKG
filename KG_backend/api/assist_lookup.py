"""Structured lookups the assistant needs beside manual RAG.

Two question kinds are answered from tables, not prose, so text retrieval
misses them: a part number lives in the parts catalog (a separate warehouse),
and "which special tool for job X" lives on the per-system SST pages, which
rank poorly against a job description. For a pinned car, :func:`lookups`
returns the matching catalog rows and SST tools so the chat layer can put them
in the grounding context.
"""
import re

_ZW = re.compile(r'[‌\u200f\u200e]')
_WORD = re.compile(r'\w+')  # \w covers Persian letters, not ؟ ،

PARTS_Q = re.compile(
    r'شماره\s*(فنی|قطعه|پارت)|پارت\s*نامبر|کد\s*قطعه|part\s*(no|number|#)|\bp/?n\b', re.I)
TOOL_Q = re.compile(r'ابزار|\bSST\b|special\s+(service\s+)?tool', re.I)

# Words that frame the question rather than name the part. Built through
# _norm below, like the query, so 'می‌خواهم' (ZWNJ -> space) still matches.
_STOP_RAW = ('''
شماره فنی قطعه پارت نامبر کد برای این خودرو ماشین چیست چیه چه چی است هست را و در از با
یک کدام کدوم مخصوص ابزار لازم نیاز دارم میخواهم می‌خواهم بده بگو لطفا لطفاً مورد
part number no pn the for of what is a which tool tools special service sst
''')

# Persian job words -> English system words used in SST page paths.
_SYS_HINTS = {
    'ترمز': 'brake', 'لنت': 'brake', 'کالیپر': 'brake', 'دیسک': 'brake',
    'ترمزدستی': 'parking brake', 'موتور': 'engine', 'گیربکس': 'transaxle',
    'تعلیق': 'suspension', 'کمک': 'suspension', 'فرمان': 'steering',
    'کولر': 'air conditioning', 'باتری': 'battery', 'روغن': 'lubrication',
    'شمع': 'ignition', 'اگزوز': 'exhaust', 'سوخت': 'fuel', 'خنک': 'cooling',
    'رادیاتور': 'cooling', 'پلوس': 'drive shaft', 'اکسل': 'axle', 'چرخ': 'axle',
}


def _norm(s):
    s = _ZW.sub(' ', s or '').replace('ي', 'ی').replace('ك', 'ک')
    return s.lower()


_STOP = set(_norm(_STOP_RAW).split())


def _terms(query):
    return [w for w in _WORD.findall(_norm(query)) if w not in _STOP and len(w) > 1]


def _manual_car(car_stem):
    from .models import Car
    return Car.objects.filter(car_name=car_stem).first()


def parts_rows(user, car, query, limit=8):
    """Catalog rows (all configurations of the matching catalogs) whose Persian
    or English name holds every content word of the question."""
    from . import parts as P
    terms = _terms(query)
    if not terms:
        return []
    out, seen = [], set()
    for cat in P._related_catalogs(user, car):
        from .models import Car
        pc = Car.objects.filter(car_name=cat['model'], year=cat['year']).first()
        if pc is None:
            continue
        conn = P.get_parts_db(pc)
        like = f'%{terms[0]}%'
        for r in conn.execute(
                "SELECT pn_display, name_en, name_fa, qty_display, date_range FROM part_rows "
                "WHERE REPLACE(REPLACE(name_fa, 'ك', 'ک'), 'ي', 'ی') LIKE ? "
                "OR LOWER(name_en) LIKE ? LIMIT 400", (like, like)):
            name = _norm(f"{r['name_fa'] or ''} {r['name_en'] or ''}")
            if not all(t in name for t in terms):
                continue
            key = (r['pn_display'], r['date_range'])
            if key in seen:
                continue
            seen.add(key)
            pn = r['pn_display'] or ''
            if re.fullmatch(r'\d{10}', pn):  # Toyota prints 5-5
                pn = f'{pn[:5]}-{pn[5:]}'
            out.append({'pn': pn, 'name_en': r['name_en'], 'name_fa': r['name_fa'],
                        'qty': r['qty_display'], 'date_range': r['date_range'],
                        'catalog': cat['model']})
            if len(out) >= limit:
                return out
    return out


def sst_tools(car, query, hits, limit=12):
    """SST tools of the systems the question is about: systems named by the
    top manual hits, plus systems implied by Persian job words."""
    from . import sst
    from .access import car_db_ready
    from .views import get_car_db
    if not car_db_ready(car):
        return []
    wanted = set()
    for h in (hits or [])[:5]:
        for seg in (h.get('title_path') or '').split(' › ')[1:]:
            seg = seg.replace('⁄', '/').strip().lower()
            if seg and seg != 'repair and diagnosis':
                wanted.add(seg)
    qn = _norm(query)
    hints = {v for k, v in _SYS_HINTS.items() if k in qn}
    tools = sst.collect_tools(get_car_db(car.db_address))
    scored = []
    for t in tools:
        labels = [u.lower() for u in t['used_in']]
        system_hit = any(l.split(' › ')[-1] in wanted for l in labels)
        # Tool names count too: shared tools sit under generic systems
        # ("Disc Brake Piston Spreader" is filed under General › Maintenance).
        hay = labels + [(t['name'] or '').lower()]
        # Whole words only: 'axle' must not match 'Transaxle'.
        hint_hit = any(re.search(rf'\b{re.escape(h)}\b', l) for h in hints for l in hay)
        if system_hit or hint_hit:
            scored.append((0 if system_hit else 1, t))
    scored.sort(key=lambda x: x[0])
    return [{'number': t['number'], 'name': t['name'], 'kit_of': t['kit_of'],
             'used_in': t['used_in'][:3]} for _, t in scored[:limit]]


def lookups(user, car_stem, query, hits):
    """{'parts': [...], 'sst_tools': [...]} for a pinned car; empty lists when
    the question is not of that kind. Never raises."""
    out = {'parts': [], 'sst_tools': []}
    if not car_stem:
        return out
    try:
        car = _manual_car(car_stem)
        if car is None:
            return out
        if PARTS_Q.search(query or ''):
            out['parts'] = parts_rows(user, car, query)
        if TOOL_Q.search(query or ''):
            out['sst_tools'] = sst_tools(car, query, hits)
    except Exception as e:  # a lookup must never break the answer
        out['error'] = str(e)[:200]
    return out
