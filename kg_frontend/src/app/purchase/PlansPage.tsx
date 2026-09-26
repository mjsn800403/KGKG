'use client';

// Public plans & ordering page. The customer picks a duration and a team size,
// sees the estimated price live, and files a request that lands in the admin
// panel's «درخواست‌های خرید» list. Payment is handled offline for now (invoice
// + bank transfer); the online gateway is announced as coming later.
import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { AnimatePresence, motion, MotionConfig } from 'motion/react';
import Icon from '@/components/Icon';
import { submitPurchaseRequest } from '@/utils/api';
import {
  PLANS, PLAN_ORDER, LIST_SEATS, LIST_MONTHLY, TWO_DAY_PER_SEAT, DEMO_DAYS, SINGLE_SEAT_PLANS,
  MAX_LISTED_SEATS, PLAN_REQUEST_BRAND, quote, monthlyPrice, faNum, faMillion, latinDigits,
} from '@/lib/pricing';
import { MANUAL_CONFIGS_FLOOR, fa } from '../landing-data';
import { Wordmark, HelpButton, ThemeButton, LoginButton, Footer } from '../lp-shared';
import '../landing.css';
import './plans.css';

type PlanId = 'demo' | 'pass' | 'monthly' | 'annual';
const singleSeat = (p: PlanId) => SINGLE_SEAT_PLANS.includes(p);
type Quote = ReturnType<typeof quote>;

const EASE = [0.22, 1, 0.36, 1] as const;
const SEAT_CHIPS = [1, 2, 3, 5, 10, 20, 50];
const MAX_SEATS = 1000;
const ALL_DOCUMENTS = ['manual', 'parts', 'standard_time', 'special_tools', 'full_spec'];

const INCLUDED = [
  { icon: 'car', t: 'همهٔ خودروهای پلتفرم', d: `بیش از ${fa(MANUAL_CONFIGS_FLOOR)} پیکربندی خودرو امروز، و هر خودرویی که بعداً اضافه شود — بدون هزینهٔ جداگانه.` },
  { icon: 'manual', t: 'منوال تعمیر و عیب‌یابی', d: 'رویه‌های گام‌به‌گام تعمیر، کدهای خطا، گشتاورها و هشدارهای ایمنی کارخانه.' },
  { icon: 'wiring', t: 'نقشهٔ سیم‌کشی و مشخصات فنی', d: 'نقشه‌های الکتریکی، ظرفیت روغن‌ها و مایعات و مشخصات هر خودرو.' },
  { icon: 'clock', t: 'زمان استاندارد و ابزار مخصوص', d: 'زمان استاندارد هر کار تعمیری و فهرست ابزار مخصوص (SST) هر خودرو.' },
  { icon: 'parts', t: 'کاتالوگ قطعات', d: 'شماره‌فنی قطعات اصلی با نقشه‌های انفجاری، برای خودروهایی که کاتالوگ دارند.' },
  { icon: 'bot', t: 'دستیار هوشمند', d: 'پرسش فارسی، پاسخ مستند به منوال همان خودرو — با سهمیهٔ ماهانهٔ پرسش برای هر کاربر.' },
  { icon: 'users', t: 'مدیریت تیم و گزارش', d: 'نمودار سازمانی، دعوت اعضا، صندوق درخواست‌ها و گزارش استفادهٔ تیم.' },
];

const STEPS = [
  { t: 'انتخاب پلن و ثبت درخواست', d: 'مدت اشتراک و تعداد کاربران را انتخاب و درخواست را ثبت می‌کنید.' },
  { t: 'تماس کارشناس و پیش‌فاکتور', d: 'کارشناس فروش با شما تماس می‌گیرد و پیش‌فاکتور نهایی را ارسال می‌کند.' },
  { t: 'پرداخت', d: 'مبلغ از طریق انتقال بانکی (شبا) به حساب شرکت پرداخت می‌شود.' },
  { t: 'فعال‌سازی دسترسی', d: 'حساب‌های کاربری صادر می‌شود و تیم شما وارد پورتال می‌شود.' },
];

const FAQ = [
  { q: 'قیمت‌های این صفحه نهایی است؟', a: 'قیمت‌ها برآورد رسمی ما برای هر پلن است. مبلغ نهایی، به‌همراه جزئیات پرداخت، در پیش‌فاکتوری که کارشناس فروش برایتان ارسال می‌کند اعلام می‌شود.' },
  { q: 'اشتراک شامل کدام خودروها می‌شود؟', a: 'همهٔ خودروها و همهٔ لایه‌های مستند موجود در پلتفرم؛ خودروهایی که در طول اشتراک اضافه می‌شوند نیز بدون هزینهٔ اضافه در دسترس شما قرار می‌گیرند.' },
  { q: 'سهمیهٔ دستیار هوشمند چطور کار می‌کند؟', a: 'هر کاربر در اشتراک ماهانه ۱۵۰ و در اشتراک سالانه ۲۰۰ پرسش در ماه دارد؛ دسترسی ۲ روزه ۲۰ پرسش و حساب دمو ۵ پرسش دارد. سهمیهٔ کاربران یک شرکت با هم جمع می‌شود. اگر سهمیه تمام شود فقط دستیار متوقف می‌شود و دسترسی به مستندات ادامه دارد؛ برای سهمیهٔ بیشتر کافی است از پورتال درخواست ثبت کنید.' },
  { q: 'حساب دمو چیست؟', a: 'یک حساب رایگان ۱ روزه برای یک نفر، تا پیش از خرید با پلتفرم و مستندات آن آشنا شوید. درخواست دمو پس از بررسی کارشناس فعال می‌شود و برای هر شماره موبایل فقط یک حساب صادر می‌شود.' },
  { q: 'دسترسی ۲ روزه برای چه کسانی است؟', a: 'برای تعمیرکارانی که می‌خواهند پیش از خرید اشتراک، پلتفرم را در کار واقعی بیازمایند. اگر ظرف ۷ روز پس از آن اشتراک ماهانه یا سالانه بخرید، مبلغ دسترسی ۲ روزه از قیمت اشتراک کسر می‌شود.' },
  { q: 'بعداً می‌توانم کاربر اضافه کنم؟', a: 'بله. مدیر شرکت از پورتال درخواست افزایش ظرفیت کاربران را ثبت می‌کند و قیمت هر کاربر اضافه بر اساس همین جدول محاسبه می‌شود.' },
  { q: 'تیم ما بیش از ۵۰ نفر است.', a: 'برای تیم‌های بزرگ‌تر از ۵۰ نفر و شبکه‌های نمایندگی، قیمت سازمانی جداگانه ارائه می‌شود. در فرم، تعداد کاربران را وارد کنید تا کارشناس ما با شما تماس بگیرد.' },
  { q: 'پرداخت آنلاین امکان‌پذیر است؟', a: 'در حال حاضر پرداخت از طریق انتقال بانکی (شبا) و بر اساس پیش‌فاکتور انجام می‌شود. درگاه پرداخت آنلاین به‌زودی اضافه می‌شود.' },
];

/* ---------------------------------------------------------------- helpers */

/** Price of the next seat for the current team size (monthly, million toman). */
function nextSeatPrice(seats: number) {
  if (seats >= MAX_LISTED_SEATS) return null;
  return monthlyPrice(seats + 1) - monthlyPrice(seats);
}

function Price({ value, big = false }: { value: number | null; big?: boolean }) {
  // Cross-fade the figure when it changes so the eye catches the update.
  const text = value == null ? 'قیمت سازمانی' : value === 0 ? 'رایگان' : faMillion(value, { unit: false });
  return (
    <span className={`pl-price${big ? ' pl-price-big' : ''}`}>
      <AnimatePresence mode="popLayout" initial={false}>
        <motion.span
          key={text}
          className="pl-price-v"
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -8 }}
          transition={{ duration: 0.22, ease: EASE }}
        >
          {text}
        </motion.span>
      </AnimatePresence>
      {value != null && value !== 0 && <span className="pl-price-u">میلیون تومان</span>}
    </span>
  );
}

/* ------------------------------------------------------------ plan cards */

function PlanCards({ plan, onPlan }: { plan: PlanId; onPlan: (p: PlanId) => void }) {
  const name = useId();
  const cards = [
    {
      id: 'demo' as PlanId, badge: null,
      from: 'رایگان', fromUnit: `${fa(DEMO_DAYS)} روز`,
      facts: ['فقط ۱ کاربر', `${fa(PLANS.demo.aiPerSeat)} پرسش دستیار`, 'پس از تأیید کارشناس فعال می‌شود'],
    },
    {
      id: 'pass' as PlanId, badge: null,
      from: `${faMillion(TWO_DAY_PER_SEAT)}`, fromUnit: 'برای ۲ روز',
      facts: ['فقط ۱ کاربر', `هر کاربر: ${fa(PLANS.pass.aiPerSeat)} پرسش دستیار`, 'قابل کسر از خرید اشتراک'],
    },
    {
      id: 'monthly' as PlanId, badge: null,
      from: `از ${faMillion(LIST_MONTHLY[1])}`, fromUnit: 'در ماه',
      facts: ['تمدید ماه‌به‌ماه', `هر کاربر: ${fa(PLANS.monthly.aiPerSeat)} پرسش دستیار در ماه`, 'افزودن کاربر در هر زمان'],
    },
    {
      id: 'annual' as PlanId, badge: '۲ ماه رایگان',
      from: `از ${faMillion(LIST_MONTHLY[1] * 10)}`, fromUnit: 'در سال',
      facts: ['پرداخت ۱۰ ماه، استفادهٔ ۱۲ ماه', `هر کاربر: ${fa(PLANS.annual.aiPerSeat)} پرسش دستیار در ماه`, 'پیشنهاد ما برای تعمیرگاه‌ها'],
    },
  ];
  return (
    <fieldset className="pl-plans">
      <legend className="lp-visually-hidden">مدت دسترسی</legend>
      {cards.map((c) => {
        const p = PLANS[c.id];
        const on = plan === c.id;
        return (
          <label key={c.id} className={`pl-plan${on ? ' is-on' : ''}${c.id === 'annual' ? ' is-featured' : ''}`}>
            <input type="radio" name={name} value={c.id} checked={on} onChange={() => onPlan(c.id)} className="pl-radio" />
            <span className="pl-plan-top">
              <span className="pl-plan-check" aria-hidden="true"><Icon name="check" /></span>
              <span className="pl-plan-title">{p.title}</span>
              {c.badge && <span className="pl-badge">{c.badge}</span>}
            </span>
            <span className="pl-plan-tag">{p.tagline}</span>
            <span className="pl-plan-from"><b>{c.from}</b><small>{c.fromUnit}</small></span>
            <span className="pl-plan-facts">
              {c.facts.map((f) => <span key={f}><Icon name="check" />{f}</span>)}
            </span>
          </label>
        );
      })}
    </fieldset>
  );
}

/* ---------------------------------------------------------- seat picker */

function SeatPicker({ plan, seats, onSeats }: { plan: PlanId; seats: number; onSeats: (n: number) => void }) {
  const max = singleSeat(plan) ? 1 : MAX_SEATS;
  // A draft exists only while the number is being typed; otherwise the field
  // mirrors the committed team size.
  const [draft, setDraft] = useState<string | null>(null);
  const commit = (raw: string) => {
    const n = parseInt(latinDigits(raw), 10);
    onSeats(Number.isFinite(n) ? Math.min(max, Math.max(1, n)) : seats);
    setDraft(null);
  };
  const next = singleSeat(plan) ? null : nextSeatPrice(seats);
  return (
    <div className="pl-seats">
      <div className="pl-stepper" role="group" aria-label="تعداد کاربران">
        <button type="button" className="pl-step-btn" onClick={() => onSeats(Math.min(max, seats + 1))} disabled={seats >= max} aria-label="افزودن یک کاربر">+</button>
        <label className="pl-step-field">
          <span className="lp-visually-hidden">تعداد کاربران</span>
          <input
            inputMode="numeric" value={fa(draft ?? String(seats))} dir="ltr"
            onFocus={(e) => { setDraft(String(seats)); e.target.select(); }}
            onChange={(e) => setDraft(latinDigits(e.target.value).replace(/\D/g, '').slice(0, 4))}
            onBlur={(e) => commit(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); commit((e.target as HTMLInputElement).value); } }}
          />
          <small>کاربر</small>
        </label>
        <button type="button" className="pl-step-btn" onClick={() => onSeats(Math.max(1, seats - 1))} disabled={seats <= 1} aria-label="کم کردن یک کاربر">−</button>
      </div>
      <div className="pl-chips" role="group" aria-label="انتخاب سریع تعداد کاربران">
        {SEAT_CHIPS.map((n) => (
          <button
            key={n} type="button"
            className={`pl-chip${seats === n ? ' is-on' : ''}`}
            onClick={() => onSeats(n)}
            disabled={n > max}
            aria-pressed={seats === n}
          >
            {fa(n)}
          </button>
        ))}
        <button
          type="button"
          className={`pl-chip pl-chip-wide${seats > MAX_LISTED_SEATS ? ' is-on' : ''}`}
          onClick={() => onSeats(Math.max(seats, MAX_LISTED_SEATS + 1))}
          disabled={singleSeat(plan)}
          aria-pressed={seats > MAX_LISTED_SEATS}
        >
          بیش از {fa(MAX_LISTED_SEATS)}
        </button>
      </div>
      <p className="pl-hint" aria-live="polite">
        {singleSeat(plan) && <>{PLANS[plan].title} فقط برای ۱ کاربر است.</>}
        {!singleSeat(plan) && seats > MAX_LISTED_SEATS && <>برای بیش از {fa(MAX_LISTED_SEATS)} کاربر، کارشناس ما قیمت سازمانی را اعلام می‌کند.</>}
        {!singleSeat(plan) && seats <= MAX_LISTED_SEATS && next != null && (
          <>هر کاربر بعدی: <b>{faMillion(next)}</b> در ماه{plan === 'annual' ? ' (پیش از تخفیف سالانه)' : ''} — هرچه تیم بزرگ‌تر، سهم هر نفر کمتر.</>
        )}
        {!singleSeat(plan) && seats === MAX_LISTED_SEATS && <>بزرگ‌ترین تیم با قیمت ثابت؛ برای تیم‌های بزرگ‌تر قیمت سازمانی اعلام می‌شود.</>}
      </p>
    </div>
  );
}

/* -------------------------------------------------------------- summary */

function Summary({ q, onSubmitLabel, submitting, formId }: { q: Quote; onSubmitLabel: string; submitting: boolean; formId: string }) {
  const period = q.plan.id === 'demo' ? `برای ${fa(DEMO_DAYS)} روز` : q.plan.id === 'pass' ? 'برای ۲ روز' : q.plan.id === 'monthly' ? 'در ماه' : 'در سال';
  return (
    <div className="pl-summary">
      <div className="pl-sum-head">
        <span>برآورد هزینه</span>
        <span className="pl-sum-plan">{q.plan.title} · {fa(q.seats)} کاربر</span>
      </div>
      <div className="pl-sum-price">
        <Price value={q.custom ? null : q.total} big />
        {!q.custom && <span className="pl-sum-period">{period}</span>}
      </div>
      {q.plan.id === 'demo' ? (
        <p className="pl-sum-sub">دسترسی آزمایشی رایگان؛ پس از بررسی درخواست توسط کارشناس فعال می‌شود.</p>
      ) : q.custom ? (
        <p className="pl-sum-sub">قیمت تیم‌های بیش از {fa(MAX_LISTED_SEATS)} کاربر پس از تماس کارشناس اعلام می‌شود.</p>
      ) : (
        <p className="pl-sum-sub">
          معادل <b>{faMillion(q.perSeat as number)}</b> {q.seats === 1 ? (q.plan.id === 'pass' ? 'برای ۲ روز' : 'در ماه') : q.perSeatLabel}
        </p>
      )}
      {q.savings > 0 && (
        <div className="pl-save">
          <Icon name="sparkles" />
          <span>{faMillion(q.savings)} کمتر از پرداخت ماهانه</span>
        </div>
      )}
      <ul className="pl-sum-list">
        <li><Icon name="car" /><span>همهٔ خودروها و همهٔ لایه‌های مستند</span></li>
        <li>
          <Icon name="bot" />
          <span>
            دستیار هوشمند: {fa(q.aiPerSeat)} {q.plan.aiUnit}{q.seats > 1 ? ' برای هر کاربر' : ''}
          </span>
        </li>
        <li><Icon name="users" /><span>{q.seats > 1 ? 'مدیریت تیم، دعوت اعضا و گزارش استفاده' : 'قابل ارتقا به تیم در هر زمان'}</span></li>
      </ul>
      <button type="submit" form={formId} className="lp-btn lp-btn-primary lp-btn-lg pl-sum-cta" disabled={submitting}>
        {submitting ? 'در حال ثبت…' : onSubmitLabel}
        {!submitting && <span aria-hidden="true" className="lp-arrow">←</span>}
      </button>
      <p className="pl-fine">
        <Icon name="shield" />
        <span>ثبت درخواست تعهد پرداخت نیست. کارشناس ما تماس می‌گیرد و پیش‌فاکتور نهایی را ارسال می‌کند.</span>
      </p>
    </div>
  );
}

/* ----------------------------------------------------------------- form */

type Buyer = 'company' | 'person';
type Fields = { name: string; regNo: string; contact: string; mobile: string; landline: string; email: string; note: string; website: string };
const EMPTY: Fields = { name: '', regNo: '', contact: '', mobile: '', landline: '', email: '', note: '', website: '' };

function validate(buyer: Buyer, f: Fields) {
  const e: Partial<Record<keyof Fields, string>> = {};
  const mobile = latinDigits(f.mobile).replace(/[\s-]/g, '');
  const landline = latinDigits(f.landline).replace(/[\s-]/g, '');
  const reg = latinDigits(f.regNo).trim();
  if (f.name.trim().length < 2) e.name = buyer === 'company' ? 'نام شرکت را وارد کنید.' : 'نام و نام خانوادگی را وارد کنید.';
  if (buyer === 'company' && f.contact.trim().length < 2) e.contact = 'نام شخص رابط را وارد کنید.';
  if (!/^09\d{9}$/.test(mobile)) e.mobile = 'شمارهٔ همراه ۱۱ رقمی را وارد کنید؛ مثلاً ۰۹۱۲۳۴۵۶۷۸۹.';
  if (landline && !/^0\d{9,10}$/.test(landline)) e.landline = 'تلفن ثابت را با پیش‌شماره وارد کنید؛ مثلاً ۰۲۱۹۲۰۰۱۴۰۴.';
  if (buyer === 'person' && !/^\d{10}$/.test(reg)) e.regNo = 'کد ملی ۱۰ رقمی را وارد کنید.';
  if (buyer === 'company' && !/^[0-9]{4,11}$/.test(reg)) e.regNo = 'شناسهٔ ملی یا شمارهٔ ثبت شرکت را وارد کنید.';
  if (f.email.trim() && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(f.email.trim())) e.email = 'ایمیل معتبر نیست.';
  return e;
}

function Field({
  id, label, hint, error, required, children,
}: { id: string; label: string; hint?: string; error?: string; required?: boolean; children: React.ReactNode }) {
  return (
    <div className={`pl-field${error ? ' has-error' : ''}`}>
      <label htmlFor={id}>
        {label}
        {required ? <span className="pl-req" aria-hidden="true">*</span> : <span className="pl-opt">اختیاری</span>}
      </label>
      {children}
      {error ? <span className="pl-err" id={`${id}-err`} role="alert">{error}</span> : hint ? <span className="pl-help">{hint}</span> : null}
    </div>
  );
}

/* --------------------------------------------------------------- dialog */

function SuccessDialog({ open, onClose, data }: { open: boolean; onClose: () => void; data: { id?: number; q: Quote; mobile: string } | null }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return undefined;
    const prev = document.activeElement as HTMLElement | null;
    const t = window.setTimeout(() => ref.current?.querySelector<HTMLElement>('[data-autofocus]')?.focus(), 60);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
      if (e.key === 'Tab' && ref.current) {
        const els = [...ref.current.querySelectorAll<HTMLElement>('a[href],button')];
        const first = els[0], last = els[els.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener('keydown', onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { window.clearTimeout(t); document.removeEventListener('keydown', onKey); document.body.style.overflow = overflow; prev?.focus(); };
  }, [open, onClose]);

  return (
    <AnimatePresence>
      {open && data && (
        <motion.div className="pl-dialog-scrim" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.2 }} onClick={onClose}>
          <motion.div
            ref={ref}
            className="pl-dialog" role="dialog" aria-modal="true" aria-labelledby="pl-ok-title" aria-describedby="pl-ok-desc"
            initial={{ opacity: 0, y: 18, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 10, scale: 0.98 }}
            transition={{ duration: 0.32, ease: EASE }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="pl-ok-mark" aria-hidden="true">
              <svg viewBox="0 0 52 52">
                <motion.circle cx="26" cy="26" r="24" initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.5, ease: EASE }} />
                <motion.path d="M15 27 l7 7 l15 -16" initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.35, ease: EASE, delay: 0.35 }} />
              </svg>
            </div>
            <h2 id="pl-ok-title">درخواست شما با موفقیت ثبت شد</h2>
            <p id="pl-ok-desc" className="pl-ok-lead">
              درخواست در سامانهٔ ما ثبت و برای کارشناس فروش ارسال شد. کارشناس ما ظرف ۱ تا ۲ روز کاری با شمارهٔ{' '}
              <bdi dir="ltr" className="lp-code">{data.mobile}</bdi> تماس می‌گیرد و پیش‌فاکتور را ارسال می‌کند.
            </p>
            <dl className="pl-ok-card">
              {data.id != null && (
                <div className="pl-ok-ref"><dt>شمارهٔ پیگیری</dt><dd><bdi dir="ltr" className="lp-code">#{data.id}</bdi></dd></div>
              )}
              <div><dt>پلن</dt><dd>{data.q.plan.title}</dd></div>
              <div><dt>تعداد کاربران</dt><dd>{fa(data.q.seats)} کاربر</dd></div>
              <div><dt>برآورد هزینه</dt><dd>{data.q.custom ? 'قیمت سازمانی' : data.q.total === 0 ? 'رایگان' : faMillion(data.q.total as number)}</dd></div>
            </dl>
            <ol className="pl-ok-next" aria-label="مراحل بعدی">
              <li className="is-done"><span>{fa(1)}</span>ثبت درخواست</li>
              <li><span>{fa(2)}</span>تماس و پیش‌فاکتور</li>
              <li><span>{fa(3)}</span>پرداخت</li>
              <li><span>{fa(4)}</span>فعال‌سازی</li>
            </ol>
            <div className="pl-ok-actions">
              <button type="button" className="lp-btn lp-btn-primary lp-btn-lg" onClick={onClose} data-autofocus>متوجه شدم</button>
              <Link className="lp-btn lp-btn-outline lp-btn-lg" href="/">بازگشت به صفحهٔ اصلی</Link>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

/* ----------------------------------------------------------------- page */

export default function PlansPage({ initialPlan = 'annual', initialSeats = 1 }: { initialPlan?: PlanId; initialSeats?: number }) {
  const [plan, setPlan] = useState<PlanId>(initialPlan);
  const [seats, setSeats] = useState(initialSeats);
  const [buyer, setBuyerState] = useState<Buyer>('company');
  const [f, setF] = useState<Fields>(EMPTY);
  const [errors, setErrors] = useState<Partial<Record<keyof Fields, string>>>({});
  const [touched, setTouched] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [serverError, setServerError] = useState('');
  const [done, setDone] = useState<{ id?: number; q: Quote; mobile: string } | null>(null);
  const [scrolled, setScrolled] = useState(false);
  const [dockOn, setDockOn] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);
  const summaryRef = useRef<HTMLDivElement>(null);
  const formId = 'pl-order';

  // Plan and team size live in the URL so a quote can be shared or linked.
  useEffect(() => {
    const url = new URL(window.location.href);
    url.searchParams.set('plan', plan);
    url.searchParams.set('seats', String(seats));
    window.history.replaceState(null, '', url);
  }, [plan, seats]);

  useEffect(() => {
    const on = () => setScrolled(window.scrollY > 8);
    on();
    window.addEventListener('scroll', on, { passive: true });
    return () => window.removeEventListener('scroll', on);
  }, []);

  // Mobile price bar: shown only while neither the summary card nor the
  // buyer form (which has its own submit button) is on screen.
  useEffect(() => {
    const targets = [summaryRef.current, formRef.current].filter(Boolean) as Element[];
    if (!targets.length) return undefined;
    const visible = new Set<Element>();
    const io = new IntersectionObserver((entries) => {
      entries.forEach((e) => (e.isIntersecting ? visible.add(e.target) : visible.delete(e.target)));
      setDockOn(visible.size === 0);
    }, { threshold: 0 });
    targets.forEach((t) => io.observe(t));
    return () => io.disconnect();
  }, []);

  const q = useMemo(() => quote(plan, seats), [plan, seats]);

  const choosePlan = useCallback((p: PlanId) => {
    setPlan(p);
    if (singleSeat(p)) setSeats(1);
  }, []);

  const set = (k: keyof Fields) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const v = e.target.value;
    setF((prev) => {
      const next = { ...prev, [k]: v };
      if (touched) setErrors(validate(buyer, next));
      return next;
    });
  };

  const setBuyer = (b: Buyer) => {
    setBuyerState(b);
    if (touched) setErrors(validate(b, f));
  };

  const pickFromTable = (n: number) => {
    setSeats(n);
    if (singleSeat(plan)) setPlan('annual');
    document.getElementById('configure')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (submitting) return;
    setTouched(true);
    setServerError('');
    const errs = validate(buyer, f);
    setErrors(errs);
    const firstBad = Object.keys(errs)[0];
    if (firstBad) {
      const el = document.getElementById(`pl-${firstBad}`);
      el?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      window.setTimeout(() => (el as HTMLInputElement | null)?.focus({ preventScroll: true }), 350);
      return;
    }
    if (f.website) return; // honeypot: bots fill every field

    const mobile = latinDigits(f.mobile).replace(/[\s-]/g, '');
    const landline = latinDigits(f.landline).replace(/[\s-]/g, '');
    const priceLine = q.custom
      ? 'برآورد قیمت: قیمت سازمانی (بیش از ۵۰ کاربر)'
      : q.plan.id === 'demo' ? 'برآورد قیمت: رایگان (حساب دمو)'
      : `برآورد قیمت نمایش‌داده‌شده به مشتری: ${faMillion(q.total as number)} (${q.plan.id === 'pass' ? 'برای ۲ روز' : q.plan.id === 'monthly' ? 'ماهانه' : 'سالانه'})`;
    const note = [
      `پلن: ${q.plan.title} · ${fa(q.seats)} کاربر`,
      priceLine,
      `سهمیهٔ دستیار: ${fa(q.aiPerSeat)} ${q.plan.aiUnit} برای هر کاربر`,
      `نوع خریدار: ${buyer === 'company' ? 'حقوقی (شرکت)' : 'حقیقی (شخص)'}`,
      buyer === 'company' && f.contact.trim() ? `شخص رابط: ${f.contact.trim()}` : '',
      f.email.trim() ? `ایمیل: ${f.email.trim()}` : '',
      landline ? '' : 'تلفن ثابت: اعلام نشده',
      f.note.trim() ? `توضیحات مشتری: ${f.note.trim()}` : '',
    ].filter(Boolean).join('\n');

    setSubmitting(true);
    try {
      const res = await submitPurchaseRequest({
        brand: PLAN_REQUEST_BRAND,
        model: `${q.plan.title} — ${fa(q.seats)} کاربر`,
        year: q.plan.code,
        documents: ALL_DOCUMENTS,
        company: f.name.trim(),
        landline: landline || mobile,
        mobile,
        reg_no: latinDigits(f.regNo).trim(),
        note,
        employees_count: q.seats,
        seats_count: q.seats,
        seat_plan: q.seats === 1
          ? [{ role: 'after_sales_manager', count: 1 }]
          : [{ role: 'after_sales_manager', count: 1 }, { role: 'after_sales_specialist', count: q.seats - 1 }],
        wants_demo: q.plan.id === 'demo',
        wants_ai_assistant: true,
      });
      setDone({ id: res?.id, q, mobile });
      setF(EMPTY);
      setTouched(false);
      setErrors({});
    } catch (err) {
      setServerError((err as Error)?.message || 'ثبت درخواست ناموفق بود. لطفاً دوباره تلاش کنید.');
    } finally {
      setSubmitting(false);
    }
  }

  const submitLabel = q.plan.id === 'demo' ? 'درخواست حساب دمو' : q.custom ? 'درخواست قیمت سازمانی' : 'ثبت درخواست خرید';
  const errProps = (k: keyof Fields) => ({
    id: `pl-${k}`,
    'aria-invalid': errors[k] ? true : undefined,
    'aria-describedby': errors[k] ? `pl-${k}-err` : undefined,
  });

  return (
    <MotionConfig reducedMotion="user">
      <div className="lp pl-page" id="plans-page">
        <a className="lp-skip" href="#configure">رفتن به انتخاب پلن</a>

        <header className={`lp-header${scrolled ? ' is-scrolled' : ''}`}>
          <div className="lp-header-in">
            <Wordmark />
            <nav className="lp-nav" aria-label="بخش‌های صفحه">
              <Link href="/">صفحهٔ اصلی</Link>
              <a href="#configure">انتخاب پلن</a>
              <a href="#table">جدول قیمت</a>
              <a href="#process">روند خرید</a>
              <a href="#faq">پرسش‌ها</a>
            </nav>
            <div className="lp-header-actions">
              <HelpButton />
              <ThemeButton />
              <LoginButton />
            </div>
          </div>
        </header>

        <main id="main">
          {/* ---- hero ---- */}
          <section className="pl-hero" aria-labelledby="pl-title">
            <div className="pl-hero-grid" aria-hidden="true" />
            <div className="lp-wrap">
              <motion.p className="lp-eyebrow" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4, ease: EASE }}>
                پلن‌ها و قیمت
              </motion.p>
              <motion.h1 id="pl-title" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.45, ease: EASE, delay: 0.04 }}>
                یک اشتراک، <em>همهٔ خودروها</em>.
              </motion.h1>
              <motion.p className="pl-hero-lead" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.45, ease: EASE, delay: 0.08 }}>
                همهٔ منوال‌های تعمیر، نقشه‌های سیم‌کشی، زمان‌های استاندارد، ابزار مخصوص و کاتالوگ قطعات — همراه با دستیار هوشمند و مدیریت تیم. مدت و تعداد کاربران را انتخاب کنید؛ قیمت همین‌جا محاسبه می‌شود.
              </motion.p>
              <motion.ul className="pl-hero-facts" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.5, delay: 0.16 }}>
                <li><b>{fa(MANUAL_CONFIGS_FLOOR)}+</b><span>پیکربندی خودرو</span></li>
                <li><b>{fa(4)}</b><span>لایهٔ مستند فنی</span></li>
                <li><b>{fa(PLANS.annual.aiPerSeat)}</b><span>پرسش دستیار در ماه، برای هر کاربر</span></li>
              </motion.ul>
            </div>
          </section>

          {/* ---- configurator ---- */}
          <section id="configure" className="pl-config" aria-label="انتخاب پلن و ثبت درخواست">
            <div className="lp-wrap pl-config-grid">
              <div className="pl-steps">
                <div className="pl-block">
                  <div className="pl-block-head">
                    <span className="pl-num">{fa(1)}</span>
                    <div>
                      <h2>مدت دسترسی</h2>
                      <p>همهٔ پلن‌ها به همهٔ خودروها و مستندات دسترسی دارند؛ تفاوت در مدت و سهمیهٔ دستیار است.</p>
                    </div>
                  </div>
                  <PlanCards plan={plan} onPlan={choosePlan} />
                </div>

                <div className="pl-block">
                  <div className="pl-block-head">
                    <span className="pl-num">{fa(2)}</span>
                    <div>
                      <h2>تعداد کاربران</h2>
                      <p>هر کاربر حساب ورود جداگانه دارد. با بزرگ‌تر شدن تیم، سهم هر نفر کاهش می‌یابد.</p>
                    </div>
                  </div>
                  <SeatPicker plan={plan} seats={seats} onSeats={setSeats} />
                </div>

                <form id={formId} ref={formRef} className="pl-block" onSubmit={submit} noValidate>
                  <div className="pl-block-head">
                    <span className="pl-num">{fa(3)}</span>
                    <div>
                      <h2>مشخصات خریدار</h2>
                      <p>برای تماس و صدور پیش‌فاکتور. اطلاعات شما فقط برای پیگیری همین درخواست استفاده می‌شود.</p>
                    </div>
                  </div>

                  <div className="pl-seg" role="radiogroup" aria-label="نوع خریدار">
                    {([['company', 'شرکت یا سازمان'], ['person', 'شخص حقیقی']] as [Buyer, string][]).map(([id, label]) => (
                      <button
                        key={id} type="button" role="radio" aria-checked={buyer === id}
                        className={`pl-seg-btn${buyer === id ? ' is-on' : ''}`}
                        onClick={() => setBuyer(id)}
                      >
                        <Icon name={id === 'company' ? 'building' : 'user'} />{label}
                      </button>
                    ))}
                  </div>

                  <div className="pl-fields">
                    <Field id="pl-name" label={buyer === 'company' ? 'نام شرکت' : 'نام و نام خانوادگی'} required error={errors.name}>
                      <input {...errProps('name')} value={f.name} onChange={set('name')} autoComplete={buyer === 'company' ? 'organization' : 'name'} placeholder={buyer === 'company' ? 'مثلاً خدمات فنی آریا' : ''} />
                    </Field>
                    <Field id="pl-regNo" label={buyer === 'company' ? 'شناسهٔ ملی یا شمارهٔ ثبت' : 'کد ملی'} required error={errors.regNo}>
                      <input {...errProps('regNo')} value={f.regNo} onChange={set('regNo')} inputMode="numeric" dir="ltr" placeholder={buyer === 'company' ? '10100000000' : '0012345678'} />
                    </Field>
                    {buyer === 'company' && (
                      <Field id="pl-contact" label="نام شخص رابط" required error={errors.contact}>
                        <input {...errProps('contact')} value={f.contact} onChange={set('contact')} autoComplete="name" />
                      </Field>
                    )}
                    <Field id="pl-mobile" label="تلفن همراه" required error={errors.mobile} hint="کارشناس فروش با این شماره تماس می‌گیرد.">
                      <input {...errProps('mobile')} value={f.mobile} onChange={set('mobile')} type="tel" inputMode="tel" dir="ltr" autoComplete="tel" placeholder="09xxxxxxxxx" />
                    </Field>
                    <Field id="pl-landline" label="تلفن ثابت" error={errors.landline}>
                      <input {...errProps('landline')} value={f.landline} onChange={set('landline')} type="tel" inputMode="tel" dir="ltr" placeholder="021xxxxxxxx" />
                    </Field>
                    <Field id="pl-email" label="ایمیل" error={errors.email}>
                      <input {...errProps('email')} value={f.email} onChange={set('email')} type="email" dir="ltr" autoComplete="email" placeholder="name@company.com" />
                    </Field>
                    <Field id="pl-note" label="توضیحات" hint="مثلاً خودرو یا برند خاصی که برایتان مهم است، یا زمان مناسب تماس.">
                      <textarea id="pl-note" value={f.note} onChange={set('note')} maxLength={1000} rows={3} />
                    </Field>
                    <div className="pl-hp" aria-hidden="true">
                      <label htmlFor="pl-website">وب‌سایت</label>
                      <input id="pl-website" tabIndex={-1} autoComplete="off" value={f.website} onChange={set('website')} />
                    </div>
                  </div>

                  {serverError && <div className="pl-server-err" role="alert"><Icon name="info" />{serverError}</div>}

                  <div className="pl-form-foot">
                    <button type="submit" className="lp-btn lp-btn-primary lp-btn-lg" disabled={submitting}>
                      {submitting ? 'در حال ثبت…' : submitLabel}
                      {!submitting && <span aria-hidden="true" className="lp-arrow">←</span>}
                    </button>
                    <span>پرداخت آنلاین به‌زودی؛ فعلاً پرداخت با پیش‌فاکتور و انتقال بانکی انجام می‌شود.</span>
                  </div>
                </form>
              </div>

              <aside className="pl-aside" ref={summaryRef} aria-label="خلاصهٔ سفارش">
                <Summary q={q} onSubmitLabel={submitLabel} submitting={submitting} formId={formId} />
              </aside>
            </div>
          </section>

          {/* ---- included ---- */}
          <section className="lp-sec lp-sec-alt pl-sec" aria-labelledby="pl-inc-title">
            <div className="lp-wrap">
              <header className="lp-sechead">
                <span className="lp-chapter" aria-hidden="true">در همهٔ پلن‌ها</span>
                <h2 id="pl-inc-title">هرچه پلتفرم دارد، در اشتراک شما</h2>
                <p className="lp-lead">پلن‌ها فقط در مدت و تعداد کاربران فرق دارند؛ هیچ خودرو یا لایهٔ مستندی جداگانه فروخته نمی‌شود.</p>
              </header>
              <ul className="pl-inc">
                {INCLUDED.map((it) => (
                  <li key={it.t}>
                    <span className="pl-inc-icon"><Icon name={it.icon} /></span>
                    <h3>{it.t}</h3>
                    <p>{it.d}</p>
                  </li>
                ))}
              </ul>
            </div>
          </section>

          {/* ---- price table ---- */}
          <section id="table" className="lp-sec pl-sec" aria-labelledby="pl-table-title">
            <div className="lp-wrap">
              <header className="lp-sechead">
                <span className="lp-chapter" aria-hidden="true">جدول قیمت</span>
                <h2 id="pl-table-title">قیمت برای هر اندازهٔ تیم</h2>
                <p className="lp-lead">مبالغ به میلیون تومان است. برای انتخاب، روی هر ردیف بزنید.</p>
              </header>
              <div className="pl-table-wrap">
                <table className="pl-table">
                  <caption className="lp-visually-hidden">قیمت اشتراک ماهانه و سالانه بر اساس تعداد کاربران، به میلیون تومان</caption>
                  <thead>
                    <tr>
                      <th scope="col">تعداد کاربران</th>
                      <th scope="col">ماهانه</th>
                      <th scope="col">سالانه <span className="pl-th-note">۲ ماه رایگان</span></th>
                      <th scope="col">هر کاربر در ماه <span className="pl-th-note">با اشتراک سالانه</span></th>
                      <th scope="col"><span className="lp-visually-hidden">انتخاب</span></th>
                    </tr>
                  </thead>
                  <tbody>
                    {LIST_SEATS.map((n) => {
                      const a = quote('annual', n);
                      const on = seats === n && !singleSeat(plan);
                      return (
                        <tr key={n} className={on ? 'is-on' : ''} onClick={() => pickFromTable(n)}>
                          <th scope="row">{fa(n)} {n === 1 ? 'کاربر' : 'کاربر'}</th>
                          <td>{faNum(LIST_MONTHLY[n])}</td>
                          <td>{faNum(LIST_MONTHLY[n] * 10)}</td>
                          <td className="pl-td-dim">{faMillion(a.perSeat as number, { unit: false })}</td>
                          <td className="pl-td-act">
                            <button type="button" className="pl-row-btn" onClick={(e) => { e.stopPropagation(); pickFromTable(n); }} aria-label={`انتخاب ${fa(n)} کاربر`}>
                              {on ? 'انتخاب‌شده' : 'انتخاب'}
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <div className="pl-table-notes">
                <p><b>حساب دمو:</b> رایگان، {fa(DEMO_DAYS)} روز، فقط ۱ کاربر.</p>
                <p><b>دسترسی ۲ روزه:</b> {faMillion(TWO_DAY_PER_SEAT)}، فقط ۱ کاربر.</p>
                <p><b>سایر تعدادها:</b> برای هر تعداد کاربر تا {fa(MAX_LISTED_SEATS)} نفر، قیمت در بخش انتخاب پلن محاسبه می‌شود.</p>
                <p><b>بیش از {fa(MAX_LISTED_SEATS)} کاربر:</b> قیمت سازمانی، پس از تماس کارشناس.</p>
              </div>
            </div>
          </section>

          {/* ---- process ---- */}
          <section id="process" className="lp-sec lp-sec-alt pl-sec" aria-labelledby="pl-proc-title">
            <div className="lp-wrap">
              <header className="lp-sechead">
                <span className="lp-chapter" aria-hidden="true">روند خرید</span>
                <h2 id="pl-proc-title">از درخواست تا دسترسی، در چهار مرحله</h2>
                <p className="lp-lead">فعلاً پرداخت با پیش‌فاکتور و انتقال بانکی انجام می‌شود. درگاه پرداخت آنلاین به‌زودی فعال می‌شود.</p>
              </header>
              <ol className="pl-proc">
                {STEPS.map((s, i) => (
                  <li key={s.t}>
                    <span className="pl-proc-n">{fa(`0${i + 1}`)}</span>
                    <h3>{s.t}</h3>
                    <p>{s.d}</p>
                  </li>
                ))}
              </ol>
              <div className="pl-soon"><span className="pl-soon-dot" aria-hidden="true" />پرداخت آنلاین با درگاه بانکی — به‌زودی</div>
            </div>
          </section>

          {/* ---- faq ---- */}
          <section id="faq" className="lp-sec pl-sec" aria-labelledby="pl-faq-title">
            <div className="lp-wrap pl-faq-grid">
              <header className="lp-sechead">
                <span className="lp-chapter" aria-hidden="true">پرسش‌های رایج</span>
                <h2 id="pl-faq-title">پیش از ثبت درخواست</h2>
                <p className="lp-lead">پاسخ پرسش‌تان را پیدا نکردید؟ با شمارهٔ <a className="lp-textlink" href="tel:+982192001404"><bdi dir="ltr">021 9200 1404</bdi></a> (داخلی {fa(304)}) تماس بگیرید.</p>
              </header>
              <div className="pl-faq">
                {FAQ.map((it) => (
                  <details key={it.q}>
                    <summary>{it.q}<span className="pl-faq-x" aria-hidden="true" /></summary>
                    <p>{it.a}</p>
                  </details>
                ))}
              </div>
            </div>
          </section>
        </main>

        <Footer />

        <div className={`pl-dock${dockOn ? ' is-on' : ''}`} inert={!dockOn}>
          <div className="pl-dock-price">
            <small>{q.plan.short} · {fa(q.seats)} کاربر</small>
            <b>{q.custom ? 'قیمت سازمانی' : q.total === 0 ? 'رایگان' : faMillion(q.total as number)}</b>
          </div>
          <button
            type="button" className="lp-btn lp-btn-primary"
            onClick={() => { formRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }); window.setTimeout(() => document.getElementById('pl-name')?.focus({ preventScroll: true }), 450); }}
          >
            ثبت درخواست
          </button>
        </div>

        <SuccessDialog open={!!done} data={done} onClose={() => setDone(null)} />
      </div>
    </MotionConfig>
  );
}
