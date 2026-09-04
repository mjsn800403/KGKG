"""Gold-set construction for the KGKG quantitative evaluation suite.

DESIGN RULE — no invented ground truth.
Every relevance label produced here is derived from data that already exists in
the product; nothing is guessed and no language model is asked what the correct
answer is:

  * known-item sets (EN/FA): the query is generated FROM a specific manual page,
    so that page is the correct answer BY CONSTRUCTION. This is the standard
    "known-item retrieval" evaluation used for documentation search.
  * cross-lingual set (FA): identical topics to the EN set, phrased in Persian.
    The corpus is English, so this measures Persian-query/English-document
    retrieval directly. Reported both WITH and WITHOUT the terminology
    expansion layer (see the `--no-glossary` ablation in the runner) so the
    contribution of the dictionary is separated from the multilingual encoder.
  * out-of-scope set: every row is VERIFIED absent from the index before it is
    kept (see `_verify_absent`). A query is only labelled "must refuse" if the
    corpus genuinely cannot answer it.
  * diagnosis sets: labels come from the manuals' OWN tables (`dtc`,
    `symptom`, `symptom_link`) — i.e. manufacturer-authored ground truth.

Relevance is judged at BLOB level (content identity), not app_url, because one
blob is shared by many vehicles. A "topic family" (same system + component +
action, differing only by date-range/variant) counts as relevant, since those
pages are genuinely interchangeable answers to the same question.
"""
from __future__ import annotations

import json
import random
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

from api.rag import config, glossary

# --------------------------------------------------------------- constants
DATE_RE = re.compile(r"\s*\[[^\]]*\]\s*")
PAREN_RE = re.compile(r"\([^)]*\)")
NONWORD_RE = re.compile(r"[^a-z0-9 ]+")
WS_RE = re.compile(r"\s+")
ASCII_WORD_RE = re.compile(r"[A-Za-z]{3,}")

SEP = " › "  # ' › '

# Leaf-kind segments carry no topic information; they are stripped so the
# segment above them is the real "action".
LEAF_KINDS = {
    "procedure", "description", "wiring diagram", "illustration",
    "caution / notice / hint", "components", "fail-safe", "equipment",
}

# 'External Pages' is the cross-variant duplicate bucket, not a real system.
SKIP_SYSTEMS = {"external pages", ""}

# Actions that map to an unambiguous technician question. Anything outside this
# map is skipped rather than guessed at.
ACTIONS_EN = {
    "removal": "how do I remove the {c}",
    "installation": "how to install the {c}",
    "replacement": "steps to replace the {c}",
    "remove & replace": "remove and replace the {c}",
    "inspection": "how do I inspect the {c}",
    "on-vehicle inspection": "on vehicle inspection of the {c}",
    "disassembly": "how to disassemble the {c}",
    "reassembly": "how to reassemble the {c}",
    "adjustment": "how to adjust the {c}",
    "parts location": "where is the {c} located",
    "precaution": "what precautions apply when servicing the {c}",
    "system diagram": "system diagram for the {c}",
    "problem symptoms table": "problem symptoms table for the {c}",
    "terminals of ecu": "ecu terminal values for the {c}",
    "operation check": "how to check operation of the {c}",
    "diagnosis system": "diagnosis system for the {c}",
    "data list / active test": "data list and active test for the {c}",
}

ACTIONS_FA = {
    "removal": "چگونه {c} را باز کنم؟",
    "installation": "نصب {c} چگونه انجام می‌شود؟",
    "replacement": "{c} را چطور تعویض کنم؟",
    "remove & replace": "باز و بست {c} چگونه است؟",
    "inspection": "{c} را چگونه بازرسی کنم؟",
    "on-vehicle inspection": "بازرسی {c} روی خودرو چگونه است؟",
    "disassembly": "چگونه {c} را دمونتاژ کنم؟",
    "reassembly": "مونتاژ مجدد {c} چگونه است؟",
    "adjustment": "تنظیم {c} چگونه انجام می‌شود؟",
    "parts location": "محل قرارگیری {c} کجاست؟",
    "precaution": "هنگام کار روی {c} چه نکات ایمنی را باید رعایت کنم؟",
    "system diagram": "دیاگرام سیستم {c} را نشان بده",
    "problem symptoms table": "جدول علائم خرابی {c} را نشان بده",
    "terminals of ecu": "مقادیر ترمینال‌های کامپیوتر {c} چیست؟",
    "operation check": "بررسی عملکرد {c} چگونه انجام می‌شود؟",
    "diagnosis system": "سیستم عیب‌یابی {c} چگونه کار می‌کند؟",
    "data list / active test": "لیست دیتا و تست فعال {c} را نشان بده",
}


# ---------------------------------------------------------------- helpers
def norm_en(s: str) -> str:
    """Normalise an English component/action string for matching."""
    s = DATE_RE.sub(" ", s or "").lower()
    s = PAREN_RE.sub(" ", s)
    s = NONWORD_RE.sub(" ", s)
    return WS_RE.sub(" ", s).strip()


def segments(comp_readable: str):
    """Breadcrumb -> cleaned segment list (date ranges stripped, empties gone)."""
    return [DATE_RE.sub(" ", s).strip()
            for s in (comp_readable or "").split(SEP) if s and s.strip()]


def topic_of(comp_readable: str):
    """(system, component, action) for a page, or None if it has no clean topic.

    Trailing leaf-kind segments ('Procedure', 'Description', ...) are stripped;
    what remains is <... > Component > Action>.
    """
    segs = segments(comp_readable)
    while segs and segs[-1].lower() in LEAF_KINDS:
        segs.pop()
    if len(segs) < 3:
        return None
    system, action, component = segs[0], segs[-1], segs[-2]
    if system.lower() in SKIP_SYSTEMS:
        return None
    if norm_en(action) not in ACTIONS_EN:
        return None
    comp_n = norm_en(component)
    # A component name must be substantive: not a bare date/number, not huge.
    if not comp_n or len(comp_n) < 3 or len(comp_n.split()) > 8:
        return None
    if comp_n in ACTIONS_EN:          # 'Removal > Removal' style noise
        return None
    return system, component, norm_en(action)


def topic_key(system: str, component: str, action: str) -> str:
    return f"{norm_en(system)}|{norm_en(component)}|{action}"


# ------------------------------------------------------- Persian lexicon
def build_fa_lexicon():
    """en_norm -> Persian term, from the SAME sources the product uses.

    Sources: the curated service glossary in api.rag.glossary (inverted) and the
    active, query-enabled rows of terms.db. Kept separate from the retrieval
    path — this only supplies wording for the Persian questions.
    """
    lex = {}
    # 1) curated service glossary (fa -> en), inverted. Only the WHOLE English
    #    value is indexed: values like 'brake rotor disc' are alternate spellings
    #    of one Persian term, so splitting them would create false pairs.
    for fa, en in getattr(glossary, "GLOSSARY", {}).items():
        k = norm_en(str(en))
        if k and k not in lex:
            lex[k] = fa
    # 2) terms.db parts/service dictionary
    terms_db = Path(config.INDEX_DB).parent / "terms.db"
    if terms_db.exists():
        c = sqlite3.connect(f"file:{terms_db}?mode=ro", uri=True)
        try:
            rows = c.execute(
                "SELECT en_norm, fa FROM terms "
                "WHERE status='active' AND use_query=1 AND fa!=''").fetchall()
        finally:
            c.close()
        for en_norm, fa in rows:
            k = norm_en(en_norm)
            if k and k not in lex:
                lex[k] = fa
    return lex


def translate_component(comp_norm: str, lex: dict):
    """Persian rendering of an English component name, or None.

    Strict: exact normalised match, or match after dropping a trailing
    'assembly'/'sub assy' qualifier. No fuzzy matching — a wrong translation
    would silently corrupt the cross-lingual measurement.
    """
    if comp_norm in lex:
        return lex[comp_norm]
    for tail in (" assembly", " sub assy", " sub assembly", " assy"):
        if comp_norm.endswith(tail):
            base = comp_norm[: -len(tail)].strip()
            if base in lex:
                return lex[base]
    return None


def has_ascii_leak(fa_query: str) -> bool:
    """True if a 'Persian' query still contains English words.

    A Persian query that embeds the English component name would be testing
    keyword matching, not cross-lingual retrieval, so such rows are dropped.
    """
    return bool(ASCII_WORD_RE.search(fa_query or ""))


# ------------------------------------------------------- known-item sets
def indexed_cars(index):
    """Vehicles that were actually embedded/served (the `cars` table is the
    source of truth; `occurrences` also holds parts-only vehicles that have no
    retrievable manual content)."""
    return [r[0] for r in index.execute("SELECT car_stem FROM cars ORDER BY car_stem")]


def _topics_from_blobs(index):
    """topic_key -> {system, component, action, blobs:set(blob_id)}.

    Derived from `blobs` alone (301k rows, one fast scan). Blobs are globally
    content-deduplicated, so a topic's blob set IS its relevant set; which
    vehicles carry it is resolved later, per sampled topic, via idx_occ_blob.
    """
    topics = {}
    for blob_id, comp in index.execute(
            "SELECT blob_id, comp_readable FROM blobs "
            "WHERE comp_readable IS NOT NULL"):
        t = topic_of(comp)
        if not t:
            continue
        system, component, action = t
        key = topic_key(system, component, action)
        rec = topics.get(key)
        if rec is None:
            rec = topics[key] = {"system": system, "component": component,
                                 "action": action, "blobs": set()}
        rec["blobs"].add(blob_id)
    return topics


def _cars_for(index, blob_ids, allowed):
    """Indexed vehicles that carry any of `blob_ids` (uses idx_occ_blob)."""
    qs = ",".join("?" * len(blob_ids))
    rows = index.execute(
        f"SELECT DISTINCT car_stem FROM occurrences WHERE blob_id IN ({qs})",
        list(blob_ids)).fetchall()
    return sorted({r[0] for r in rows} & allowed)


def build_known_item(index, n_en=250, n_fa=250, seed=1373,
                     max_relevant=8, min_relevant=1):
    """Known-item gold rows in English and Persian.

    Sampling is stratified over (system, action) and spread across vehicles so
    that no single system, action or car dominates. Deterministic under `seed`.
    """
    rng = random.Random(seed)
    lex = build_fa_lexicon()
    allowed = set(indexed_cars(index))
    topics = _topics_from_blobs(index)

    # keep topics whose relevant set is small enough to be a real known-item
    # task (a 200-page 'topic' is a boilerplate bucket, not an answer)
    cands = [(k, rec) for k, rec in topics.items()
             if min_relevant <= len(rec["blobs"]) <= max_relevant]
    rng.shuffle(cands)

    buckets = defaultdict(list)
    for k, rec in cands:
        buckets[(norm_en(rec["system"]), rec["action"])].append((k, rec))
    order = sorted(buckets)
    rng.shuffle(order)

    def draw(want, need_fa):
        out = []
        cursor = {k: 0 for k in order}
        car_use = defaultdict(int)
        while len(out) < want:
            exhausted = 0
            for bkey in order:
                if len(out) >= want:
                    break
                lst = buckets[bkey]
                i = cursor[bkey]
                if i >= len(lst):
                    exhausted += 1
                    continue
                cursor[bkey] = i + 1
                key, rec = lst[i]
                comp_n = norm_en(rec["component"])
                if need_fa:
                    fa_comp = translate_component(comp_n, lex)
                    if not fa_comp:
                        continue
                    tmpl = ACTIONS_FA.get(rec["action"])
                    if not tmpl:
                        continue
                    query = tmpl.format(c=fa_comp)
                    if has_ascii_leak(query):
                        continue
                else:
                    tmpl = ACTIONS_EN.get(rec["action"])
                    if not tmpl:
                        continue
                    query = tmpl.format(c=rec["component"].strip())
                cars = _cars_for(index, sorted(rec["blobs"]), allowed)
                if not cars:
                    continue
                # spread the load over vehicles: prefer the least-used car
                car = min(cars, key=lambda c: (car_use[c], c))
                car_use[car] += 1
                out.append({
                    "query": query,
                    "lang": "fa" if need_fa else "en",
                    "car": car,
                    "brand": "Toyota",
                    "expected_blob_ids": sorted(rec["blobs"]),
                    "topic_key": key,
                    "system": rec["system"],
                    "component": rec["component"],
                    "action": rec["action"],
                    "glossary_covered": bool(need_fa),
                    "out_of_scope": False,
                    "provenance": "known_item_by_construction",
                })
            if exhausted >= len(order):
                break
        return out

    en_rows = draw(n_en, need_fa=False)
    fa_rows = draw(n_fa, need_fa=True)
    return en_rows, fa_rows


# ------------------------------------------------------- out-of-scope set
NON_AUTOMOTIVE_FA = [
    "پایتخت ژاپن کجاست؟",
    "دستور پخت قرمه سبزی را بگو",
    "قیمت دلار امروز چند است؟",
    "بهترین فیلم سال ۲۰۲۴ چه بود؟",
    "چگونه زبان فرانسوی یاد بگیرم؟",
    "حافظ در چه قرنی می‌زیست؟",
    "فرمول مساحت دایره چیست؟",
    "آب و هوای فردای تهران چگونه است؟",
    "چطور از افسردگی خارج شوم؟",
    "برنامه پروازهای مشهد را بگو",
    "نتیجه بازی پرسپولیس و استقلال چه شد؟",
    "بهترین رژیم لاغری چیست؟",
    "چگونه در بورس سرمایه‌گذاری کنم؟",
    "شعر «الا یا ایها الساقی» از کیست؟",
    "جمعیت شهر اصفهان چقدر است؟",
    "چطور ویزای کانادا بگیرم؟",
    "معنی کلمه «استیصال» چیست؟",
    "بهترین گوشی موبایل زیر ۲۰ میلیون کدام است؟",
    "فاصله تهران تا شیراز چند کیلومتر است؟",
    "چگونه کد پایتون بنویسم؟",
    "علائم بیماری دیابت چیست؟",
    "قوانین مالیات بر ارزش افزوده را توضیح بده",
    "بهترین زمان کاشت گوجه فرنگی کی است؟",
    "چگونه گیتار یاد بگیرم؟",
    "تاریخ شروع جنگ جهانی دوم چه بود؟",
]

NONSENSE = [
    "asdkjh qwe zxcv", "قققق شششش", "1234567890 ??? ...",
    "lorem ipsum dolor sit amet", "تست تست تست",
    "zzzzzzzz", "!!!!!!!", "الف ب ج د",
    "؟؟؟؟؟؟", "qwertyuiop asdfghjkl", "کککک للل مممم",
    "xyzzy plugh frotz", "۱۲۳۴۵۶", "ااااااااا", "...---...",
]

# Automotive concepts plausibly asked about but NOT present in this modern
# Toyota/Lexus corpus. Each is VERIFIED against the index (see `_verify_absent`)
# before admission — candidates that turn out to be present are rejected and
# reported, so the set can never silently mislabel a covered topic.
ABSENT_CANDIDATES = [
    ("carburetor float bowl", "پیاله شناور کاربوراتور را چگونه تمیز کنم؟"),
    ("distributor cap rotor", "درپوش و چکش برق دلکو را چگونه تعویض کنم؟"),
    ("glow plug preheat", "شمع گرمکن پیش‌گرمایش دیزل را چگونه عوض کنم؟"),
    ("adblue injector", "انژکتور آدبلو را چگونه تعویض کنم؟"),
    ("diesel particulate filter regeneration", "فرآیند احیای فیلتر دوده دیزل چگونه است؟"),
    ("rotary engine apex seal", "آب‌بند نوک روتور موتور وانکل را چگونه تعویض کنم؟"),
    ("magneto ignition", "سیستم جرقه مگنتی را چگونه تنظیم کنم؟"),
    ("kickstart lever", "اهرم هندل موتورسیکلت را چگونه تعمیر کنم؟"),
    ("swirl flap actuator", "عملگر دریچه گردابی منیفولد را چگونه تعویض کنم؟"),
    ("quattro centre differential", "دیفرانسیل مرکزی کواترو را چگونه تعمیر کنم؟"),
    ("tractor power take off shaft", "شفت پی‌تی‌او تراکتور را چگونه تعویض کنم؟"),
    ("hydropneumatic suspension sphere", "کره تعلیق هیدروپنوماتیک را چگونه شارژ کنم؟"),
    ("points condenser ignition", "پلاتین و خازن دلکو را چگونه تنظیم کنم؟"),
    ("choke cable adjustment", "سیم ساسات را چگونه تنظیم کنم؟"),
    ("prechamber diesel injector", "انژکتور پیش‌محفظه دیزل را چگونه تنظیم کنم؟"),
    ("dual mass flywheel clutch", "فلایویل دوجرمی را چگونه تعویض کنم؟"),
    ("supercharger intercooler bypass", "بای‌پس اینترکولر سوپرشارژر را چگونه تعمیر کنم؟"),
    ("gasoline direct injection walnut blasting", "کربن‌زدایی سوپاپ با پوسته گردو چگونه انجام می‌شود؟"),
]


def _verify_absent(index, phrase, max_hits=0):
    """True if `phrase` genuinely has (essentially) no coverage in the index.

    Uses the same FTS table the product searches. A candidate that DOES appear
    is rejected from the out-of-scope set rather than mislabelled.
    """
    toks = [t for t in norm_en(phrase).split() if len(t) >= 3]
    if not toks:
        return False
    match = " AND ".join(toks)
    try:
        n = index.execute(
            "SELECT count(*) FROM blobs_fts WHERE blobs_fts MATCH ?",
            (match,)).fetchone()[0]
    except sqlite3.OperationalError:
        return False
    return n <= max_hits


def build_out_of_scope(index, cars, seed=1373):
    """Queries the system MUST refuse, in three verified categories."""
    rng = random.Random(seed)
    car_list = sorted(cars)
    rows = []

    def add(query, category, note):
        rows.append({
            "query": query, "lang": "fa", "category": category,
            "car": rng.choice(car_list), "brand": "Toyota",
            "expected_blob_ids": [], "out_of_scope": True,
            "provenance": note,
        })

    for q in NON_AUTOMOTIVE_FA:
        add(q, "non_automotive", "off_domain_by_inspection")
    for q in NONSENSE:
        add(q, "nonsense", "no_information_need")
    kept, rejected = [], []
    for phrase, q in ABSENT_CANDIDATES:
        if _verify_absent(index, phrase):
            add(q, "automotive_absent", f"fts_verified_absent:{phrase}")
            kept.append(phrase)
        else:
            rejected.append(phrase)
    return rows, kept, rejected


def _car_mentions(index, car_stem, comp_norm):
    """True if `car_stem` has ANY page whose breadcrumb mentions this component.

    Catches naming variants that an exact component-label comparison misses, so
    a vehicle is only called 'lacking' the part when nothing in its own manual
    refers to it.
    """
    row = index.execute(
        "SELECT 1 FROM occurrences o JOIN blobs b ON b.blob_id = o.blob_id "
        "WHERE o.car_stem = ? AND lower(b.comp_readable) LIKE ? LIMIT 1",
        (car_stem, f"%{comp_norm}%")).fetchone()
    return row is not None


def build_wrong_vehicle(index, n=60, seed=1373):
    """Questions about a component that genuinely does NOT exist in the vehicle
    the user is looking at (e.g. a hybrid battery question on a petrol GR86).

    Membership is derived from `occurrences`: the component is present in some
    indexed vehicles and absent from the scoped one. This is not scored as a
    refusal — the product deliberately allows cross-vehicle corroboration — but
    it measures whether an answer is correctly ATTRIBUTED to the vehicle it
    actually came from, which is the concrete form "unsupported response" takes
    in a multi-vehicle corpus.
    """
    rng = random.Random(seed)
    lex = build_fa_lexicon()
    all_cars = set(indexed_cars(index))
    topics = _topics_from_blobs(index)

    # Presence must be judged at COMPONENT level, over EVERY page of that
    # component (all actions, all date variants). Judging it per (component,
    # action) topic would call a component "absent" merely because one specific
    # procedure page happens to be car-specific — while the component itself is
    # present in the vehicle, which would make the label wrong.
    by_comp = defaultdict(lambda: {"display": None, "blobs": set(), "actions": {}})
    for key, rec in topics.items():
        cn = norm_en(rec["component"])
        e = by_comp[cn]
        e["display"] = e["display"] or rec["component"]
        e["blobs"] |= rec["blobs"]
        e["actions"].setdefault(rec["action"], rec)

    comps = list(by_comp.items())
    rng.shuffle(comps)

    rows = []
    for cn, e in comps:
        if len(rows) >= n:
            break
        fa_comp = translate_component(cn, lex)
        if not fa_comp:
            continue
        action = next((a for a in e["actions"] if a in ACTIONS_FA), None)
        if not action:
            continue
        blobs = sorted(e["blobs"])
        if not (1 <= len(blobs) <= 4000):
            continue
        have = set()
        for i in range(0, len(blobs), 500):      # exact, chunked to keep SQL sane
            have |= set(_cars_for(index, blobs[i:i + 500], all_cars))
        missing = sorted(all_cars - have)
        # distinctive: the component exists in a minority of vehicles, and this
        # vehicle is verifiably not one of them
        if not missing or not have or len(have) > len(all_cars) // 2:
            continue
        # Second, STRICTER gate. Component labels vary between manuals ('Oil Pan'
        # vs 'Oil Pan Sub-Assembly'), so an exact-label miss does not prove the
        # vehicle lacks the part. Require that the candidate vehicle has no page
        # AT ALL whose breadcrumb mentions this component. Vehicles that fail
        # this test are dropped, not relabelled.
        missing = [c for c in missing if not _car_mentions(index, c, cn)]
        if not missing:
            continue
        query = ACTIONS_FA[action].format(c=fa_comp)
        if has_ascii_leak(query):
            continue
        rows.append({
            "query": query, "lang": "fa", "category": "wrong_vehicle",
            "car": rng.choice(missing), "brand": "Toyota",
            "expected_blob_ids": [], "out_of_scope": True,
            "component": e["display"], "action": action,
            "n_pages_for_component": len(blobs),
            "present_in_cars": sorted(have),
            "provenance": "component_verified_absent_from_scoped_vehicle",
        })
    return rows


# --------------------------------------------------------- diagnosis sets
def build_diagnosis(index, cars, n_code=150, n_name=150, n_symptom=200,
                    seed=1373):
    """Fault-diagnosis gold rows from the manuals' OWN diagnostic tables.

    Three conditions, reported separately because they are NOT equally hard:

      dtc_code    query is the bare trouble code            -> exact lookup
      dtc_name    query is the fault NAME, code removed     -> semantic match
      symptom     query is a Problem-Symptoms-Table entry   -> symptom -> cause

    Labels: for `dtc_*` the correct answer is the code the query was built from.
    For `symptom` the correct answers are the codes Toyota's own symptom table
    links to that symptom (`symptom_link.source='symptom_table'`) — authored
    ground truth, not our judgement.

    NOTE (stated in the report): `symptom` queries reuse the indexed symptom
    wording verbatim, so that condition measures symptom->cause LINKAGE, not
    paraphrase robustness. It is an upper bound on that stage.
    """
    rng = random.Random(seed)
    rows = []
    car_list = [c for c in sorted(cars) if config.diag_db_path(c).exists()]
    if not car_list:
        return rows

    per_car = max(1, (n_code + n_name + n_symptom) // max(1, len(car_list)) + 1)
    for car in car_list:
        path = config.diag_db_path(car)
        c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        c.row_factory = sqlite3.Row
        try:
            dtcs = c.execute(
                "SELECT code, name, system, subsystem, component, app_url "
                "FROM dtc WHERE name IS NOT NULL AND name != '' "
                "ORDER BY code").fetchall()
            syms = c.execute(
                "SELECT s.symptom_id, s.text, s.system, s.subsystem "
                "FROM symptom s ORDER BY s.symptom_id").fetchall()
            # AUTHORED ground truth is symptom -> PAGE. The symptom tables in
            # these manuals link a complaint to its troubleshooting page, not
            # to a DTC: `symptom_table`->dtc rows number 3-6 per vehicle while
            # ->page rows number ~740. The abundant symptom->dtc rows carry
            # source='inheritance', which is derived by our own build (same
            # subsystem), so using them as labels would be scoring the system
            # against its own guesswork. They are deliberately not used here.
            links = defaultdict(set)
            for sid, url in c.execute(
                    "SELECT symptom_id, target_app_url FROM symptom_link "
                    "WHERE target_kind='page' AND source='symptom_table' "
                    "AND target_app_url IS NOT NULL AND target_app_url != ''"):
                links[sid].add(url)
        finally:
            c.close()

        dtcs, syms = list(dtcs), list(syms)
        rng.shuffle(dtcs)
        rng.shuffle(syms)

        for d in dtcs[:per_car]:
            rows.append({
                "query": d["code"], "condition": "dtc_code", "lang": "en",
                "car": car, "brand": "Toyota",
                "expected_codes": [d["code"]],
                "system": d["system"], "component": d["component"],
                "provenance": "dtc_table",
            })
            name = re.sub(r"\b[A-Z]\d{3,4}(-\d+)?\b", " ", d["name"] or "").strip()
            if len(name) >= 8:
                rows.append({
                    "query": name, "condition": "dtc_name", "lang": "en",
                    "car": car, "brand": "Toyota",
                    "expected_codes": [d["code"]],
                    "system": d["system"], "component": d["component"],
                    "provenance": "dtc_table_name_code_stripped",
                })
        for s in syms[:per_car]:
            gold = sorted(links.get(s["symptom_id"], ()))
            if not gold:
                continue
            text = (s["text"] or "").strip()
            if len(text) < 8:
                continue
            rows.append({
                "query": text, "condition": "symptom", "lang": "en",
                "car": car, "brand": "Toyota",
                "expected_app_urls": gold,
                "system": s["system"], "component": s["subsystem"],
                "provenance": "symptom_table_page_links",
            })

    rng.shuffle(rows)
    out, want = [], {"dtc_code": n_code, "dtc_name": n_name, "symptom": n_symptom}
    got = defaultdict(int)
    for r in rows:
        if got[r["condition"]] < want[r["condition"]]:
            out.append(r)
            got[r["condition"]] += 1
    return out


# ------------------------------------------------------------------ io
def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path


def read_jsonl(path: Path):
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows
