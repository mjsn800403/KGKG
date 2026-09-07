// Server-side assistant proxy. The intelligence comes from OUR OWN system:
//   * when a car is in context, we first call the deterministic DIAGNOSTIC rule
//     engine (/api/diagnose) — it maps a Persian symptom or a DTC code to ranked
//     candidate faults, ordered diagnostic steps, repair procedure + labor time,
//     and cross-vehicle matches, all computed in the backend;
//   * otherwise (or when the engine finds nothing) we fall back to the general
//     RAG retrieval (/api/assist).
// Metis is used ONLY as a language generator ("phraser") with a strict,
// context-only prompt. All processing/logic stays on our side. The API token
// lives only here (server runtime), never in the browser bundle.

import { faTitle, faTitleBoth, collectPairs, faTermsSet } from '../../../lib/faTerms';
import { contextualize } from '../../../lib/contextualize';

const METIS_BASE = 'https://api.metisai.ir/api/v1/chat';
const API_KEY = process.env.METIS_API_KEY;
const BOT_ID = process.env.METIS_BOT_ID;
const BACKEND_URL = process.env.BACKEND_URL || 'http://127.0.0.1:8000';

async function metis(path, body) {
  const res = await fetch(`${METIS_BASE}/${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Api-Key': API_KEY },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(90000),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Metis ${path} failed: ${res.status} ${text}`);
  }
  return res.json();
}

// Query translation before retrieval, behind a flag (off by default).
//
// The index is English; a Persian question reaches BM25 as ~9 tokens that match
// zero pages, so the keyword half of the hybrid contributes almost nothing.
// Measured on the technician-reviewed set known_item_fa_rev (n=59), translating
// to one English service-manual phrasing first:
//
//     Hit@1   0.068 -> 0.203   (p=0.025)
//     nDCG@5  0.152 -> 0.313   (p=0.003)
//     R@10    0.305 -> 0.458   (p=0.035)
//     p50      906  -> 1055 ms
//
// Multi-query fusion scored higher on Recall@10 (0.627) but LOWER on Hit@1 and
// took 2949 ms, so it is deliberately not wired.
//
// Caveat worth keeping visible: the paraphrases in that measurement were written
// by hand, not returned by Metis, so the live gain may be smaller. Re-run the
// A/B against real Metis output before treating these numbers as shipped.
const MQ_TRANSLATE = process.env.RAG_MQ_TRANSLATE === '1';
const FA_RE = /[\u0600-\u06FF]/;
const _mqCache = new Map();          // process-local, bounded below

const TRANSLATE_PROMPT = [
  'Translate this Persian automotive service question into ONE short English',
  'query using Toyota/Lexus service-manual terminology.',
  'Output ONLY the query: no quotes, no explanation, no punctuation at the end.',
  'Keep any DTC code (like B0050 or P0607) and any engine code exactly as-is.',
  '',
  'Persian question: ',
].join('\n');

async function translateQuery(q) {
  if (!MQ_TRANSLATE || !(API_KEY && BOT_ID) || !q || !FA_RE.test(q)) return null;
  const key = q.trim();
  if (_mqCache.has(key)) return _mqCache.get(key);
  try {
    const session = await metis('session', {
      botId: BOT_ID, user: { id: 'mq-translate', name: '_' },
    });
    const reply = await metis(`session/${session.id}/message`, {
      message: { type: 'USER', content: TRANSLATE_PROMPT + key },
    });
    let out = (reply?.content ?? '').trim().split('\n')[0].replace(/^["'`]|["'`]$/g, '').trim();
    // Refuse anything that came back still Persian, empty, or implausibly long
    // -- a bad translation is worse than no translation.
    if (!out || FA_RE.test(out) || out.length > 200) out = null;
    if (_mqCache.size > 500) _mqCache.clear();
    _mqCache.set(key, out);
    return out;
  } catch (e) {
    console.error('query translation failed (using original Persian):', e);
    return null;
  }
}


async function backend(path, body, token) {
  const res = await fetch(`${BACKEND_URL}${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(60000),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    const err = new Error(detail?.error || `${path} failed: ${res.status}`);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

// GET the backend with the caller's token (used to validate the session + read
// AI eligibility before we spend anything on the paid phraser).
async function backendGet(path, token) {
  const res = await fetch(`${BACKEND_URL}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    signal: AbortSignal.timeout(30000),
  });
  if (!res.ok) {
    const err = new Error(`${path}: ${res.status}`);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

// Read a cookie from the raw header — robust whether the runtime hands us a
// NextRequest or a plain Request.
function readCookie(request, name) {
  const raw = request.headers.get('cookie') || '';
  const m = raw.match(new RegExp('(?:^|;\\s*)' + name + '=([^;]*)'));
  return m ? decodeURIComponent(m[1]) : '';
}

// ---- English -> Persian titles: served by src/lib/faTerms.js -------------
// The full terminology dictionary is generated from the backend store
// (manage.py build_terms --export) and hot-reloaded on change; the lib
// falls back to the previous small built-in dictionary if it is absent.
// Persian labels for a confidence band (diagnostic path; the assist path reuses
// the backend's own label_fa).
function bandLabel(band) {
  return band === 'high' ? 'مطمئن'
    : band === 'low' ? 'نامطمئن — با دفترچه راستی‌آزمایی کن'
    : 'نسبتاً مطمئن';
}

// ---- per-IP rate limit (protect the paid Metis dependency) ----------------
// Metis costs money per message, so cap how often any one client can drive this
// route. In-memory sliding window — right for the single-process Next server;
// tune with CHAT_RL_LIMIT / CHAT_RL_WINDOW (requests / seconds).
const RL_LIMIT = parseInt(process.env.CHAT_RL_LIMIT || '20', 10);
const RL_WINDOW = parseInt(process.env.CHAT_RL_WINDOW || '60', 10) * 1000;
const _RL = new Map();   // ip -> number[] (ms timestamps)

function clientIp(request) {
  // Prefer X-Real-IP (nginx sets it to the true client). Otherwise use the LAST
  // X-Forwarded-For hop, which is the one our proxy appended — earlier entries
  // are client-supplied and spoofable (taking [0] was the bypass bug).
  const xri = request.headers.get('x-real-ip');
  if (xri) return xri.trim();
  const xff = request.headers.get('x-forwarded-for');
  if (xff) return xff.split(',').pop().trim();
  return 'unknown';
}

function rateLimited(ip) {
  if (RL_LIMIT <= 0) return false;
  const now = Date.now();
  const arr = (_RL.get(ip) || []).filter((t) => t > now - RL_WINDOW);
  if (arr.length >= RL_LIMIT) {
    _RL.set(ip, arr);
    return true;
  }
  arr.push(now);
  _RL.set(ip, arr);
  if (_RL.size > 5000) {           // opportunistic cleanup of idle buckets
    for (const [k, v] of _RL) {
      if (!v.some((t) => t > now - RL_WINDOW)) _RL.delete(k);
    }
  }
  return false;
}

// ---- multi-turn plumbing ---------------------------------------------------
// The client sends its recent thread (localStorage) with each request. It is
// UNTRUSTED input: hard-cap counts and lengths before it reaches a prompt.
function sanitizeHistory(history) {
  if (!Array.isArray(history)) return [];
  return history
    .filter((h) => h && typeof h === 'object' &&
      (h.role === 'user' || h.role === 'ai') &&
      typeof h.content === 'string' && h.content.trim())
    .slice(-8)
    .map((h) => ({ role: h.role, content: h.content.slice(0, 600) }));
}

function sanitizePrevSources(prev) {
  if (!Array.isArray(prev)) return [];
  return prev.filter((t) => typeof t === 'string' && t.trim())
    .slice(0, 3).map((t) => t.slice(0, 160));
}

// Condensed prior exchanges for the Metis prompt — reference resolution only;
// the grounding context always belongs to the CURRENT message.
function historyBlock(hist) {
  if (!hist || !hist.length) return '';
  const lines = hist.slice(-6).map((h) =>
    `${h.role === 'user' ? 'کاربر' : 'دستیار'}: ${h.content.slice(0, 300)}`);
  return (
    `گفتگوی پیشین (فقط برای فهم مرجع اشاره‌ها؛ فقط به آخرین پیام کاربر پاسخ بده ` +
    `و منبع‌ها فقط مالِ همین پاسخ هستند):\n${lines.join('\n')}\n\n`
  );
}

// The manual system each hit belongs to — segment 2 of the breadcrumb
// («Car › Repair and Diagnosis › Brakes › …»). Used to spot ambiguous queries.
function systemRoots(rag) {
  const roots = [];
  for (const h of (rag?.hits || []).slice(0, 4)) {
    const segs = (h.title_path || '').split(' › ');
    const root = (segs.length > 2 ? segs[2] : segs[1] || '').trim();
    if (root && !roots.includes(root)) roots.push(root);
  }
  return roots;
}

// One short Persian clarifying question instead of a generic low-confidence
// answer, when retrieval scattered across several unrelated systems.
function buildClarifyPrompt({ message, roots, historyText }) {
  return (
    `سؤال کاربر مبهم است: در دفترچهٔ سرویس به چند سیستم مختلف می‌خورد ` +
    `(${roots.join('، ')}).\n` +
    `فقط یک سؤال کوتاه، دوستانه و فارسی بپرس تا روشن شود منظور کدام سیستم است. ` +
    `پاسخ فنی نده، حدس نزن و هیچ دکمهٔ لینکی نساز.\n\n` +
    (historyText || '') +
    `پیام کاربر: «${message}»\n\nحالا فقط همان یک سؤال روشن‌کننده را بپرس.`
  );
}

function fallbackClarify(roots) {
  return (
    `سؤالت به چند بخش مختلف دفترچه می‌خورد: ${roots.join('، ')}. ` +
    `کدام بخش منظورت است؟ روی یکی از گزینه‌ها بزن یا کمی دقیق‌تر بنویس.`
  );
}

// 2-4 follow-up chips from data we already retrieved. Labels are Persian; the
// underlying queries stay self-contained (mostly English manual titles) so a
// chip click retrieves precisely without needing the conversation context.
function buildSuggestions({ mode, rag, diag, clarifyRoots }) {
  const out = [];
  if (clarifyRoots?.length) {
    clarifyRoots.slice(0, 4).forEach((r) =>
      out.push({ label: faTitle(r), query: `از ${faTitle(r)}` }));
    return out;
  }
  if (mode === 'diagnose' && diag) {
    const c = diag.candidates?.[0];
    (c?.sibling_dtcs || []).slice(0, 2).forEach((code) =>
      out.push({ label: `کد ${code} یعنی چه؟`, query: `${code}` }));
    if (c?.labor_time?.length) {
      out.push({ label: 'زمان استاندارد این تعمیر چقدر است؟',
                 query: `${c.labor_time[0].title} labor time` });
    }
    if (c?.procedure && c?.name) {
      out.push({ label: 'رویهٔ کامل تعمیر را نشان بده',
                 query: `${c.name} repair procedure` });
    }
  } else if (rag?.hits?.length) {
    const top = rag.hits[0];
    (top.related || []).filter((r) => r.relation !== 'labor_time').slice(0, 2)
      .forEach((r) => out.push({ label: `راهنمای «${faTitle(r.title)}»`, query: r.title }));
    const labor = (top.related || []).find((r) => r.relation === 'labor_time');
    if (labor) {
      out.push({ label: 'زمان استاندارد این کار چقدر است؟',
                 query: `${top.title} labor time flat rate` });
    }
    if (top.cross_vehicle?.length) {
      const v = top.cross_vehicle[0];
      out.push({ label: `همین رویه در ${v.model} ${v.variant || ''}`.trim(),
                 query: `${top.title} ${v.model}` });
    }
  }
  const seen = new Set();
  return out.filter((s) => !seen.has(s.label) && seen.add(s.label)).slice(0, 4);
}

// ---- no-LLM fallback (resilience: Metis is the only external dependency) ----
// Vehicle-scoped evidence banner.
//
// Deduplication makes one stored manual page addressable from many vehicles, so
// a high-ranking page can belong to a DIFFERENT vehicle than the one the
// technician has open. For repair data (torque values, procedures) presenting
// that silently is unsafe. The backend's retrieve.assist() reports where the
// evidence actually came from; this renders that verdict.
//
// It is prepended DETERMINISTICALLY to the final reply rather than asked of the
// phraser, because a warning the model may choose to omit is not a safety
// control. It therefore survives an LLM failure and the no-LLM fallback alike.
function scopeBanner(rag) {
  const ev = rag?.evidence;
  if (!ev || ev.scope !== 'cross_vehicle') return '';
  const src = ev.source_car_stem || 'خودروی دیگر';
  const alt = ev.hits_in_vehicle > 0
    ? ` نتایج مربوط به خودروی انتخاب‌شده در فهرست منابع، پایین‌تر آمده است.`
    : '';
  if (ev.title_absent_from_vehicle) {
    return `> ⚠️ **این پاسخ از خودروی دیگری نقل شده است.**
` +
           `> صفحهٔ استنادشده متعلق به **${src}** است و در دفترچهٔ خودروی انتخاب‌شده ` +
           `هیچ صفحه‌ای با همین عنوان وجود ندارد. مقادیر گشتاور و روش‌های تعمیر ` +
           `میان خودروها متفاوت است؛ پیش از اجرا، مرجع خودروی خودتان را بررسی کنید.${alt}

`;
  }
  return `> ℹ️ صفحهٔ استنادشده از **${src}** بازیابی شده است، نه از خودروی انتخاب‌شده. ` +
         `محتوای این صفحه میان چند خودرو مشترک است.${alt}

`;
}

// When Metis is unconfigured/down/over budget we still have the full grounded
// retrieval. Rather than 502, emit a deterministic Persian digest of the sources
// we already retrieved (as BUTTON links, which survive the faithfulness gate).
function fallbackReply({ mode, sources, grounded }) {
  if (!grounded || !sources || !sources.length) {
    return 'دستیار زبانی موقتاً در دسترس نیست و موردی هم در دفترچه‌های ما برای این پرسش پیدا نشد. ' +
      'کمی بعد دوباره تلاش کن.';
  }
  const head = mode === 'diagnose'
    ? 'دستیار زبانی موقتاً در دسترس نیست؛ این خلاصهٔ خودکار از دادهٔ تشخیصی دفترچه است:'
    : 'دستیار زبانی موقتاً در دسترس نیست؛ این منابع مرتبط از دفترچهٔ سرویس است:';
  const seen = new Set();
  const lines = [];
  for (const s of sources) {
    if (!s.url || seen.has(s.url)) continue;
    seen.add(s.url);
    const conf = s.band_label ? ` — اطمینان: ${s.band_label}` : '';
    lines.push(`• ${s.title}${conf}\n[BUTTON](title="${s.title}", href="${s.url}")`);
    if (lines.length >= 6) break;
  }
  return `${head}\n\n${lines.join('\n\n')}\n\n` +
    'ℹ️ این فهرست به‌صورت خودکار و بدون مدل زبانی تهیه شده؛ برای پاسخ کامل کمی بعد دوباره بپرس.';
}

// ---- runtime faithfulness: button-link validation -------------------------
// Metis is a phraser, not a source of truth. It is instructed to emit link
// buttons only with the hrefs we hand it, but an LLM can still hallucinate a
// plausible-looking link. So we compute the exact set of hrefs that actually
// came from our retrieval (the hit, its graph-related/labor pages, and
// cross-vehicle matches) and strip any [BUTTON] whose href isn't in that set.
function normHref(h) {
  return (h || '').trim();
}

function collectAllowedHrefs(rag) {
  const set = new Set();
  (rag?.hits || []).forEach((h) => {
    if (h.app_url) set.add(normHref(h.app_url));
    (h.related || []).forEach((r) => r.app_url && set.add(normHref(r.app_url)));
    // cross_vehicle skipped: those cars may not be in the user's subscription
  });
  return set;
}

function collectAllowedHrefsDiag(d) {
  const set = new Set();
  (d?.candidates || []).forEach((c) => {
    if (c.app_url) set.add(normHref(c.app_url));
    (c.steps || []).forEach((s) => s.app_url && set.add(normHref(s.app_url)));
    if (c.procedure?.app_url) set.add(normHref(c.procedure.app_url));
    (c.labor_time || []).forEach((l) => l.app_url && set.add(normHref(l.app_url)));
    // cross_vehicle skipped: those cars may not be in the user's subscription
  });
  (d?.procedures || []).forEach((p) => p.app_url && set.add(normHref(p.app_url)));
  return set;
}

// Drop any [BUTTON](title="...", href="...") whose href didn't come from us.
// Returns { text, stripped } so the caller can surface how many were removed.
const BUTTON_RE = /\[BUTTON\]\(\s*title="([^"]*)"\s*,\s*href="([^"]*)"\s*\)/g;
function sanitizeButtons(reply, allowed) {
  let stripped = 0;
  const text = (reply || '').replace(BUTTON_RE, (full, _title, href) => {
    if (allowed.has(normHref(href))) return full;
    stripped += 1;
    return '';            // remove the hallucinated link entirely
  });
  return { text: stripped ? text.replace(/[ \t]+\n/g, '\n').trim() : text, stripped };
}

// ---- general RAG path (repair/spec Q&A) -----------------------------------
function buildContext(rag) {
  const sources = [];
  const blocks = [];
  rag.hits.forEach((h, i) => {
    const n = i + 1;
    // Bilingual «فارسی (English)» title for the UI/prompt; keep the English
    // body for grounding and the raw English title for future UI surfaces.
    const titleFa = faTitleBoth(h.title);
    sources.push({ n, title: titleFa, title_en: h.title,
                   path: faTitle(h.title_path), url: h.app_url,
                   model: h.model, variant: h.variant, blob_id: h.blob_id,
                   band: h.confidence_band, band_label: h.confidence_label,
                   matched_via: h.matched_via, similarity: h.similarity });
    let b = `[منبع ${n}] خودرو: ${h.brand} ${h.model}${h.variant ? ' ' + h.variant : ''}\n`;
    b += `عنوان: ${titleFa}\nمسیر: ${faTitle(h.title_path)}\nلینک: ${h.app_url}\n`;
    b += `متن:\n${(h.text || '').slice(0, 1800)}\n`;
    const labor = (h.related || []).filter((r) => r.relation === 'labor_time');
    const other = (h.related || []).filter((r) => r.relation !== 'labor_time');
    if (labor.length) {
      b += `زمان کار مرتبط: ` + labor.map((r) => `${faTitle(r.title)} (${r.app_url})`).join(' ، ') + `\n`;
    }
    if (other.length) {
      b += `صفحات مرتبط: ` + other.map((r) => `${faTitle(r.title)} (${r.app_url})`).join(' ، ') + `\n`;
    }
    if (h.cross_vehicle?.length) {
      b += `همین رویه در خودروهای دیگر: ` +
        h.cross_vehicle.map((c) => `${c.model} ${c.variant} [${c.scope}] (${c.app_url})`).join(' ، ') + `\n`;
    }
    blocks.push(b);
  });
  return { sources, contextText: blocks.join('\n---\n') };
}

// The official-terminology block: the EN<->FA pairs that actually occur in the
// retrieved context, so the phraser translates every recurring technical term
// the same way our UI does (consistency beats ad-hoc synonyms).
function termsBlock(pairs) {
  if (!pairs || !pairs.length) return '';
  return (
    `واژه‌نامهٔ رسمی (این معادل‌ها را همیشه به‌کار ببر و در اولین اشاره نام انگلیسی را داخل پرانتز بیاور):\n` +
    pairs.map(([en, fa]) => `- ${en} = ${fa}`).join('\n') + `\n\n`
  );
}

function buildPrompt({ message, contextText, hasContext, terminology, historyText }) {
  if (!hasContext) {
    return (
      (historyText || '') +
      `سؤال کاربر: «${message}»\n\n` +
      `در دفترچه‌های سرویس ما هیچ مطلب مرتبطی پیدا نشد. ` +
      `صادقانه به کاربر بگو این مورد در داده‌های ما موجود نیست و از خودت اطلاعات فنی نساز.`
    );
  }
  return (
    `تو دستیار تعمیراتی هستی و فقط بر اساس «متن‌های دفترچهٔ سرویس» زیر پاسخ می‌دهی.\n` +
    termsBlock(terminology) +
    `قوانین:\n` +
    `1) فقط از همین متن‌ها استفاده کن؛ اگر چیزی در آن‌ها نبود، بگو در داده‌ها نیست و حدس نزن.\n` +
    `2) پاسخ را کاملاً فارسی، روان، مرحله‌به‌مرحله و کاربردی بنویس. اصطلاحات فنی را به فارسی بنویس؛ ` +
    `اگر معادل فارسی رایج نبود، فقط همان اصطلاح را نگه دار و یک‌بار نام انگلیسی را داخل پرانتز بیاور ` +
    `(مثلاً «سنسور اکسیژن (Oxygen Sensor)»). از کپی مستقیم جمله‌ها و عبارت‌های انگلیسی خودداری کن و ` +
    `متن انگلیسی را به فارسی برگردان. مقادیر عددی گشتاور/سیال/فاصله را دقیق نقل کن.\n` +
    `3) برای هر منبعی که استفاده می‌کنی، یک دکمهٔ لینک با همین قالب بده و «عنوان» را به فارسیِ کوتاه بنویس ` +
    `(نه عین عنوان انگلیسی): [BUTTON](title="عنوان فارسی صفحه", href="لینک منبع").\n` +
    `4) اگر «همین رویه در خودروهای دیگر» آمده و به کاربر کمک می‌کند، آن را هم به‌عنوان مرجع مکمل ذکر کن.\n` +
    `5) اگر «زمان کار مرتبط» آمده، مدت زمان تخمینی انجام کار را هم به کاربر بگو و لینکش را بده.\n` +
    `6) پاسخ را سناریومحور و بر اساس نوع سؤال بساز. اگر سؤال دربارهٔ «تعمیر/تعویض یک قطعه» است، تا حد امکان این بخش‌ها را (فقط آن‌هایی که در متن‌ها هست) رعایت کن:\n` +
    `   • تشخیص/توضیح کوتاه مشکل یا کار\n` +
    `   • قطعات و مایعات لازم\n` +
    `   • مراحل کار به‌ترتیب\n` +
    `   • مقادیر گشتاور و مشخصات فنی (دقیق)\n` +
    `   • زمان تخمینی کار (اگر موجود بود)\n` +
    `   • هشدارها و نکات ایمنی\n` +
    `   اگر سؤال فقط یک «مقدار/مشخصه» می‌خواهد (مثل گشتاور یا ظرفیت روغن)، کوتاه و مستقیم همان عدد را بده.\n` +
    `7) اگر اطلاعات برای خودروی دقیق کاربر نبود ولی برای تایپ/مدل مشابه هست، شفاف بگو از کدام خودرو نقل می‌کنی.\n\n` +
    `=== متن‌های دفترچهٔ سرویس ===\n${contextText}\n=== پایان متن‌ها ===\n\n` +
    (historyText || '') +
    `سؤال کاربر: «${message}»\n\nحالا پاسخ بده.`
  );
}

// ---- diagnostic path (symptom / DTC rule engine) --------------------------
// True when the rule engine produced something actionable.
function diagUsable(d) {
  if (!d || d.error) return false;
  if (d.intent === 'dtc') return true;     // always answer (even "not found")
  if (d.intent === 'symptom') return (d.candidates?.length || d.procedures?.length) > 0;
  return false;
}

// The diagnosis data is rich; the Metis prompt must stay SMALL or the model
// drops the connection. So `sources` (sent to the client) keeps the full link
// set, while `contextText` (sent to Metis) is trimmed: for a single DTC we can
// afford detail; for a symptom (several candidates) we cap candidates/steps and
// emit only the key links (Description + Procedure), step NAMES otherwise.
function buildDiagnosisContext(d) {
  const sources = [];
  const blocks = [];
  const isDtc = d.intent === 'dtc';
  const maxCand = isDtc ? 3 : 3;
  let n = 0;

  (d.candidates || []).forEach((c, idx) => {
    n += 1;
    // Enriched source row so the evidence panel shows the SAME signals the assist
    // path does (band, how it matched, a confidence bar, the blob it maps to).
    sources.push({
      n, title: `DTC ${c.code} — ${faTitleBoth(c.name)}`, title_en: c.name, url: c.app_url,
      blob_id: c.blob_id ?? null,
      band: c.confidence_band || null,
      band_label: c.confidence_label || null,
      matched_via: c.matched_via || 'diagnostic',
      similarity: typeof c.confidence === 'number' ? c.confidence : null,
    });
    (c.steps || []).forEach((s) => sources.push({ n, title: `${c.code}: ${faTitle(s.aspect)}`, url: s.app_url }));
    if (idx >= maxCand) return;            // keep the prompt small
    let b = `[کاندیدا ${n}] کد: ${c.code} — ${faTitle(c.name)}`;
    if (c.confidence != null) b += ` (اطمینان ${(c.confidence * 100).toFixed(0)}٪)`;
    b += `\n`;
    if (c.inheritance_path) b += `جایگاه: ${faTitle(c.inheritance_path)}\n`;
    if (c.trigger) b += `چه زمانی ثبت می‌شود: ${(c.trigger || '').slice(0, 220)}\n`;
    if (c.steps?.length) {
      b += `مراحل عیب‌یابی: ${c.steps.map((s) => faTitle(s.aspect)).join(' ← ')}\n`;
      const desc = c.steps.find((s) => /description/i.test(s.aspect)) || c.steps[0];
      if (desc) b += `لینک توضیح/تشخیص: ${desc.app_url}\n`;
    }
    if (c.procedure) b += `لینک رویهٔ تعمیر: ${c.procedure.app_url}\n`;
    if (c.labor_time?.length) b += `زمان کار: ${c.labor_time[0].title} (${c.labor_time[0].app_url})\n`;
    if (c.sibling_dtcs?.length) b += `کدهای مرتبط: ${c.sibling_dtcs.slice(0, 3).join('، ')}\n`;
    if (c.cross_vehicle?.length) {
      const v = c.cross_vehicle[0];
      b += `همین کد در خودرو دیگر: ${v.model} ${v.variant} (${v.app_url})\n`;
    }
    blocks.push(b);
  });

  (d.procedures || []).slice(0, 3).forEach((p) => {
    n += 1;
    sources.push({ n, title: faTitleBoth(p.title), title_en: p.title, url: p.app_url });
    blocks.push(`[رویهٔ تشخیص کارخانه] ${faTitle(p.title)}\nلینک: ${p.app_url}` +
      (p.matched_symptom ? `\nمرتبط با علامت: ${faTitle(p.matched_symptom)}` : ''));
  });

  if (d.symptoms?.length) {
    blocks.push(`علائم نزدیک و «ناحیهٔ مشکوک» کارخانه (به‌ترتیب احتمال):\n` +
      d.symptoms.slice(0, 4).map((s) => `   • ${faTitle(s.text)}${s.suspected ? ` → ${faTitle(s.suspected)}` : ''}`).join('\n'));
  }

  return { sources, contextText: blocks.join('\n---\n') };
}

function buildDiagnosisPrompt({ message, d, contextText, terminology, historyText }) {
  if (d.intent === 'dtc' && !d.candidates?.length) {
    return (
      (historyText || '') +
      `کاربر کد خطای «${message}» را وارد کرده ولی این کد در دادهٔ این خودرو موجود نیست. ` +
      `مؤدبانه و فارسی بگو این کد برای این خودرو در داده‌های ما نیست و از خودت اطلاعات نساز. ` +
      `پیشنهاد بده علامت مشکل را به‌جای کد توضیح دهد.`
    );
  }
  const header =
    d.intent === 'dtc'
      ? `کاربر یک کد خطا (DTC) وارد کرده. بر اساس دادهٔ زیر، عیب را تشخیص بده و مرحله‌به‌مرحله راهنمایی کن.`
      : `کاربر علائم یک مشکل را گفته. بر اساس دادهٔ زیر (که از «جدول علائم» و «کدهای خطا»ی کارخانه برای همین خودرو استخراج شده)، محتمل‌ترین عیب‌ها را به‌ترتیب احتمال تشخیص بده.`;
  return (
    `تو یک کارشناس فنی خودرو هستی و فقط بر اساس «دادهٔ تشخیصی» زیر پاسخ می‌دهی.\n` +
    `${header}\n` +
    termsBlock(terminology) +
    `قوانین:\n` +
    `1) فقط از همین داده استفاده کن؛ چیزی از خودت اضافه/حدس نزن. اگر داده کافی نبود، صادقانه بگو.\n` +
    `2) پاسخ کاملاً فارسی، ساختارمند و عملی باشد. اصطلاحات فنی را فارسی بنویس و در صورت نبودِ معادل، ` +
    `نام انگلیسی را فقط یک‌بار داخل پرانتز بیاور؛ از کپی مستقیم عبارات انگلیسی خودداری کن. ` +
    `منطق را به‌صورت شرطی و سلسله‌مراتبی بیان کن: ` +
    `«اگر این علامت/شرط بود → محتمل‌ترین کد Y؛ اول این تست را انجام بده؛ اگر تأیید شد → رویهٔ تعمیر؛ اگر نه → کد بعدی Z».\n` +
    `3) کاندیداها را به‌ترتیب احتمال فهرست کن و برای هرکدام بگو «این کد چه زمانی ثبت می‌شود» و «جایگاهش در کدام سیستم/زیرسیستم است».\n` +
    `4) برای هر مرحله/رویه/کد، یک دکمهٔ لینک با همین قالب بده و «عنوان» را فارسی و کوتاه بنویس: [BUTTON](title="عنوان فارسی", href="لینک").\n` +
    `5) اگر «زمان کار» موجود بود، مدت تخمینی تعمیر را هم بگو و لینکش را بده.\n` +
    `6) اگر «رویهٔ تشخیص» (How to Proceed) موجود بود، آن را به‌عنوان نقطهٔ شروع عیب‌یابی پیشنهاد بده.\n` +
    `7) در پایان یک جمله بگو که این تشخیص اولیه بر پایهٔ دفترچهٔ کارخانه است و تأیید نهایی با تست عملی است.\n\n` +
    `=== دادهٔ تشخیصی ===\n${contextText}\n=== پایان داده ===\n\n` +
    (historyText || '') +
    `ورودی کاربر: «${message}»\n\nحالا تشخیص بده.`
  );
}

export async function POST(request) {
  try {
    // Rate-limit BEFORE any work so abuse can't run up the Metis bill.
    if (rateLimited(clientIp(request))) {
      return Response.json(
        { error: 'تعداد درخواست‌ها زیاد است؛ کمی بعد دوباره تلاش کن.' },
        { status: 429 }
      );
    }

    // The assistant is a paid feature: require a logged-in portal user whose
    // account is AI-eligible, validated against the backend, BEFORE any work
    // (grounding retrieval + the paid Metis call). Token rides the same-site
    // session cookie the browser sends to this same-origin route.
    const token = readCookie(request, 'kg_portal_token');
    if (!token) {
      return Response.json({ error: 'برای استفاده از دستیار هوشمند ابتدا وارد شوید.' }, { status: 401 });
    }
    let me;
    try {
      me = await backendGet('/api/auth/me/', token);
    } catch {
      return Response.json({ error: 'نشست شما منقضی شده؛ دوباره وارد شوید.' }, { status: 401 });
    }
    if (!me?.user) {
      return Response.json({ error: 'نشست شما منقضی شده؛ دوباره وارد شوید.' }, { status: 401 });
    }
    if (!me.user.ai_eligible) {
      return Response.json(
        { error: 'دستیار هوش مصنوعی برای حساب شما فعال نیست. با مدیر یا پشتیبانی تماس بگیرید.' },
        { status: 403 });
    }

    const { message, sessionId, userId, brand, model, car,
            history, prevSources } = await request.json();
    if (!message || !message.trim()) {
      return Response.json({ error: 'پیام خالی است.' }, { status: 400 });
    }
    const metisConfigured = !!(API_KEY && BOT_ID);

    // Multi-turn: sanitize the client-sent thread, then resolve short
    // anaphoric follow-ups into a self-contained RETRIEVAL query (the prompt
    // still shows the user's original message, plus a history block).
    const hist = sanitizeHistory(history);
    const prevTitles = sanitizePrevSources(prevSources);
    const historyText = historyBlock(hist);
    const { query: retrievalQuery, contextualized } =
      contextualize(message, hist, prevTitles, faTermsSet());

    // 1) Ground the answer. With a car in context, try the diagnostic engine
    //    first; fall back to general RAG retrieval.
    let prompt, sources, grounded, mode = 'assist';
    let confidence = null;     // {band, label} surfaced to the user (transparency)
    let diag = null;
    let rag = null;
    let clarifyRoots = null;   // set => ask ONE clarifying question instead
    let allowedHrefs = new Set();   // hrefs we actually retrieved (link validation)
    if (car || model) {
      try {
        diag = await backend('/api/diagnose/', { query: retrievalQuery, brand, model, car }, token);
      } catch (e) {
        console.error('diagnose error (will fall back to assist):', e);
      }
    }

    if (diagUsable(diag)) {
      mode = 'diagnose';
      const ctx = buildDiagnosisContext(diag);
      sources = ctx.sources;
      // honour the engine's own grounding gate now that it has one (parity with
      // the assist path), falling back to the old heuristic if absent.
      grounded = diag.grounded !== false &&
        (ctx.contextText.length > 0 || diag.intent === 'dtc');
      // prefer the engine's calibrated band; else derive from top confidence.
      const cb = diag.confidence_band;
      if (cb?.band) {
        confidence = { band: cb.band, label: cb.label_fa || bandLabel(cb.band) };
      } else {
        const topConf = diag.candidates?.[0]?.confidence ?? null;
        const band = topConf == null ? null : topConf >= 0.8 ? 'high' : topConf >= 0.5 ? 'medium' : 'low';
        confidence = band ? { band, label: bandLabel(band) } : null;
      }
      allowedHrefs = collectAllowedHrefsDiag(diag);
      const terminology = collectPairs([
        ...(diag.candidates || []).flatMap((c) => [c.name, ...(c.steps || []).map((s) => s.aspect)]),
        ...(diag.procedures || []).map((p) => p.title),
        ...(diag.symptoms || []).map((s) => `${s.text || ''} ${s.suspected || ''}`),
      ]);
      prompt = buildDiagnosisPrompt({ message, d: diag, contextText: ctx.contextText,
                                      terminology, historyText });
    } else {
      // Translate before retrieving when the flag is on. Fail-open: a null
      // translation means we retrieve with the original Persian, exactly as
      // before. NOT applied to /api/diagnose above -- that engine matches
      // Persian symptom text.
      const translated = await translateQuery(retrievalQuery);
      const assistQuery = translated || retrievalQuery;
      try {
        rag = await backend('/api/assist/', { query: assistQuery, brand, model, car }, token);
      } catch (e) {
        console.error('RAG retrieve error:', e);
        return Response.json(
          { error: 'بازیابی از دیتابیس ناموفق بود. مطمئن شو ایندکس ساخته شده (build_rag / build_diag).' },
          { status: 502 }
        );
      }
      // honour the backend's grounding gate (out-of-domain queries are refused
      // even if a weak nearest neighbour exists).
      const hasContext = (rag?.hits?.length || 0) > 0 && rag?.grounded !== false;
      const built = hasContext ? buildContext(rag) : { sources: [], contextText: '' };
      // Structured vehicle facts for the pinned car (schema.org-derived,
      // deterministic). Prepended INSIDE the grounding context so the phraser
      // can answer spec questions (fuel type, drivetrain, capacities, tires)
      // while remaining strictly context-only.
      if (hasContext && rag?.vehicle_specs) {
        built.contextText = `مشخصات فنی ثبت‌شدهٔ این خودرو (قطعی):\n${rag.vehicle_specs}\n---\n${built.contextText}`;
      }
      sources = built.sources;
      grounded = hasContext;
      const cb = rag?.confidence_band;
      confidence = cb ? { band: cb.band, label: cb.label_fa } : null;
      if (hasContext) allowedHrefs = collectAllowedHrefs(rag);
      const terminology = hasContext ? collectPairs(
        (rag.hits || []).flatMap((h) => [h.title, h.title_path, (h.text || '').slice(0, 1800),
                                         ...(h.related || []).map((r) => r.title)])) : [];

      // Ambiguity gate: a weakly-confident answer whose top hits scatter over
      // 3+ unrelated systems is better served by ONE clarifying question. The
      // grounding math is untouched — only the phrasing changes.
      if (hasContext && confidence?.band === 'low') {
        const roots = systemRoots(rag);
        if (roots.length >= 3) clarifyRoots = roots.slice(0, 3);
      }
      if (clarifyRoots) {
        mode = 'clarify';
        prompt = buildClarifyPrompt({ message, roots: clarifyRoots.map((r) => faTitle(r)),
                                      historyText });
      } else {
        prompt = buildPrompt({ message, contextText: built.contextText, hasContext,
                               terminology, historyText });
      }
    }

    // 2) Let Metis phrase the grounded context. Metis is the ONLY external
    //    dependency, so any failure (unconfigured / down / timeout / over budget)
    //    degrades to a deterministic no-LLM digest of what we already retrieved,
    //    instead of failing the whole request.
    let sid = sessionId;
    let rawReply = null;
    let degraded = false;
    if (metisConfigured) {
      try {
        if (!sid) {
          const session = await metis('session', {
            botId: BOT_ID,
            user: { id: userId || `web-${Date.now()}`, name: '_' },
          });
          sid = session.id;
        }
        const reply = await metis(`session/${sid}/message`, {
          message: { type: 'USER', content: prompt },
        });
        rawReply = reply?.content ?? '';
      } catch (e) {
        console.error('Metis failed -> serving no-LLM fallback:', e);
        degraded = true;
      }
    } else {
      console.warn('Metis not configured -> serving no-LLM fallback.');
      degraded = true;
    }

    if (degraded || !rawReply || !rawReply.trim()) {
      degraded = true;
      rawReply = mode === 'clarify'
        ? fallbackClarify(clarifyRoots.map((r) => faTitle(r)))
        : fallbackReply({ mode, sources, grounded });
    }

    // Faithfulness gate: drop any link the model invented that we didn't
    // actually retrieve, so the UI can never show a fabricated source button.
    // (Harmless on the fallback text — its links all come from `sources`.)
    const { text: safeReply, stripped } = sanitizeButtons(rawReply, allowedHrefs);
    // The scope verdict is prepended AFTER sanitisation so it can never be
    // stripped, reworded or dropped by the phraser.
    const banner = grounded ? scopeBanner(rag) : '';

    return Response.json({
      sessionId: sid,
      reply: banner + safeReply,
      evidenceScope: rag?.evidence || null,
      strippedLinks: stripped,
      sources,
      grounded,
      mode,
      confidence,                                    // {band, label} or null
      degraded,                                      // true => no-LLM fallback used
      llm: !degraded,
      suggestions: buildSuggestions({ mode, rag, diag, clarifyRoots }),
      contextualized,                                // true => follow-up was expanded
      topBlobs: (sources || []).map((s) => s.blob_id).filter((b) => b != null),
    });
  } catch (err) {
    console.error('chat proxy error:', err);
    return Response.json({ error: 'ارتباط با دستیار ناموفق بود.' }, { status: 502 });
  }
}
