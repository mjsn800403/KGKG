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
import {
  sanitizeHistory, sanitizePrevSources, historyBlock,
  collectAllowedHrefs, collectAllowedHrefsDiag, sanitizeButtons,
  buildPrompt, buildDiagnosisPrompt,
} from '../../../lib/chatPrompt';

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

// Streaming variant: Metis answers `<path>/stream` with SSE lines
// `data:{"message":{"content":"<piece>"}}`. Calls onDelta per piece and
// resolves with the whole reply. The closing event carries a `financial`
// block (tokens + cost), handed to onUsage.
async function metisStream(path, body, onDelta, onUsage) {
  const res = await fetch(`${METIS_BASE}/${path}/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Api-Key': API_KEY },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(90000),
  });
  if (!res.ok || !res.body) {
    const text = await res.text().catch(() => '');
    throw new Error(`Metis ${path}/stream failed: ${res.status} ${text}`);
  }
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = '';
  let full = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let nl;
    while ((nl = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, nl).trim();
      buf = buf.slice(nl + 1);
      if (!line.startsWith('data:')) continue;
      let ev;
      try { ev = JSON.parse(line.slice(5)); } catch { continue; }
      const piece = ev?.message?.content || '';
      if (piece) { full += piece; onDelta(piece); }
      if (ev?.financial && onUsage) onUsage(ev.financial);
    }
  }
  return full;
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

// `enabled` is the user's mq_translate A/B arm (api/flags.py) when that flag
// is defined, else the RAG_MQ_TRANSLATE env default.
async function translateQuery(q, enabled = MQ_TRANSLATE) {
  if (!enabled || !(API_KEY && BOT_ID) || !q || !FA_RE.test(q)) return null;
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
    blocks.push(b);
  });
  return { sources, contextText: blocks.join('\n---\n') };
}

// Parts-catalog rows and SST tools found by the backend's table lookups.
function lookupBlock(rag) {
  let b = '';
  const parts = rag?.parts || [];
  if (parts.length) {
    b += `کاتالوگ قطعات این خودرو (شمارهٔ فنی دقیق؛ همین‌ها را نقل کن):\n` +
      parts.map((p) => `- ${p.pn} — ${p.name_fa || ''} (${p.name_en || ''})` +
        (p.qty ? `، تعداد ${p.qty}` : '') + (p.date_range ? `، تولید ${p.date_range}` : '') +
        ` [${p.catalog}]`).join('\n') + `\n`;
  }
  const tools = rag?.sst_tools || [];
  if (tools.length) {
    b += `ابزارهای مخصوص (SST) سیستم‌های مرتبط در این خودرو:\n` +
      tools.map((t) => `- ${t.number} — ${t.name}` + (t.kit_of ? ` (جزء کیت ${t.kit_of})` : '') +
        (t.used_in?.length ? ` — کاربرد: ${t.used_in.join('، ')}` : '')).join('\n') + `\n`;
  }
  return b;
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

export async function POST(request) {
  const t0 = Date.now();
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
    {
      // Read /me directly so an expired / locked account gets its real reason
      // instead of a generic "session expired".
      const mr = await fetch(`${BACKEND_URL}/api/auth/me/`, {
        headers: { Authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(30000),
      }).catch(() => null);
      const mj = mr ? await mr.json().catch(() => ({})) : {};
      if (!mr || !mr.ok) {
        return Response.json({ error: mj?.detail || 'نشست شما منقضی شده؛ دوباره وارد شوید.',
                               reason: mj?.reason || null }, { status: 401 });
      }
      me = mj;
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
            history, prevSources, stream: wantStream } = await request.json();
    if (!message || !message.trim()) {
      return Response.json({ error: 'پیام خالی است.' }, { status: 400 });
    }
    // Plan allowance (demo 5 / 2-day 20 / monthly 150 / annual 200). Checked
    // here (fail closed: no answer if the allowance can't be read) and charged
    // only once a real answer has been produced — an empty message, a failed
    // retrieval or an LLM outage never costs the user a question.
    const quotaCall = (method, payload) => fetch(`${BACKEND_URL}/api/auth/ai-usage/`, {
      method,
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: payload ? JSON.stringify(payload) : undefined,
    }).then(async (r) => ({ status: r.status, body: await r.json().catch(() => ({})) }))
      .catch(() => ({ status: 0, body: {} }));
    let quota = null;
    // A/B arms for this user (api/flags.py), delivered with the quota read.
    let flags = {};
    {
      const q = await quotaCall('GET');
      if (q.status === 429) {
        return Response.json({ error: q.body.error, quota: q.body }, { status: 429 });
      }
      if (q.status !== 200) {
        return Response.json({ error: 'بررسی سهمیهٔ دستیار ممکن نشد؛ کمی بعد دوباره تلاش کنید.' },
          { status: 503 });
      }
      const { flags: arms, ...usage } = q.body || {};
      quota = usage;
      flags = arms && typeof arms === 'object' ? arms : {};
    }
    const charge = async (payload) => {
      if (payload.degraded) return payload;
      const q = await quotaCall('POST', { detail: String(message).slice(0, 300) });
      if (q.body?.quota) quota = q.body.quota;
      return { ...payload, quota };
    };
    const metisConfigured = !!(API_KEY && BOT_ID);
    // Phraser usage for the chat log: streamed replies report tokens + cost,
    // non-streamed ones only `billing.cost`.
    const llm = { ms: null, usage: null, cost: null };
    const fromFinancial = (f) => { llm.usage = f; llm.cost = f?.totalCost ?? null; };
    // Chat log for admins / managers (api/chatlog.py). Best-effort: a logging
    // failure never touches the user's answer.
    const logKey = globalThis.crypto.randomUUID();
    const record = (payload) => {
      fetch(`${BACKEND_URL}/api/auth/chat-log/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          question: String(message).slice(0, 4000),
          answer: payload.reply || '',
          session_id: payload.sessionId || '',
          mode: payload.mode, grounded: !!payload.grounded, degraded: !!payload.degraded,
          vehicle: car || [brand, model].filter(Boolean).join(' '),
          sources: (payload.sources || []).map((s) => ({ title: s.title, href: s.url || s.href || '' })),
          latency_ms: Date.now() - t0,
          llm_latency_ms: llm.ms,
          input_tokens: llm.usage?.inputTokens ?? null,
          output_tokens: llm.usage?.outputTokens ?? null,
          llm_cost: llm.cost,
          llm_usage: llm.usage || {},
          client_key: logKey,
          flags,
        }),
        signal: AbortSignal.timeout(10000),
      }).catch((e) => console.error('chat-log record failed:', e));
      return { ...payload, logKey };
    };

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
    // Part-number / special-tool / labor-time / spec questions are lookups,
    // not faults: the diagnose engine would answer them with an unrelated
    // DTC. Send them straight to retrieval unless they name a DTC code.
    const hasDtc = /\b[PCBU][0-9A-F]{4}\b/i.test(message);
    const LOOKUP_RE = /شماره\s*(فنی|قطعه|پارت)|پارت\s*نامبر|کد\s*قطعه|part\s*(no|number|#)|ابزار|\bSST\b|special\s+tool|زمان\s*(کار|تعمیر|استاندارد)|اجرت|labor|گشتاور|torque|ظرفیت|capacity|چند\s*لیتر|مشخصات/i;
    const isLookup = !hasDtc && LOOKUP_RE.test(message);
    // Instruction-injection attempts are not symptoms either; the diagnose
    // engine would turn them into a fault guess. Retrieval + the grounded
    // prompt answer (or decline) them instead.
    const INJECTION_RE = /ignore\s+(all\s+|the\s+)?(previous|prior|above)|system\s*prompt|developer\s+mode|jailbreak|you\s+are\s+now|disregard\s+(the\s+)?(rules|instructions)|دستور(ات|های)?\s*(قبلی|بالا)|نادیده\s*بگیر|پرامپت|پرومپت|قوانین\s*(را|ت)\s*(فراموش|نادیده)/i;
    const isInjection = INJECTION_RE.test(message);
    if ((car || model) && !isLookup && !isInjection) {
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
      const translated = await translateQuery(retrievalQuery, flags.mq_translate ?? MQ_TRANSLATE);
      const assistQuery = translated || retrievalQuery;
      try {
        rag = await backend('/api/assist/', { query: assistQuery, brand, model, car }, token);
        // Hard rule: answer only from the selected vehicle. Pages of other
        // vehicles never reach the prompt; with none left the reply is the
        // honest "not in our data" answer.
        if (rag?.hits?.length && (car || model)) {
          rag.hits = rag.hits.filter((h) => (car ? h.car_stem === car : h.model === model));
          rag.evidence = null;
        }
      } catch (e) {
        console.error('RAG retrieve error:', e);
        return Response.json(
          { error: 'بازیابی از دیتابیس ناموفق بود. مطمئن شو ایندکس ساخته شده (build_rag / build_diag).' },
          { status: 502 }
        );
      }
      // honour the backend's grounding gate (out-of-domain queries are refused
      // even if a weak nearest neighbour exists).
      const hasContext = ((rag?.hits?.length || 0) > 0 && rag?.grounded !== false) ||
        (rag?.parts?.length || 0) > 0 || (rag?.sst_tools?.length || 0) > 0;
      const built = (rag?.hits?.length && rag?.grounded !== false)
        ? buildContext(rag) : { sources: [], contextText: '' };
      // Structured vehicle facts for the pinned car (schema.org-derived,
      // deterministic). Prepended INSIDE the grounding context so the phraser
      // can answer spec questions (fuel type, drivetrain, capacities, tires)
      // while remaining strictly context-only.
      const lookupText = lookupBlock(rag);
      if (lookupText) {
        built.contextText = `${lookupText}---\n${built.contextText}`;
      }
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

    // Everything after the LLM text is the same for both transports.
    const finish = (reply, wasDegraded) => {
      let text = reply;
      let deg = wasDegraded;
      if (deg || !text || !text.trim()) {
        deg = true;
        text = mode === 'clarify'
          ? fallbackClarify(clarifyRoots.map((r) => faTitle(r)))
          : fallbackReply({ mode, sources, grounded });
      }
      // Faithfulness gate: drop any link the model invented that we didn't
      // actually retrieve, so the UI can never show a fabricated source button.
      const { text: safeReply, stripped } = sanitizeButtons(text, allowedHrefs);
      // The scope verdict is prepended AFTER sanitisation so it can never be
      // stripped, reworded or dropped by the phraser.
      const banner = grounded ? scopeBanner(rag) : '';
      return {
        sessionId: sid,
        reply: banner + safeReply,
        evidenceScope: rag?.evidence || null,
        strippedLinks: stripped,
        sources,
        grounded,
        mode,
        confidence,
        degraded: deg,
        llm: !deg,
        suggestions: buildSuggestions({ mode, rag, diag, clarifyRoots }),
        contextualized,
        quota,
        topBlobs: (sources || []).map((s) => s.blob_id).filter((b) => b != null),
      };
    };

    // Streaming transport (NDJSON): {t:'delta',d} pieces as the phraser writes,
    // then {t:'done', ...payload} with the validated reply. Deltas are display
    // only; the client swaps in the final gated text when 'done' arrives.
    if (wantStream && metisConfigured) {
      const enc = new TextEncoder();
      const body = new ReadableStream({
        async start(ctrl) {
          const send = (obj) => ctrl.enqueue(enc.encode(JSON.stringify(obj) + '\n'));
          let reply = null;
          let deg = false;
          try {
            if (!sid) {
              const session = await metis('session', {
                botId: BOT_ID,
                user: { id: userId || `web-${Date.now()}`, name: '_' },
              });
              sid = session.id;
            }
            const tl = Date.now();
            reply = await metisStream(`session/${sid}/message`, {
              message: { type: 'USER', content: prompt },
            }, (d) => send({ t: 'delta', d }), fromFinancial);
            llm.ms = Date.now() - tl;
          } catch (e) {
            console.error('Metis stream failed -> serving no-LLM fallback:', e);
            deg = true;
          }
          try {
            send({ t: 'done', ...record(await charge(finish(reply, deg))) });
          } catch (e) {
            console.error('chat finish error:', e);
            send({ t: 'error', error: 'ارتباط با دستیار ناموفق بود.' });
          }
          ctrl.close();
        },
      });
      return new Response(body, {
        headers: {
          'Content-Type': 'application/x-ndjson; charset=utf-8',
          'Cache-Control': 'no-store',
          'X-Accel-Buffering': 'no',
        },
      });
    }

    if (metisConfigured) {
      try {
        if (!sid) {
          const session = await metis('session', {
            botId: BOT_ID,
            user: { id: userId || `web-${Date.now()}`, name: '_' },
          });
          sid = session.id;
        }
        const tl = Date.now();
        const reply = await metis(`session/${sid}/message`, {
          message: { type: 'USER', content: prompt },
        });
        llm.ms = Date.now() - tl;
        llm.cost = reply?.billing?.cost ?? null;
        if (reply?.billing) llm.usage = { billing: reply.billing };
        rawReply = reply?.content ?? '';
      } catch (e) {
        console.error('Metis failed -> serving no-LLM fallback:', e);
        degraded = true;
      }
    } else {
      console.warn('Metis not configured -> serving no-LLM fallback.');
      degraded = true;
    }

    return Response.json(record(await charge(finish(rawReply, degraded))));
  } catch (err) {
    console.error('chat proxy error:', err);
    return Response.json({ error: 'ارتباط با دستیار ناموفق بود.' }, { status: 502 });
  }
}
