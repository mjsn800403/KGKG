// Deterministic multi-turn contextualizer for the chat route (server-side).
//
// Retrieval is single-message by design (the backend grounds each query
// independently), so a short follow-up like «و گشتاورش چقدره؟» retrieves
// garbage on its own. Instead of a paid LLM rewrite, a cheap heuristic detects
// anaphoric/elliptic follow-ups and augments the retrieval query with the
// previous user message (and the top previous source title) — bounded, flagged
// in the response (`contextualized`), and covered by unit tests.
//
// Pure functions only: the caller passes the known-Persian-terms set
// (faTermsSet() from faTerms.js) so this module stays dependency-free.

// Mirror of faTerms.normFa (kept tiny; both are covered by tests).
const FA_CHAR_MAP = {
  'ي': 'ی', 'ك': 'ک', 'ى': 'ی', 'ئ': 'ی',
  'ۀ': 'ه', 'ة': 'ه', 'أ': 'ا', 'إ': 'ا',
  'آ': 'ا', 'ٱ': 'ا', 'ؤ': 'و',
};
function norm(s) {
  return String(s || '')
    .replace(/[يكىئۀةأإآٱؤ]/g, (c) => FA_CHAR_MAP[c] || c)
    .replace(/[‌‎‏ـ]/g, ' ')
    .replace(/[ً-ْ]/g, '')
    .replace(/[؟?!.،,:;()«»"']/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase();
}

// Persian anaphora / discourse starters that mark a message as referring back.
const STARTERS = new Set([
  'این', 'ان', 'اون', 'همین', 'همون', 'چرا', 'چطور', 'چجوری', 'چگونه',
  'خب', 'پس', 'بعدش', 'بعد', 'یعنی', 'بازم', 'دوباره', 'حالا', 'اونوقت',
  'و', 'ولی', 'اما', 'همچنین', 'چی', 'چیه', 'کدوم', 'کدام', 'کی', 'چقدر',
  'چند', 'ایا', 'آیا', 'مطمینی', 'مطمئنی',
]);

// English function words that may open a short follow-up ("how long?", "why?").
const EN_FOLLOWUP_WORDS = new Set([
  'why', 'how', 'what', 'when', 'where', 'which', 'who', 'this', 'that', 'it',
  'long', 'much', 'many', 'more', 'again', 'and', 'but', 'so', 'then', 'ok',
  'okay', 'yes', 'no', 'sure', 'really', 'does', 'do', 'is', 'are', 'time',
  'need', 'needed', 'next', 'also', 'about',
]);

const DTC_RE = /\b[A-Za-z][0-9A-Za-z]{3,4}(?:[-:]\d{1,3})?\b/;

// True when `message` cannot stand alone: short/anaphoric, carries no known
// domain term, no substantive English word and no DTC code.
export function isFollowUp(message, faSet) {
  const raw = String(message || '').trim();
  if (!raw) return false;
  if (DTC_RE.test(raw)) return false;
  const n = norm(raw);
  const tokens = n.split(' ').filter(Boolean);
  if (!tokens.length || tokens.length >= 8) return false;

  // a substantive (non-function) English word means a self-contained query
  for (const t of tokens) {
    if (/^[a-z0-9]+$/.test(t) && t.length >= 4 && !EN_FOLLOWUP_WORDS.has(t)) {
      return false;
    }
  }

  // A known Persian domain term (unigram or bigram) anchors the message as
  // self-contained — but only from 3 tokens up: a 1-2 word bare term («از
  // ترمز») is almost always the answer to a clarifying question and must be
  // joined with the question that prompted it.
  if (faSet && faSet.size && tokens.length >= 3) {
    for (let i = 0; i < tokens.length; i++) {
      if (faSet.has(tokens[i])) return false;
      if (i + 1 < tokens.length && faSet.has(`${tokens[i]} ${tokens[i + 1]}`)) {
        return false;
      }
    }
  }

  if (STARTERS.has(tokens[0])) return true;
  return tokens.length < 6;
}

// Build the retrieval query: the previous user message rejoined with the
// follow-up (and the top previous source title as an extra anchor), capped.
export function contextualize(message, history, prevSources, faSet) {
  const msg = String(message || '').trim();
  if (!isFollowUp(msg, faSet)) return { query: msg, contextualized: false };

  const lastUser = [...(history || [])].reverse()
    .find((h) => h && h.role === 'user' && h.content && String(h.content).trim());
  if (!lastUser) return { query: msg, contextualized: false };

  let q = `${String(lastUser.content).trim()} — ${msg}`;
  const anchor = (prevSources || []).find((t) => t && String(t).trim());
  if (anchor && q.length + anchor.length < 260) {
    q += ` (${String(anchor).trim()})`;
  }
  if (q.length > 300) q = q.slice(0, 300);
  return { query: q, contextualized: true };
}
