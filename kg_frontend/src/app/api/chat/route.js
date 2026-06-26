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

async function backend(path, body) {
  const res = await fetch(`${BACKEND_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(60000),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail?.error || `${path} failed: ${res.status}`);
  }
  return res.json();
}

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
  const xff = request.headers.get('x-forwarded-for');
  if (xff) return xff.split(',')[0].trim();
  return request.headers.get('x-real-ip') || 'unknown';
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

// ---- no-LLM fallback (resilience: Metis is the only external dependency) ----
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
    (h.cross_vehicle || []).forEach((c) => c.app_url && set.add(normHref(c.app_url)));
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
    (c.cross_vehicle || []).forEach((v) => v.app_url && set.add(normHref(v.app_url)));
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
    sources.push({ n, title: h.title, path: h.title_path, url: h.app_url,
                   model: h.model, variant: h.variant, blob_id: h.blob_id,
                   band: h.confidence_band, band_label: h.confidence_label,
                   matched_via: h.matched_via, similarity: h.similarity });
    let b = `[منبع ${n}] خودرو: ${h.brand} ${h.model}${h.variant ? ' ' + h.variant : ''}\n`;
    b += `عنوان: ${h.title}\nمسیر: ${h.title_path}\nلینک: ${h.app_url}\n`;
    b += `متن:\n${(h.text || '').slice(0, 1800)}\n`;
    const labor = (h.related || []).filter((r) => r.relation === 'labor_time');
    const other = (h.related || []).filter((r) => r.relation !== 'labor_time');
    if (labor.length) {
      b += `زمان کار مرتبط: ` + labor.map((r) => `${r.title} (${r.app_url})`).join(' ، ') + `\n`;
    }
    if (other.length) {
      b += `صفحات مرتبط: ` + other.map((r) => `${r.title} (${r.app_url})`).join(' ، ') + `\n`;
    }
    if (h.cross_vehicle?.length) {
      b += `همین رویه در خودروهای دیگر: ` +
        h.cross_vehicle.map((c) => `${c.model} ${c.variant} [${c.scope}] (${c.app_url})`).join(' ، ') + `\n`;
    }
    blocks.push(b);
  });
  return { sources, contextText: blocks.join('\n---\n') };
}

function buildPrompt({ message, contextText, hasContext }) {
  if (!hasContext) {
    return (
      `سؤال کاربر: «${message}»\n\n` +
      `در دفترچه‌های سرویس ما هیچ مطلب مرتبطی پیدا نشد. ` +
      `صادقانه به کاربر بگو این مورد در داده‌های ما موجود نیست و از خودت اطلاعات فنی نساز.`
    );
  }
  return (
    `تو دستیار تعمیراتی هستی و فقط بر اساس «متن‌های دفترچهٔ سرویس» زیر پاسخ می‌دهی.\n` +
    `قوانین:\n` +
    `1) فقط از همین متن‌ها استفاده کن؛ اگر چیزی در آن‌ها نبود، بگو در داده‌ها نیست و حدس نزن.\n` +
    `2) پاسخ را فارسی، مرحله‌به‌مرحله و کاربردی بنویس (مقادیر گشتاور/سیال را دقیق نقل کن).\n` +
    `3) برای هر منبعی که استفاده می‌کنی، یک دکمهٔ لینک با همین قالب بده: ` +
    `[BUTTON](title="عنوان صفحه", href="لینک منبع").\n` +
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
      n, title: `DTC ${c.code} — ${c.name}`, url: c.app_url,
      blob_id: c.blob_id ?? null,
      band: c.confidence_band || null,
      band_label: c.confidence_label || null,
      matched_via: c.matched_via || 'diagnostic',
      similarity: typeof c.confidence === 'number' ? c.confidence : null,
    });
    (c.steps || []).forEach((s) => sources.push({ n, title: `${c.code}: ${s.aspect}`, url: s.app_url }));
    if (idx >= maxCand) return;            // keep the prompt small
    let b = `[کاندیدا ${n}] کد: ${c.code} — ${c.name}`;
    if (c.confidence != null) b += ` (اطمینان ${(c.confidence * 100).toFixed(0)}٪)`;
    b += `\n`;
    if (c.inheritance_path) b += `جایگاه: ${c.inheritance_path}\n`;
    if (c.trigger) b += `چه زمانی ثبت می‌شود: ${(c.trigger || '').slice(0, 220)}\n`;
    if (c.steps?.length) {
      b += `مراحل عیب‌یابی: ${c.steps.map((s) => s.aspect).join(' ← ')}\n`;
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
    sources.push({ n, title: p.title, url: p.app_url });
    blocks.push(`[رویهٔ تشخیص کارخانه] ${p.title}\nلینک: ${p.app_url}` +
      (p.matched_symptom ? `\nمرتبط با علامت: ${p.matched_symptom}` : ''));
  });

  if (d.symptoms?.length) {
    blocks.push(`علائم نزدیک و «ناحیهٔ مشکوک» کارخانه (به‌ترتیب احتمال):\n` +
      d.symptoms.slice(0, 4).map((s) => `   • ${s.text}${s.suspected ? ` → ${s.suspected}` : ''}`).join('\n'));
  }

  return { sources, contextText: blocks.join('\n---\n') };
}

function buildDiagnosisPrompt({ message, d, contextText }) {
  if (d.intent === 'dtc' && !d.candidates?.length) {
    return (
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
    `قوانین:\n` +
    `1) فقط از همین داده استفاده کن؛ چیزی از خودت اضافه/حدس نزن. اگر داده کافی نبود، صادقانه بگو.\n` +
    `2) پاسخ فارسی، ساختارمند و عملی باشد. منطق را به‌صورت شرطی و سلسله‌مراتبی بیان کن: ` +
    `«اگر این علامت/شرط بود → محتمل‌ترین کد Y؛ اول این تست را انجام بده؛ اگر تأیید شد → رویهٔ تعمیر؛ اگر نه → کد بعدی Z».\n` +
    `3) کاندیداها را به‌ترتیب احتمال فهرست کن و برای هرکدام بگو «این کد چه زمانی ثبت می‌شود» و «جایگاهش در کدام سیستم/زیرسیستم است».\n` +
    `4) برای هر مرحله/رویه/کد، یک دکمهٔ لینک با همین قالب بده: [BUTTON](title="عنوان", href="لینک").\n` +
    `5) اگر «زمان کار» موجود بود، مدت تخمینی تعمیر را هم بگو و لینکش را بده.\n` +
    `6) اگر «رویهٔ تشخیص» (How to Proceed) موجود بود، آن را به‌عنوان نقطهٔ شروع عیب‌یابی پیشنهاد بده.\n` +
    `7) در پایان یک جمله بگو که این تشخیص اولیه بر پایهٔ دفترچهٔ کارخانه است و تأیید نهایی با تست عملی است.\n\n` +
    `=== دادهٔ تشخیصی ===\n${contextText}\n=== پایان داده ===\n\n` +
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

    const { message, sessionId, userId, brand, model, car } = await request.json();
    if (!message || !message.trim()) {
      return Response.json({ error: 'پیام خالی است.' }, { status: 400 });
    }
    const metisConfigured = !!(API_KEY && BOT_ID);

    // 1) Ground the answer. With a car in context, try the diagnostic engine
    //    first; fall back to general RAG retrieval.
    let prompt, sources, grounded, mode = 'assist';
    let confidence = null;     // {band, label} surfaced to the user (transparency)
    let diag = null;
    let allowedHrefs = new Set();   // hrefs we actually retrieved (link validation)
    if (car || model) {
      try {
        diag = await backend('/api/diagnose/', { query: message, brand, model, car });
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
      prompt = buildDiagnosisPrompt({ message, d: diag, contextText: ctx.contextText });
    } else {
      let rag;
      try {
        rag = await backend('/api/assist/', { query: message, brand, model, car });
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
      sources = built.sources;
      grounded = hasContext;
      const cb = rag?.confidence_band;
      confidence = cb ? { band: cb.band, label: cb.label_fa } : null;
      if (hasContext) allowedHrefs = collectAllowedHrefs(rag);
      prompt = buildPrompt({ message, contextText: built.contextText, hasContext });
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
      rawReply = fallbackReply({ mode, sources, grounded });
    }

    // Faithfulness gate: drop any link the model invented that we didn't
    // actually retrieve, so the UI can never show a fabricated source button.
    // (Harmless on the fallback text — its links all come from `sources`.)
    const { text: safeReply, stripped } = sanitizeButtons(rawReply, allowedHrefs);

    return Response.json({
      sessionId: sid,
      reply: safeReply,
      strippedLinks: stripped,
      sources,
      grounded,
      mode,
      confidence,                                    // {band, label} or null
      degraded,                                      // true => no-LLM fallback used
      llm: !degraded,
      topBlobs: (sources || []).map((s) => s.blob_id).filter((b) => b != null),
    });
  } catch (err) {
    console.error('chat proxy error:', err);
    return Response.json({ error: 'ارتباط با دستیار ناموفق بود.' }, { status: 502 });
  }
}
