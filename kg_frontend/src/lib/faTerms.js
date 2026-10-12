// English -> Persian terminology for the chat surface (server-side only).
//
// The dictionary is GENERATED from the backend terminology store
// (manage.py build_terms --export -> Database_warehouse/_rag/terms_en_fa.json)
// and hot-reloaded here on mtime change (checked at most once a minute), so new
// translations go live with no rebuild and no restart — the same contract the
// backend glossary has with Book1.csv. If the artifact is missing or broken we
// fall back to the small built-in dictionary this module replaced, preserving
// the pre-terminology behaviour.
//
// Matching: whole-token, longest-phrase-first — same semantics as the regex
// loop it replaces, but backed by a first-token index so thousands of entries
// stay O(tokens) per title instead of O(entries).
import fs from 'node:fs';

const RELOAD_CHECK_MS = 60_000;

// Mirror of the backend glossary._norm_fa (Arabic->Persian unification, ZWNJ/
// tatweel/diacritics stripped, whitespace collapsed) so Persian-term lookups
// agree with the store's fa_norm forms.
const FA_CHAR_MAP = {
  'ي': 'ی', 'ك': 'ک', 'ى': 'ی', 'ئ': 'ی',
  'ۀ': 'ه', 'ة': 'ه', 'أ': 'ا', 'إ': 'ا',
  'آ': 'ا', 'ٱ': 'ا', 'ؤ': 'و',
};
export function normFa(s) {
  if (!s) return '';
  let out = String(s)
    .replace(/[يكىئۀةأإآٱؤ]/g,
      (c) => FA_CHAR_MAP[c] || c)
    .replace(/[‌‎‏ـ]/g, ' ')
    .replace(/[ً-ْ]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase();
  return out;
}

// The dictionary this module replaced (kept verbatim as the degraded-mode
// fallback). Longest phrases first so they win.
const FALLBACK_PAIRS = [
  ['remove and replace', 'باز و بست'], ['removal and installation', 'باز و بست'],
  ['on-vehicle inspection', 'بازرسی روی خودرو'], ['how to proceed', 'روند عیب‌یابی'],
  ['monitor description', 'شرح پایش'], ['circuit description', 'شرح مدار'],
  ['problem symptoms table', 'جدول علائم مشکل'], ['diagnostic trouble code', 'کد خطای عیب‌یابی'],
  ['freeze frame data', 'داده فریز فریم'], ['service data', 'داده سرویس'],
  ['torque specification', 'مشخصات گشتاور'], ['tightening torque', 'گشتاور سفت‌کردن'],
  ['labor time', 'زمان کار'], ['flat rate', 'زمان استاندارد'],
  ['wiring diagram', 'نقشه سیم‌کشی'], ['parts catalog', 'کاتالوگ قطعات'],
  ['special service tool', 'ابزار مخصوص'], ['special tool', 'ابزار مخصوص'],
  ['replacement', 'تعویض'], ['installation', 'نصب'], ['removal', 'باز کردن'],
  ['reassembly', 'مونتاژ مجدد'], ['disassembly', 'دمونتاژ'], ['assembly', 'مونتاژ'],
  ['inspection', 'بازرسی'], ['adjustment', 'تنظیم'], ['diagnosis', 'عیب‌یابی'],
  ['diagnostic', 'عیب‌یابی'], ['procedure', 'رویه'], ['overhaul', 'اورهال'],
  ['specifications', 'مشخصات فنی'], ['specification', 'مشخصه'], ['description', 'شرح'],
  ['precaution', 'احتیاط'], ['operation', 'عملکرد'], ['definition', 'تعریف'],
  ['calibration', 'کالیبراسیون'], ['initialization', 'مقداردهی اولیه'],
  ['registration', 'ثبت'], ['maintenance', 'نگهداری'], ['service', 'سرویس'],
  ['brake fluid', 'روغن ترمز'], ['engine oil', 'روغن موتور'],
  ['transmission fluid', 'روغن گیربکس'], ['power steering', 'فرمان هیدرولیک'],
  ['spark plug', 'شمع'], ['timing belt', 'تسمه تایم'], ['timing chain', 'زنجیر تایم'],
  ['drive belt', 'تسمه دینام'], ['water pump', 'واتر پمپ'], ['fuel pump', 'پمپ بنزین'],
  ['fuel injector', 'انژکتور'], ['cylinder head', 'سرسیلندر'], ['camshaft', 'میل سوپاپ'],
  ['crankshaft', 'میل لنگ'], ['oil filter', 'فیلتر روغن'], ['air filter', 'فیلتر هوا'],
  ['cabin air filter', 'فیلتر کابین'], ['fuel filter', 'فیلتر بنزین'],
  ['shock absorber', 'کمک‌فنر'], ['control arm', 'طبق'], ['ball joint', 'سیبک'],
  ['wheel bearing', 'بلبرینگ چرخ'], ['wheel alignment', 'تنظیم فرمان'],
  ['air conditioning', 'کولر'], ['brake pad', 'لنت ترمز'], ['brake rotor', 'دیسک ترمز'],
  ['brake disc', 'دیسک ترمز'], ['parking brake', 'ترمز دستی'], ['master cylinder', 'سیلندر اصلی'],
  ['throttle body', 'دریچه گاز'], ['catalytic converter', 'کاتالیزور'],
  ['oxygen sensor', 'سنسور اکسیژن'], ['coolant temperature', 'دمای خنک‌کننده'],
  ['high voltage', 'فشار قوی'], ['hybrid battery', 'باتری هیبرید'],
  ['electric motor', 'موتور برقی'], ['inverter', 'اینورتر'], ['alternator', 'دینام'],
  ['starter', 'استارت'], ['radiator', 'رادیاتور'], ['thermostat', 'ترموستات'],
  ['transmission', 'گیربکس'], ['differential', 'دیفرانسیل'], ['driveshaft', 'گاردان'],
  ['suspension', 'سیستم تعلیق'], ['steering', 'فرمان'], ['clutch', 'کلاچ'],
  ['coolant', 'مایع خنک‌کننده'], ['battery', 'باتری'], ['sensor', 'سنسور'],
  ['relay', 'رله'], ['fuse', 'فیوز'], ['airbag', 'ایربگ'], ['engine', 'موتور'],
  ['brake', 'ترمز'], ['circuit', 'مدار'], ['system', 'سیستم'], ['component', 'قطعه'],
  ['module', 'ماژول'], ['valve', 'سوپاپ'], ['pump', 'پمپ'],
  ['filter', 'فیلتر'], ['belt', 'تسمه'], ['wheel', 'چرخ'],
  ['tire', 'لاستیک'], ['lamp', 'چراغ'], ['light', 'چراغ'], ['fluid', 'مایع'],
  ['front', 'جلو'], ['rear', 'عقب'], ['left', 'چپ'], ['right', 'راست'],
  ['upper', 'بالا'], ['lower', 'پایین'], ['torque', 'گشتاور'], ['test', 'تست'],
];

const _state = {
  index: null,        // Map<firstTokenLower, [{words[], fa, en}] longest-first>
  faSet: null,        // Set<normFa Persian term> (for follow-up detection)
  mtimeMs: -1,
  lastCheck: 0,
  fallback: false,
};

function termsPath() {
  return process.env.TERMS_JSON_PATH || '';
}

function phraseWords(en) {
  return String(en).toLowerCase().split(/[^a-z0-9]+/).filter(Boolean);
}

function buildIndex(pairs) {
  const map = new Map();
  for (const pair of pairs) {
    const en = pair && pair[0];
    const fa = pair && pair[1];
    if (!en || !fa) continue;
    const words = phraseWords(en);
    if (!words.length) continue;
    let bucket = map.get(words[0]);
    if (!bucket) map.set(words[0], (bucket = []));
    bucket.push({ words, fa: String(fa), en: String(en) });
  }
  for (const bucket of map.values()) {
    bucket.sort((a, b) => b.words.length - a.words.length);
  }
  return map;
}

function useFallback() {
  _state.index = buildIndex(FALLBACK_PAIRS);
  _state.faSet = new Set(FALLBACK_PAIRS.map(([, fa]) => normFa(fa)));
  _state.fallback = true;
}

function ensureLoaded() {
  const now = Date.now();
  if (_state.index && now - _state.lastCheck < RELOAD_CHECK_MS) return;
  _state.lastCheck = now;
  const p = termsPath();
  if (p) {
    try {
      const st = fs.statSync(p);
      if (st.mtimeMs === _state.mtimeMs && _state.index && !_state.fallback) return;
      const payload = JSON.parse(fs.readFileSync(p, 'utf8'));
      const entries = Array.isArray(payload?.entries) ? payload.entries : [];
      if (entries.length) {
        _state.index = buildIndex(entries);
        _state.faSet = new Set(
          (Array.isArray(payload.fa_terms) ? payload.fa_terms : entries.map((e) => e[1]))
            .map(normFa).filter(Boolean));
        _state.mtimeMs = st.mtimeMs;
        _state.fallback = false;
        return;
      }
    } catch (e) {
      if (!_state.index) console.warn('faTerms: artifact unavailable, using fallback:', e?.message);
    }
  }
  // keep previously-loaded good data; only fall back if we never loaded any
  if (!_state.index) useFallback();
}

// Core scanner: walks the string's word tokens, calls onMatch(candidate,
// spanStart, spanEnd) for every longest whole-token phrase match (greedy,
// left-to-right, non-overlapping).
const WORD_RE = /[A-Za-z0-9]+/g;
// Single space / NBSP / hyphen between phrase words, or the catalogue's
// " & " / " / " joiners ("Brake Shoes & Pads", "Remove & Replace").
const SEP_OK = /^([ \xA0-]|[ ][&/][ ])$/;

function scan(str, onMatch) {
  const tokens = [];
  WORD_RE.lastIndex = 0;
  let m;
  while ((m = WORD_RE.exec(str))) {
    tokens.push({ lo: m[0].toLowerCase(), start: m.index, end: m.index + m[0].length });
  }
  let i = 0;
  while (i < tokens.length) {
    const bucket = _state.index.get(tokens[i].lo);
    let hit = null;
    if (bucket) {
      for (const cand of bucket) {
        const n = cand.words.length;
        if (i + n > tokens.length) continue;
        let ok = true;
        for (let j = 0; j < n; j++) {
          if (tokens[i + j].lo !== cand.words[j]) { ok = false; break; }
          if (j > 0 && !SEP_OK.test(str.slice(tokens[i + j - 1].end, tokens[i + j].start))) {
            ok = false; break;
          }
        }
        if (ok) { hit = cand; break; }
      }
    }
    if (hit) {
      onMatch(hit, tokens[i].start, tokens[i + hit.words.length - 1].end);
      i += hit.words.length;
    } else {
      i += 1;
    }
  }
}

// Persian-only translation of a title/label (unknown tokens left untouched).
export function faTitle(s) {
  if (!s) return s;
  ensureLoaded();
  const str = String(s);
  let out = '';
  let cursor = 0;
  scan(str, (cand, start, end) => {
    out += str.slice(cursor, start) + cand.fa;
    cursor = end;
  });
  out += str.slice(cursor);
  return out;
}

// Bilingual title: «ترجمهٔ فارسی (Original English)». Falls back to the plain
// translation when nothing changed, the source has no Latin text, or the
// original is too long to repeat.
export function faTitleBoth(s) {
  if (!s) return s;
  const str = String(s).trim();
  const t = faTitle(str);
  if (t === str || !/[A-Za-z]/.test(str) || str.length > 80) return t;
  return `${t} (${str})`;
}

// Collect the distinct EN<->FA pairs that actually occur in the given texts —
// feeds the TERMINOLOGY block of the Metis prompt so the phraser uses our
// official equivalents consistently.
export function collectPairs(texts, cap = 20) {
  ensureLoaded();
  const seen = new Map();
  for (const t of texts || []) {
    if (!t) continue;
    scan(String(t), (cand) => {
      if (!seen.has(cand.en) && cand.words.join(' ').length > 2) {
        seen.set(cand.en, cand.fa);
      }
    });
    if (seen.size >= cap * 3) break;   // plenty to choose from
  }
  return [...seen.entries()]
    .sort((a, b) => b[0].length - a[0].length)
    .slice(0, cap);
}

// Set of known Persian terms (normalised) — used by the follow-up detector.
export function faTermsSet() {
  ensureLoaded();
  return _state.faSet || new Set();
}
