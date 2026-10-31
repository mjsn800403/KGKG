// ---------------------------------------------------------------------------
// Contextual smart-hints — rule definitions.
// ---------------------------------------------------------------------------
// A hint is a *behavioural* rule (copy + a condition), kept separate from the
// doc-synced ARTICLES so the content registry stays pure data. The engine
// (HintLayer) evaluates rules against a live context and shows AT MOST ONE
// non-intrusive hint per surface — the least noisy design that still catches
// the common mistakes and inefficient workflows the product wants to prevent.
//
// A rule's `test(ctx)` returns true only when the hint should show right now.
// Rules that depend on a runtime `signal` return false when that signal is
// absent, so an un-wired signal simply keeps its hint dormant (never a false
// positive). Every hint is dismissible and frequency-capped (see storage.js).
//
// ctx = { audience, pathname, section, signals, portalUser }
//   audience : { role, caps:{manage,analytics,ai}, isAdmin }  (from content.js)
//   signals  : plain object populated by reportSignal(name, value) around the app
//
// action.kind: 'help' (open an article) | 'tour' (start a tour) |
//              'link' (navigate) | 'dismiss' (acknowledge only)
// See docs/13-guidance-system.md.
// ---------------------------------------------------------------------------

import { ROLES } from './content';

const MIN = 60 * 1000;
const DAY = 24 * 60 * MIN;

// Feature-discovery nudges. These fire on FRICTION, never on a timer: the
// discovery failure they answer does not happen at minute one — every seat saw
// the onboarding tour and the parts catalogue still went unopened by 28 of 34
// of them. It happens three weeks in, at the moment something would have
// helped. Each reads `ctx.onboarding`, the same payload the discovery strip
// uses, so a hint can never suggest a feature the seat has already used or is
// not entitled to. A null payload (not signed in, or the request failed)
// leaves every one of them dormant.
const needs = (ctx, id) => {
  const onb = ctx.onboarding;
  if (!onb || !Array.isArray(onb.items)) return false;   // unknown: stay quiet
  // Dismissing the strip says "stop telling me about this". Keeping that
  // separate from PROGRESS is right — closing a prompt is not discovering
  // anything, and the metric must not pretend otherwise — but extending it to
  // the nudges would break the promise the dismiss button makes.
  if (onb.dismissed) return false;
  const item = onb.items.find((i) => i.id === id);
  return Boolean(item) && !item.done;           // entitled, and not yet done
};

// A vehicle page: /<brand>/<year>/<model>[/...]. `/frm/<slug>/...` has the
// same shape and is NOT a vehicle, so it is excluded by name.
const VEHICLE_PATH = /^\/(?!frm\/)[^/]+\/[^/]+\/[^/]+/;

export const HINT_RULES = [
  // The single best moment to mention the assistant: a search just came back
  // empty. The person has a question the search box could not answer, which is
  // exactly what the assistant is for.
  {
    id: 'search-found-nothing',
    severity: 'tip',
    roles: [ROLES.USER, ROLES.ANALYST, ROLES.MANAGER],
    cooldownMs: 7 * DAY,
    maxShows: 2,
    // Only on the search results page itself. `signals` is provider state
    // that is never cleared, so without this the hint followed the person
    // around the app for the rest of the session — and, being first in the
    // list, suppressed every other hint while it did.
    test: (ctx) =>
      ctx.pathname.includes('/search') &&
      Boolean(ctx.signals['search.zeroResult']) &&
      needs(ctx, 'ask_assistant'),
    title: 'جستجو چیزی پیدا نکرد — از دستیار بپرسید',
    body: 'دستیار هوشمند سؤال را می‌فهمد، نه فقط کلمه را؛ پاسخ را با ارجاع به همان فصل منوال می‌دهد. فارسی هم بپرسید.',
    action: { kind: 'link', href: '/assistant', label: 'پرسیدن از دستیار' },
  },

  // Standing on a vehicle whose grant includes the parts catalogue, having
  // never opened it. Six of 34 seats had found it in four months.
  {
    id: 'parts-never-opened',
    severity: 'tip',
    roles: [ROLES.USER, ROLES.ANALYST, ROLES.MANAGER],
    cooldownMs: 14 * DAY,
    maxShows: 2,
    test: (ctx) =>
      VEHICLE_PATH.test(ctx.pathname) &&
      !ctx.pathname.includes('/parts') &&
      needs(ctx, 'open_parts'),
    // Entitlement is any-car (the seat holds the parts layer SOMEWHERE), so
    // the copy must not claim it about the vehicle on screen, and must not
    // point at a «قطعات» button that is only rendered where the layer is
    // actually granted.
    title: 'کاتالوگ قطعات را امتحان کنید',
    body: 'برای خودروهایی که کاتالوگ قطعات دارند، دکمهٔ «قطعات» در صفحهٔ همان خودرو ظاهر می‌شود: شمارهٔ فنی و نقشهٔ انفجاری.',
    action: { kind: 'dismiss', label: 'متوجه شدم' },
  },

  // The classic "AI won't answer me" confusion — purely data-driven from the
  // portal user's eligibility, so it needs no instrumentation.
  {
    id: 'ai-not-eligible',
    severity: 'tip',
    roles: [ROLES.USER, ROLES.ANALYST, ROLES.MANAGER],
    cooldownMs: 3 * DAY,
    maxShows: 3,
    test: (ctx) =>
      ctx.pathname.startsWith('/assistant') &&
      ctx.audience.role !== ROLES.ADMIN &&
      ctx.audience.caps.ai === false,
    title: 'دستیار هنوز برای شما فعال نیست',
    body: 'پاسخ‌دهی دستیار به سه شرط نیاز دارد: فعال بودن دستیار برای حساب شما، فعال بودن آن برای شرکت، و داشتن بستهٔ «منوال تعمیر». راهنما را ببینید تا بدانید کدام مورد لازم است.',
    action: { kind: 'help', article: 'assistant-eligibility', label: 'چرا؟ و چه کنم' },
  },

  // One-time precision nudge on the assistant — improves answer quality with no
  // data dependency. Capped to a single appearance.
  {
    id: 'assistant-precision',
    severity: 'tip',
    roles: [ROLES.USER, ROLES.ANALYST, ROLES.MANAGER],
    cooldownMs: 0,
    maxShows: 1,
    test: (ctx) =>
      ctx.pathname.startsWith('/assistant') &&
      ctx.audience.caps.ai === true,
    title: 'پاسخ دقیق‌تر بگیرید',
    body: 'برای بهترین نتیجه، خودرو را مشخص کنید (برند، مدل و سال) و اگر کد خطا دارید عیناً بنویسید — مثلاً P0171.',
    action: { kind: 'dismiss', label: 'متوجه شدم' },
  },

  // Manager landed on an empty team — point them at the first useful action.
  // Driven by a signal TeamView reports (member count excluding the manager).
  {
    id: 'team-empty',
    severity: 'info',
    roles: [ROLES.MANAGER],
    cooldownMs: DAY,
    maxShows: 4,
    test: (ctx) =>
      (ctx.pathname === '/team' || ctx.pathname === '/team/') &&
      typeof ctx.signals['team.memberCount'] === 'number' &&
      ctx.signals['team.memberCount'] <= 0,
    title: 'تیم شما هنوز عضوی ندارد',
    body: 'برای شروع، اولین کارمند را اضافه کنید. می‌توانید لینک دعوت بفرستید یا مستقیماً نام کاربری و رمز بسازید.',
    action: { kind: 'help', article: 'team-add-member', label: 'چطور کارمند اضافه کنم' },
  },

  // Common mistake: filling the "invite by e-mail" form with no e-mail. Since
  // no SMTP is configured in production, credentials mode is usually the right
  // choice. Driven by a signal TeamView's drawer reports.
  {
    id: 'team-invite-no-email',
    severity: 'warn',
    roles: [ROLES.MANAGER],
    cooldownMs: 6 * 60 * MIN,
    maxShows: 5,
    test: (ctx) => ctx.signals['team.drawer'] === 'invite-no-email',
    title: 'ایمیلی برای دعوت وارد نشده',
    body: 'برای ارسال دعوت‌نامه به ایمیل نیاز است. اگر ایمیل ندارید، حالت «نام کاربری و رمز» را انتخاب کنید تا حساب بلافاصله ساخته شود و اطلاعات ورود را خودتان تحویل دهید.',
    action: { kind: 'dismiss', label: 'باشه' },
  },

  // Admin: new vehicle data has been detected but not processed yet.
  {
    id: 'admin-new-data',
    severity: 'info',
    roles: [ROLES.ADMIN],
    cooldownMs: 2 * 60 * MIN,
    maxShows: 20,
    test: (ctx) =>
      ctx.pathname.startsWith('/admin') &&
      Number(ctx.signals['admin.pendingWork']) > 0 &&
      ctx.section !== 'pipeline',
    title: 'دادهٔ پردازش‌نشده وجود دارد',
    body: 'خودرو یا داده‌ای هست که هنوز ایندکس/پردازش نشده. برای اینکه در جستجو و دستیار در دسترس شود، پردازش داده‌ها را اجرا کنید.',
    action: { kind: 'link', href: '/admin#pipeline', label: 'رفتن به پردازش داده‌ها' },
  },
];

// Pick the single best hint to show for the current context (or null).
export function pickHint(ctx, { isDismissed, shownCount }) {
  for (const rule of HINT_RULES) {
    const roleOk = rule.roles.includes(ctx.audience.role) || (rule.cap && ctx.audience.caps?.[rule.cap]);
    if (!roleOk) continue;
    if (isDismissed(rule.id)) continue;
    if (rule.maxShows && shownCount(rule.id) >= rule.maxShows) continue;
    let ok = false;
    try { ok = !!rule.test(ctx); } catch { ok = false; }
    if (ok) return rule;
  }
  return null;
}
