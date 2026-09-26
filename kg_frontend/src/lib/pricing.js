// Subscription pricing — the ONE source for the public plans page and the
// admin request card, so a quote the customer saw is read back identically.
//
// Model (agreed 2026-09-22):
//   • One subscription covers every vehicle and every document layer on the
//     platform; the AI assistant is included with a question allowance.
//   • Durations: a free 1-day demo (1 user), a 2-day pass (1 user),
//     monthly, and annual (= 10 × monthly).
//   • Team price is graduated on a 12M-toman single-seat month:
//       seat 1 100% · seat 2 60% · seat 3 50% · seats 4–10 40% · seats 11–50 35%
//     Standard team sizes use rounded list prices; any other size is the
//     formula rounded to the nearest million. Above 50 seats is quoted.
// All amounts here are in MILLION toman.

export const BASE_MONTHLY = 12;
export const TWO_DAY_PER_SEAT = 3;
export const TWO_DAY_MAX_SEATS = 1;
// Free demo: one seat, one day (matches the backend's default demo window).
export const DEMO_DAYS = 1;
export const MAX_LISTED_SEATS = 50;
export const ANNUAL_MONTHS_PAID = 10;

// Public list prices (monthly); annual is always 10× these.
/** @type {Record<number, number>} */
export const LIST_MONTHLY = { 1: 12, 2: 19, 3: 25, 5: 35, 10: 60, 15: 80, 20: 100, 30: 145, 50: 225 };
export const LIST_SEATS = Object.keys(LIST_MONTHLY).map(Number);

export const PLANS = {
  demo: {
    id: 'demo', code: 'demo', title: 'حساب دمو', short: 'دمو',
    tagline: 'آشنایی رایگان با پلتفرم، پیش از خرید',
    aiPerSeat: 5, aiUnit: 'پرسش برای کل دوره',
  },
  pass: {
    id: 'pass', code: '2day', title: 'دسترسی ۲ روزه', short: '۲ روزه',
    tagline: 'برای آزمودن پلتفرم در کار واقعی',
    aiPerSeat: 20, aiUnit: 'پرسش برای کل دوره',
  },
  monthly: {
    id: 'monthly', code: 'monthly', title: 'اشتراک ماهانه', short: 'ماهانه',
    tagline: 'انعطاف کامل، تمدید ماه‌به‌ماه',
    aiPerSeat: 150, aiUnit: 'پرسش در ماه',
  },
  annual: {
    id: 'annual', code: 'annual', title: 'اشتراک سالانه', short: 'سالانه',
    tagline: 'دو ماه رایگان و سهمیهٔ بیشتر دستیار',
    aiPerSeat: 200, aiUnit: 'پرسش در ماه',
  },
};
export const PLAN_ORDER = ['demo', 'pass', 'monthly', 'annual'];
/** Access window each plan grants, in days (pre-fills the admin's expiry). */
export const PLAN_DAYS = { demo: DEMO_DAYS, pass: 2, monthly: 31, annual: 366 };
/** Plans sold to a single user only. */
export const SINGLE_SEAT_PLANS = ['demo', 'pass'];

/** Team multiplier on the single-seat price (graduated, 1–50 seats). */
export function teamMultiplier(seats) {
  const n = Math.max(1, Math.floor(seats));
  let m = 1;
  if (n >= 2) m += 0.6;
  if (n >= 3) m += 0.5;
  m += 0.4 * Math.max(0, Math.min(n, 10) - 3);
  m += 0.35 * Math.max(0, Math.min(n, 50) - 10);
  return m;
}

/** Monthly price for a team, in million toman (list price when listed). */
export function monthlyPrice(seats) {
  if (LIST_MONTHLY[seats] != null) return LIST_MONTHLY[seats];
  return Math.round(BASE_MONTHLY * teamMultiplier(seats));
}

/**
 * Full quote for a plan + team size.
 * custom = true above 50 seats (priced by the sales team).
 */
export function quote(planId, seats) {
  const plan = PLANS[planId] || PLANS.annual;
  const n = Math.max(1, Math.floor(seats) || 1);
  if (plan.id === 'demo') {
    return {
      plan, seats: 1, custom: false, total: 0,
      perSeat: 0, perSeatLabel: 'رایگان',
      savings: 0, ai: plan.aiPerSeat, aiPerSeat: plan.aiPerSeat,
    };
  }
  if (plan.id === 'pass') {
    const s = Math.min(n, TWO_DAY_MAX_SEATS);
    return {
      plan, seats: s, custom: false, total: TWO_DAY_PER_SEAT * s,
      perSeat: TWO_DAY_PER_SEAT, perSeatLabel: 'برای هر کاربر',
      savings: 0, ai: plan.aiPerSeat * s, aiPerSeat: plan.aiPerSeat,
    };
  }
  if (n > MAX_LISTED_SEATS) {
    return { plan, seats: n, custom: true, total: null, perSeat: null, savings: 0, aiPerSeat: plan.aiPerSeat, ai: plan.aiPerSeat * n };
  }
  const month = monthlyPrice(n);
  if (plan.id === 'monthly') {
    return {
      plan, seats: n, custom: false, total: month,
      perSeat: month / n, perSeatLabel: 'برای هر کاربر در ماه',
      savings: 0, ai: plan.aiPerSeat * n, aiPerSeat: plan.aiPerSeat,
    };
  }
  const year = month * ANNUAL_MONTHS_PAID;
  return {
    plan, seats: n, custom: false, total: year,
    perSeat: year / 12 / n, perSeatLabel: 'برای هر کاربر در ماه',
    savings: month * 12 - year, monthlyEquivalent: year / 12,
    ai: plan.aiPerSeat * n, aiPerSeat: plan.aiPerSeat,
  };
}

// ---- formatting (Persian digits; codes never pass through here) ----------
const nf = (max) => new Intl.NumberFormat('fa-IR', { maximumFractionDigits: max });

/** 60 → «۶۰»; 1450 → «۱٬۴۵۰»; 7.916 → «۷٫۹». */
export function faNum(n, maxFraction = 0) {
  return nf(maxFraction).format(n);
}

/** Amount in million toman → «۶۰ میلیون تومان» (one decimal below 10M). */
export function faMillion(n, { unit = true } = {}) {
  const v = n < 10 ? faNum(Math.round(n * 10) / 10, 1) : faNum(Math.round(n));
  return unit ? `${v} میلیون تومان` : v;
}

/** Persian/Arabic digits → Latin, for phone numbers and IDs typed on fa keyboards. */
export function latinDigits(s) {
  return String(s || '')
    .replace(/[۰-۹]/g, (d) => String('۰۱۲۳۴۵۶۷۸۹'.indexOf(d)))
    .replace(/[٠-٩]/g, (d) => String('٠١٢٣٤٥٦٧٨٩'.indexOf(d)));
}

// ---- request encoding ------------------------------------------------------
// Until the order backend exists, a plan request rides the existing
// /api/purchase-request/ contract: brand marks it as a plan request, model
// carries the plan title, year the plan code. The admin card recognises the
// marker and re-derives the quote from (code, seats).
export const PLAN_REQUEST_BRAND = 'همهٔ خودروها';

export function isPlanRequest(r) {
  return r?.brand === PLAN_REQUEST_BRAND && ['demo', '2day', 'monthly', 'annual', 'custom'].includes(r?.year);
}

export function planIdFromCode(code) {
  return code === 'demo' ? 'demo' : code === '2day' ? 'pass' : code === 'monthly' ? 'monthly' : 'annual';
}

/**
 * Initial plan/seats from the page URL (?plan=annual&seats=5). Runs on the
 * server so the first render already shows the linked quote.
 * @param {Record<string, string | string[] | undefined>} sp
 * @returns {{ plan: 'demo' | 'pass' | 'monthly' | 'annual', seats: number }}
 */
export function initialSelection(sp) {
  const raw = (k) => (Array.isArray(sp[k]) ? sp[k][0] : sp[k]) || '';
  const plan = PLAN_ORDER.includes(raw('plan')) ? raw('plan') : 'annual';
  const n = Math.min(1000, Math.max(1, parseInt(raw('seats') || '1', 10) || 1));
  return { plan, seats: SINGLE_SEAT_PLANS.includes(plan) ? 1 : n };
}
