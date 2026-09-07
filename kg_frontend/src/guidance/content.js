// ---------------------------------------------------------------------------
// KGtechvault — Guidance content registry (the user-facing help source of truth)
// ---------------------------------------------------------------------------
// This file is the curated, role-filtered, Persian mirror of the engineering
// documentation under /opt/KGKG/docs. Every tour and article carries a `docRef`
// pointing at the doc section it summarizes, so the two stay in step:
//
//   * When a doc section changes, grep this file for its docRef and update the
//     matching article(s)/tour(s) in the SAME commit.
//   * `scripts/check-guidance-sync.mjs` fails the check if a docRef points at a
//     doc file that no longer exists, or if a doc file was modified more
//     recently than the article's `reviewed` date (a staleness signal).
//
// Nothing here is secret: it is shipped to the browser and shown to end users,
// so it must never contain internal-only material (server internals, security
// limitations, tokens). Those live in /opt/KGKG/docs and stay maintainer-only.
//
// See docs/13-guidance-system.md for the full design.
// ---------------------------------------------------------------------------

// Effective audience roles. `analyst` = a user who can view analytics but not
// manage the team (a common capability split); `manager` implies analyst too.
export const ROLES = {
  VISITOR: 'visitor',
  USER: 'user',
  ANALYST: 'analyst',
  MANAGER: 'manager',
  ADMIN: 'admin',
};

// Resolve the viewer's audience from the app context. Kept pure so both the
// provider and the sync-checker can reuse it.
export function resolveAudience({ pathname = '', portalUser = null, isAdmin = false }) {
  if (isAdmin || pathname.startsWith('/admin')) {
    return { role: ROLES.ADMIN, caps: { manage: true, analytics: true, ai: true }, isAdmin: true };
  }
  if (!portalUser) {
    return { role: ROLES.VISITOR, caps: { manage: false, analytics: false, ai: false }, isAdmin: false };
  }
  const caps = {
    manage: !!portalUser.can_manage_team,
    analytics: !!(portalUser.can_view_analytics || portalUser.can_manage_team),
    ai: !!portalUser.ai_eligible,
  };
  let role = ROLES.USER;
  if (caps.manage) role = ROLES.MANAGER;
  else if (caps.analytics) role = ROLES.ANALYST;
  return { role, caps, isAdmin: false };
}

// Does the viewer belong to a content item's audience? An item is visible when
// its `roles` list includes the viewer's role, OR when it declares a `cap`
// requirement the viewer satisfies (so analytics help reaches every analytics
// viewer regardless of their headline role).
export function audienceMatches(item, audience) {
  const roles = item.roles || [];
  if (roles.includes(audience.role)) return true;
  if (item.cap && audience.caps && audience.caps[item.cap]) return true;
  return false;
}

// Help-center article categories (grouping + ordering in the panel).
export const CATEGORIES = [
  { id: 'start', label: 'شروع کار' },
  { id: 'browse', label: 'مرور مستندات' },
  { id: 'assistant', label: 'دستیار هوشمند' },
  { id: 'team', label: 'مدیریت تیم' },
  { id: 'analytics', label: 'تحلیل و گزارش' },
  { id: 'requests', label: 'درخواست‌ها' },
  { id: 'account', label: 'حساب و تنظیمات' },
  { id: 'admin', label: 'مدیریت پلتفرم' },
  { id: 'admin-ops', label: 'داده و عملیات' },
];

// ---------------------------------------------------------------------------
// TOURS — role-based guided walkthroughs (spotlight steps).
// Each step targets a CSS selector present on the surface. `place` hints the
// tooltip side ('auto' by default). A tour auto-starts once per role when the
// viewer first lands on a matching `autoRoute`; it can always be replayed from
// the help panel or settings.
// ---------------------------------------------------------------------------
export const TOURS = [
  {
    id: 'visitor-landing',
    roles: [ROLES.VISITOR],
    autoRoute: (p) => p === '/',
    route: '/',
    title: 'آشنایی با سامانه',
    docRef: 'docs/01-overview.md#core-user-flows',
    steps: [
      { sel: '[data-tour="login-btn"], [data-guide="login-btn"]', title: 'خوش آمدید 👋',
        body: 'به KGtechvault خوش آمدید — سامانهٔ مستندات فنی خودرو. از اینجا وارد حساب کاربری شرکت خود می‌شوید.' },
      { sel: '[data-tour="doc-layers"], [data-guide="doc-layers"]', title: 'چهار لایهٔ مستند',
        body: 'برای هر خودرو چهار نوع مستند داریم: فهرست قطعات، منوال تعمیر، زمان استاندارد و ابزار مخصوص. اشتراک شما تعیین می‌کند کدام‌ها در دسترس‌اند.' },
      { sel: '[data-tour="vin-box"], [data-guide="vin-box"]', title: 'بررسی پوشش خودرو',
        body: 'شمارهٔ شاسی (VIN) خودرو را وارد کنید تا ببینید چه مستنداتی برای آن موجود است.' },
      { sel: '[data-tour="support"], [data-guide="support"]', title: 'پشتیبانی و خرید',
        body: 'برای تهیهٔ مستندات یک خودرو یا تماس با کارشناسان، از فرم «سفارش / خرید» و راه‌های تماس پایین صفحه استفاده کنید.' },
    ],
  },
  {
    id: 'user-browse',
    roles: [ROLES.USER, ROLES.ANALYST, ROLES.MANAGER],
    autoRoute: (p) => p.startsWith('/browse'),
    route: '/browse',
    title: 'راهنمای پورتال',
    docRef: 'docs/01-overview.md#browsing-content-portal-user',
    steps: [
      { sel: '[data-tour="nav-fleet"], [data-guide="nav-fleet"]', title: 'خودروهای فعال',
        body: 'فهرست خودروهایی که مستندات آن‌ها برای شما فعال است. روی هر خودرو کلیک کنید تا وارد مستنداتش شوید.' },
      { sel: '[data-tour="model-filter"], [data-guide="model-filter"]', title: 'فیلتر خودروها',
        body: 'خودروها را بر اساس برند، سال ساخت و مدل محدود کنید — مثلاً همهٔ Land Cruiser های ۲۰۲۵. کادر جستجو هم برای پیدا کردن سریع یک نام مشخص است، و عدد کنار هر گزینه می‌گوید با انتخاب آن چند خودرو باقی می‌ماند.' },
      { sel: '[data-guide="recs"]', title: 'پیشنهادهای شخصی',
        body: 'بر اساس فعالیت شما، بخش‌هایی برای «ادامهٔ مطالعه» و موضوعات مرتبط پیشنهاد می‌شود تا سریع‌تر به کار برسید.' },
      { sel: '[data-tour="nav-assistant"], [data-guide="nav-assistant"]', title: 'دستیار هوشمند',
        body: 'سؤال تعمیراتی یا کد خطا (DTC) دارید؟ دستیار بر اساس دفترچه‌های رسمیِ همان خودرو پاسخ می‌دهد.' },
      { sel: '[data-tour="nav-settings"], [data-guide="nav-settings"]', title: 'تنظیمات و راهنما',
        body: 'حالت روشن/تاریک، اعلان‌ها و اجرای دوبارهٔ این راهنما از بخش تنظیمات در دسترس است. دکمهٔ «؟» هم همیشه پایین صفحه هست.' },
    ],
  },
  {
    id: 'manager-team',
    roles: [ROLES.MANAGER],
    autoRoute: (p) => p === '/team' || p === '/team/',
    route: '/team',
    title: 'راهنمای مدیریت تیم',
    docRef: 'docs/06-permissions-rbac.md#66-org-hierarchy-who-manages-whom',
    steps: [
      { sel: '[data-guide="team-tabs"]', title: 'سه نمای مدیریت تیم',
        body: 'اعضا (فهرست کارکنان)، چارت سازمانی (روابط گزارش‌دهی) و نقش‌ها (تعریف جایگاه‌ها). هر تغییری بلافاصله برای بقیه هم هم‌زمان‌سازی می‌شود.' },
      { sel: '[data-guide="team-add"]', title: 'افزودن کارمند',
        body: 'کارمند جدید را با «دعوت‌نامه» (لینک ایمیل، خودش رمز می‌سازد) یا «نام کاربری و رمز» (شما رمز را تحویل می‌دهید) بسازید.' },
      { sel: '[data-guide="team-search"]', title: 'جستجو و فیلتر اعضا',
        body: 'در تیم‌های بزرگ، اعضا را با نام جستجو کنید یا با تراشه‌های نقش فیلتر کنید.' },
      { sel: '[data-guide="nav-analytics"], [data-tour="nav-analytics"]', title: 'تحلیل استفاده',
        body: 'میزان استفادهٔ تیم به تفکیک عضو و حوزهٔ فنی، به‌همراه گزارش PDF قابل دانلود.' },
      { sel: '[data-guide="nav-requests"], [data-tour="nav-requests"]', title: 'درخواست‌ها',
        body: 'برای خودرو یا ظرفیت بیشتر، فعال‌سازی دستیار یا پشتیبانی، از اینجا درخواست ثبت کنید و وضعیت آن را زنده ببینید.' },
    ],
  },
  {
    id: 'admin-hub',
    roles: [ROLES.ADMIN],
    autoRoute: (p) => p === '/admin' || p === '/admin/',
    route: '/admin',
    title: 'راهنمای پنل مدیریت',
    docRef: 'docs/07-frontend.md#74-admin-panel-appadminpagejsx-1900-lines',
    steps: [
      { sel: '[data-guide="admin-hub"]', title: 'میز مدیریت',
        body: 'نقطهٔ شروع شما. بخش‌ها در گروه‌های منطقی چیده شده‌اند تا با یک نگاه وضعیت پلتفرم را ببینید. روی هر کارت کلیک کنید تا وارد آن ابزار شوید.' },
      { sel: '[data-guide="admin-group-realtime"]', title: 'بلادرنگ',
        body: 'داشبورد زنده و صندوق درخواست‌های شرکت‌ها — رویدادها بدون رفرش به‌روز می‌شوند.' },
      { sel: '[data-guide="admin-group-customers"]', title: 'مشتریان و فروش',
        body: 'گردش کار فروش: درخواست‌های خرید ← تعریف شرکت و دامنهٔ خرید ← صدور حساب کاربران.' },
      { sel: '[data-guide="admin-group-operations"]', title: 'داده و عملیات',
        body: 'فهرست خودروها، سلامت داده‌ها، پردازش (ایندکس RAG) و پایش سرور — قلب عملیاتی پلتفرم.' },
      { sel: '.guide-fab', title: 'راهنمای همیشه‌دردسترس',
        body: 'در هر بخش که باشید، این دکمه (یا کلید ؟) راهنمای همان بخش را باز می‌کند — بدون ترک صفحه.' },
    ],
  },
];

export function autoTourFor(audience, pathname) {
  return TOURS.find((t) => audienceMatches(t, audience) && t.autoRoute(pathname)) || null;
}
export function tourById(id) {
  return TOURS.find((t) => t.id === id) || null;
}

// ---------------------------------------------------------------------------
// ARTICLES — the searchable, on-demand help library.
// `surfaces` tags let the help panel surface the most relevant article(s) for
// the page/section the viewer is on (context-sensitive help). `path` matches a
// route prefix; `section` matches an admin section id.
// `reviewed` is the date the copy was last checked against its docRef.
// ---------------------------------------------------------------------------
const REVIEWED = '2026-08-05';

export const ARTICLES = [
  // ---- Visitor (public pages) ---------------------------------------------
  {
    id: 'about-platform', category: 'start', roles: [ROLES.VISITOR],
    surfaces: [{ path: '/' }], tourId: 'visitor-landing', reviewed: REVIEWED,
    title: 'KGtechvault چیست؟', keywords: ['درباره', 'معرفی', 'سامانه', 'مستندات', 'خودرو'],
    summary: 'سامانهٔ مستندات فنی رسمی خودرو برای تعمیرگاه‌ها و شرکت‌های خدمات پس از فروش.',
    body: [
      'KGtechvault دسترسی به مستندات فنی رسمی خودرو (تویوتا و لکسوس) را در چهار لایه فراهم می‌کند: فهرست قطعات، منوال تعمیر، زمان استاندارد و ابزار مخصوص.',
      'هر شرکت اشتراک خود را تهیه می‌کند و برای کارکنانش دسترسی صادر می‌شود؛ سپس تکنسین‌ها می‌توانند مستندات را مرور کنند و از دستیار هوشمند برای پرسش‌های تعمیراتی کمک بگیرند.',
    ],
    docRef: 'docs/01-overview.md#what-kgtechvault-is',
  },
  {
    id: 'check-coverage', category: 'start', roles: [ROLES.VISITOR],
    surfaces: [{ path: '/' }], reviewed: REVIEWED,
    title: 'بررسی پوشش خودرو', keywords: ['پوشش', 'vin', 'شاسی', 'خودرو', 'موجود'],
    summary: 'ببینید برای خودروی شما چه مستنداتی موجود است.',
    body: [
      'در بخش «بررسی پوشش خودرو» صفحهٔ اصلی، شمارهٔ شاسی (VIN) را وارد کنید تا میزان پوشش مستندات فنی آن خودرو مشخص شود.',
      'اگر خودروی موردنظر در فهرست نبود، از راه‌های تماس پایین صفحه با کارشناسان ما در ارتباط باشید تا برای گردآوری آن اقدام شود.',
    ],
    docRef: 'docs/01-overview.md#core-user-flows',
  },
  {
    id: 'get-access', category: 'start', roles: [ROLES.VISITOR],
    surfaces: [{ path: '/' }, { path: '/purchase' }], reviewed: REVIEWED,
    title: 'چطور دسترسی بگیرم؟', keywords: ['خرید', 'سفارش', 'اشتراک', 'دسترسی', 'ثبت‌نام'],
    summary: 'روند تهیهٔ اشتراک برای شرکت شما.',
    body: [
      'برای تهیهٔ مستندات، از صفحهٔ «سفارش / خرید» درخواست خود را ثبت کنید: خودرو، لایه‌های مستند موردنیاز، مشخصات شرکت و تعداد کاربران هر نقش را وارد کنید.',
      'پس از بررسی درخواست توسط کارشناسان ما، شرکت شما تعریف و برای کارکنان حساب کاربری صادر می‌شود. سپس با نام کاربری/رمز یا لینک دعوت وارد می‌شوید.',
    ],
    docRef: 'docs/01-overview.md#core-user-flows',
  },
  {
    id: 'visitor-login', category: 'start', roles: [ROLES.VISITOR],
    surfaces: [{ path: '/' }], reviewed: REVIEWED,
    title: 'ورود به حساب کاربری', keywords: ['ورود', 'لاگین', 'حساب', 'رمز', 'دعوت'],
    summary: 'با نام کاربری یا ایمیل خود وارد شوید.',
    body: [
      'اگر شرکت شما مشترک است و برایتان حساب صادر شده، از دکمهٔ «ورود» با نام کاربری یا ایمیل و رمز خود وارد شوید.',
      'اگر با لینک دعوت آمده‌اید، ابتدا دعوت را بپذیرید و رمز خود را تعیین کنید. رمز را فراموش کرده‌اید؟ با مدیر تیم یا پشتیبانی تماس بگیرید (بازنشانی خودکار هنوز فعال نیست).',
    ],
    docRef: 'docs/06-permissions-rbac.md#61-identity-two-separate-auth-systems',
  },
  // ---- Getting started -----------------------------------------------------
  {
    id: 'welcome', category: 'start', roles: [ROLES.USER, ROLES.ANALYST, ROLES.MANAGER],
    surfaces: [{ path: '/browse' }], tourId: 'user-browse', reviewed: REVIEWED,
    title: 'شروع کار با پورتال', keywords: ['خانه', 'داشبورد', 'شروع', 'خودرو فعال'],
    summary: 'یک نمای کلی از پورتال و کارهایی که می‌توانید انجام دهید.',
    body: [
      'در صفحهٔ «خودروهای فعال»، تمام خودروهایی که شرکت شما برایتان فعال کرده نمایش داده می‌شود. روی هر خودرو بزنید تا وارد مستنداتش شوید.',
      'اگر خودرویی را انتظار دارید ولی نمی‌بینید، یعنی هنوز برای حساب شما دسترسی‌اش صادر نشده — با مدیر تیم خود در میان بگذارید.',
      'برای پرسش‌های تعمیراتی و کدهای خطا، از «دستیار هوشمند» استفاده کنید.',
    ],
    docRef: 'docs/01-overview.md#browsing-content-portal-user',
  },
  {
    id: 'nav-basics', category: 'start', roles: [ROLES.USER, ROLES.ANALYST, ROLES.MANAGER],
    surfaces: [], reviewed: REVIEWED,
    title: 'راه‌بری و منوی کناری', keywords: ['منو', 'ناوبری', 'سایدبار', 'بخش‌ها'],
    summary: 'هر آیتم منوی کناری چه کاری انجام می‌دهد.',
    body: [
      'منوی کناری بر اساس دسترسی شما نمایش داده می‌شود: «خودروهای فعال» و «دستیار هوشمند» برای همه؛ «تیم و کارکنان» و «درخواست‌ها» برای مدیران؛ «تحلیل و گزارش‌ها» برای دارندگان دسترسی تحلیل.',
      'اگر آیتمی را نمی‌بینید، یعنی دسترسی آن برای حساب شما فعال نیست.',
    ],
    docRef: 'docs/07-frontend.md#73-portal-ui-composition',
  },
  // ---- Browsing ------------------------------------------------------------
  {
    id: 'browse-tree', category: 'browse', roles: [ROLES.USER, ROLES.ANALYST, ROLES.MANAGER],
    surfaces: [{ path: '/browse' }], reviewed: REVIEWED,
    title: 'یافتن مستند درست', keywords: ['مرور', 'درخت', 'بخش', 'فیلتر مدل', 'breadcrumb'],
    summary: 'چطور در ساختار درختی منوال به بخش مورد نظر برسید.',
    body: [
      'مستندات هر خودرو به‌صورت درختی سازمان‌دهی شده‌اند؛ با کلیک روی هر بخش یک لایه پایین‌تر می‌روید و مسیر بالای صفحه (breadcrumb) جای شما را نشان می‌دهد.',
      'با «فیلتر مدل» می‌توانید فهرست خودروها را کوتاه کنید. برای رسیدن سریع به یک عبارت خاص، از جستجوی داخل خودرو استفاده کنید — جستجو معنایی و دوزبانه است و عبارت فارسی را هم پیدا می‌کند.',
    ],
    docRef: 'docs/07-frontend.md#71-route-map-srcapp',
  },
  {
    id: 'parts-catalog', category: 'browse', roles: [ROLES.USER, ROLES.ANALYST, ROLES.MANAGER],
    surfaces: [{ path: '/browse' }], reviewed: REVIEWED,
    title: 'کاتالوگ قطعات یدکی', keywords: ['قطعات', 'کاتالوگ', 'شماره فنی', 'دیاگرام', 'پیکربندی', 'EPC'],
    summary: 'مرور دیاگرام‌های انفجاری و شماره فنی قطعات، مانند کاتالوگ رسمی کارخانه.',
    body: [
      'خودروهایی که «کاتالوگ قطعات» دارند، در صفحهٔ خودرو یک کارت «کاتالوگ قطعات یدکی» نشان می‌دهند. ساختار مرور همان درخت آشنای مستندات است: دسته → زیر‌دسته → صفحهٔ قطعه.',
      'در صفحهٔ قطعه، دیاگرام انفجاری با اسکرول بزرگ‌نمایی و با کشیدن جابه‌جا می‌شود؛ جدول زیر آن شماره فنی (قابل کپی با یک کلیک)، نام قطعه، تعداد و بازهٔ تولید را نشان می‌دهد. ستون «کد روی تصویر» هر ردیف را به شمارهٔ همان قطعه در دیاگرام وصل می‌کند.',
      'اگر خودرو چند پیکربندی (فریم) داشته باشد، بالای کاتالوگ می‌توانید پیکربندی درست را بر اساس موتور، فرمان و بازار انتخاب کنید.',
    ],
    docRef: 'docs/16-parts-catalog.md',
  },
  {
    id: 'search-tips', category: 'browse', roles: [ROLES.USER, ROLES.ANALYST, ROLES.MANAGER],
    surfaces: [], reviewed: REVIEWED,
    title: 'جستجوی هوشمند مستندات', keywords: ['جستجو', 'search', 'سرچ', 'پیدا کردن'],
    summary: 'جستجو معنایی است — با نام قطعه یا علامت خرابی هم نتیجه می‌گیرید.',
    body: [
      'جستجو فقط تطبیق واژه‌به‌واژه نیست؛ معنا را می‌فهمد و فارسی و انگلیسی را به هم نگاشت می‌کند. پس می‌توانید نام فارسی قطعه یا شرح کوتاه مشکل را بنویسید.',
      'اگر نتیجه‌ای نگرفتید، عبارت را کلی‌تر کنید یا همان پرسش را به «دستیار هوشمند» بدهید تا از دل منوال پاسخ استخراج کند.',
    ],
    docRef: 'docs/08-ai-assistant-rag.md#83-retrieval-retrievepy-served-via-servicepy',
  },
  // ---- Assistant -----------------------------------------------------------
  {
    id: 'assistant-how', category: 'assistant', roles: [ROLES.USER, ROLES.ANALYST, ROLES.MANAGER],
    surfaces: [{ path: '/assistant' }], reviewed: REVIEWED,
    title: 'دستیار هوشمند چطور کار می‌کند', keywords: ['دستیار', 'چت', 'DTC', 'کد خطا', 'عیب‌یابی', 'assistant'],
    summary: 'پاسخ‌ها فقط از دل منوال‌های خریداری‌شده استخراج می‌شوند — بدون حدس.',
    body: [
      'دستیار ابتدا موتور عیب‌یابی قطعی (برای کد خطا/علامت) و سپس بازیابی معنایی از منوال را اجرا می‌کند و در پایان پاسخ را به فارسی روان بازنویسی می‌کند. لینک‌های پاسخ همیشه به صفحهٔ واقعی و مجازِ همان مطلب می‌روند.',
      'گفتگو دنباله‌دار است: می‌توانید کوتاه ادامه بدهید (مثلاً «و گشتاورش چقدره؟») و دستیار پرسش قبلی را به یاد دارد. زیر هر پاسخ هم چند «پیشنهاد ادامه» می‌آید که با یک کلیک پرسیده می‌شوند.',
      'اگر پرسش مبهم باشد و به چند سیستم مختلف بخورد، دستیار به‌جای حدس، یک سؤال کوتاه برای روشن شدن منظور می‌پرسد.',
      'عنوان منابع به‌صورت دوزبانه «فارسی (English)» نمایش داده می‌شود تا اصطلاح رسمی منوال همیشه در دسترس باشد.',
      'برای دقت بیشتر، خودرو را مشخص کنید (برند/مدل/سال) و اگر کد خطا دارید عیناً بنویسید (مثلاً P0171).',
      'دستیار هرگز چیزی خارج از مستندات مجاز شما نمی‌سازد؛ اگر پاسخی در منابع نباشد، صادقانه می‌گوید که یافت نشد.',
    ],
    docRef: 'docs/08-ai-assistant-rag.md#85-chat-flow-kg_frontendsrcappapichatroutejs',
  },
  {
    id: 'assistant-eligibility', category: 'assistant', roles: [ROLES.USER, ROLES.ANALYST, ROLES.MANAGER],
    surfaces: [{ path: '/assistant' }], reviewed: REVIEWED,
    title: 'چرا دستیار برایم پاسخ نمی‌دهد؟', keywords: ['دستیار غیرفعال', 'دسترسی هوش مصنوعی', 'ai', 'اشتراک'],
    summary: 'فعال بودن دستیار به سه شرط بستگی دارد.',
    body: [
      'دستیار زمانی برای شما پاسخ می‌دهد که هر سه شرط برقرار باشد: ۱) دستیار برای حساب شما روشن باشد، ۲) دستیار برای شرکت شما فعال باشد، ۳) بستهٔ «منوال تعمیر» در دسترسی شما باشد.',
      'اگر یکی برقرار نیست، از مدیر تیم بخواهید دسترسی را فعال کند یا از طریق «درخواست‌ها» فعال‌سازی دستیار را از پشتیبانی بخواهد.',
    ],
    docRef: 'docs/06-permissions-rbac.md#65-capabilities-feature-flags-per-user',
  },
  // ---- Team management -----------------------------------------------------
  {
    id: 'team-overview', category: 'team', roles: [ROLES.MANAGER],
    surfaces: [{ path: '/team' }], tourId: 'manager-team', reviewed: REVIEWED,
    title: 'مدیریت تیم — نمای کلی', keywords: ['تیم', 'کارکنان', 'اعضا', 'کارمند'],
    summary: 'کارمند بسازید، جایگاه‌ها را تعریف کنید و دسترسی‌ها را واگذار کنید.',
    body: [
      'صفحهٔ تیم سه بخش دارد: «اعضا» برای مدیریت کارکنان، «چارت سازمانی» برای روابط گزارش‌دهی و «نقش‌ها» برای تعریف جایگاه‌ها.',
      'شما فقط کسانی را می‌بینید و مدیریت می‌کنید که در محدودهٔ جایگاه شما هستند و رتبه‌شان پایین‌تر از شماست.',
      'هر تغییر بلافاصله برای همهٔ نشست‌ها و برگه‌های باز هم‌زمان‌سازی می‌شود.',
    ],
    docRef: 'docs/06-permissions-rbac.md#66-org-hierarchy-who-manages-whom',
  },
  {
    id: 'team-add-member', category: 'team', roles: [ROLES.MANAGER],
    surfaces: [{ path: '/team' }], reviewed: REVIEWED,
    title: 'افزودن و دعوت کارمند', keywords: ['افزودن کارمند', 'دعوت', 'invite', 'رمز عبور', 'نام کاربری'],
    summary: 'دو روش: لینک دعوت (ایمیل) یا ساخت مستقیم نام کاربری و رمز.',
    body: [
      'روش «دعوت‌نامه»: یک لینک یک‌بارمصرف (۷ روزه) می‌سازید؛ کارمند با ایمیل خود وارد می‌شود و رمزش را خودش تعیین می‌کند. تا وقتی دعوت را نپذیرد، نمی‌تواند وارد شود.',
      'روش «نام کاربری و رمز»: حساب بلافاصله فعال می‌شود و نام کاربری و رمز را به‌صورت قابل‌کپی تحویل می‌گیرید تا به کارمند بدهید.',
      'هنگام ساخت، جایگاه سازمانی و سرپرست را تعیین کنید (سرپرست باید رتبهٔ بالاتری داشته باشد) و خودروهای مجاز را از میان دسترسی‌های خودتان واگذار کنید.',
    ],
    docRef: 'docs/05-api-reference.md#55-team-management-manager',
  },
  {
    id: 'team-delegate-access', category: 'team', roles: [ROLES.MANAGER],
    surfaces: [{ path: '/team' }], reviewed: REVIEWED,
    title: 'واگذاری دسترسی خودرو به کارمند', keywords: ['دسترسی', 'خودرو', 'واگذاری', 'بسته', 'مستند'],
    summary: 'فقط چیزی را می‌توانید بدهید که خودتان دارید («هر آنچه داری بده»).',
    body: [
      'دسترسی‌هایی که به کارمند می‌دهید به سقف دسترسی خودتان محدود می‌شود: نمی‌توانید خودرو یا لایه‌ای را بدهید که خودتان ندارید.',
      'اگر بخواهید لایه‌ای را بدهید که در اختیارتان نیست، آن خودرو نادیده گرفته می‌شود (به‌جای آنکه به اشتباه دسترسی کامل داده شود).',
      'برای خودرو یا ظرفیت بیشتر، از بخش «درخواست‌ها» به پشتیبانی درخواست بدهید.',
    ],
    docRef: 'docs/06-permissions-rbac.md#63-what-a-user-holds-grants',
  },
  {
    id: 'team-roles', category: 'team', roles: [ROLES.MANAGER],
    surfaces: [{ path: '/team' }], reviewed: REVIEWED,
    title: 'تعریف نقش‌ها و چارت سازمانی', keywords: ['نقش', 'جایگاه', 'رتبه', 'چارت', 'سازمانی', 'سرپرست'],
    summary: 'جایگاه‌ها را بسازید، رتبه‌بندی کنید و روابط گزارش‌دهی را بچینید.',
    body: [
      'در «نقش‌ها» می‌توانید جایگاه بسازید، با کشیدن‌ورهاکردن رتبه‌بندی کنید، محدودهٔ مدیریت و دسترسی‌های پیش‌فرض هر جایگاه را تعیین کنید. فقط جایگاه‌های پایین‌تر از خودتان قابل ویرایش‌اند.',
      'در «چارت سازمانی» با کلیک، افراد را جابه‌جا و سرپرست‌شان را تعیین می‌کنید. قانون همیشگی: سرپرست باید رتبهٔ بالاتری (عدد کوچک‌تر) از زیردست داشته باشد؛ سامانه ناسازگاری‌ها را خودکار اصلاح می‌کند.',
    ],
    docRef: 'docs/06-permissions-rbac.md#66-org-hierarchy-who-manages-whom',
  },
  // ---- Analytics -----------------------------------------------------------
  {
    id: 'analytics-read', category: 'analytics', roles: [ROLES.ANALYST, ROLES.MANAGER], cap: 'analytics',
    surfaces: [{ path: '/team/analytics' }], reviewed: REVIEWED,
    title: 'خواندن تحلیل استفاده', keywords: ['تحلیل', 'گزارش', 'آمار', 'دسته', 'روند'],
    summary: 'میزان استفادهٔ تیم به تفکیک عضو، حوزهٔ فنی و روند زمانی.',
    body: [
      'نمودارها استفادهٔ تیم را بر اساس حوزهٔ فنی (موتور، ترمز، برق و …)، هر عضو و روند روزانه نشان می‌دهند. بازهٔ زمانی را از بالای صفحه انتخاب کنید.',
      'شما فقط داده‌های کسانی را می‌بینید که اجازهٔ مدیریت‌شان را دارید — دقیقاً همان محدودهٔ صفحهٔ تیم.',
    ],
    docRef: 'docs/10-analytics-reporting.md#102-team-analytics-manageranalytics-viewers',
  },
  {
    id: 'analytics-pdf', category: 'analytics', roles: [ROLES.ANALYST, ROLES.MANAGER], cap: 'analytics',
    surfaces: [{ path: '/team/analytics' }], reviewed: REVIEWED,
    title: 'دانلود گزارش PDF', keywords: ['pdf', 'گزارش', 'دانلود', 'چاپ'],
    summary: 'یک گزارش فارسی و آمادهٔ ارائه از استفادهٔ تیم بگیرید.',
    body: [
      'با دکمهٔ دانلود، یک گزارش PDF فارسی و راست‌به‌چپ شامل جلد، شاخص‌های کلیدی، نمودار حوزه‌ها، روند و جداول عضو/خودرو تهیه می‌شود. بازهٔ زمانی همان انتخاب صفحه است.',
    ],
    docRef: 'docs/10-analytics-reporting.md#103-pdf-team-report-apireportingpy',
  },
  // ---- Requests ------------------------------------------------------------
  {
    id: 'requests-file', category: 'requests', roles: [ROLES.MANAGER],
    surfaces: [{ path: '/requests' }], reviewed: REVIEWED,
    title: 'ثبت درخواست برای پشتیبانی', keywords: ['درخواست', 'خرید', 'ظرفیت', 'صندلی', 'دستیار', 'پشتیبانی'],
    summary: 'خودرو، ظرفیت کاربر، فعال‌سازی دستیار یا پشتیبانی را از اینجا بخواهید.',
    body: [
      'نوع درخواست را انتخاب کنید (دسترسی به خودرو، افزایش ظرفیت کاربران، فعال‌سازی دستیار، افزودن بستهٔ مستندات، یا پشتیبانی) و جزئیات را بنویسید.',
      'وضعیت درخواست (در انتظار ← در حال انجام ← انجام شد) به‌صورت زنده به‌روز می‌شود؛ لازم نیست صفحه را رفرش کنید.',
    ],
    docRef: 'docs/05-api-reference.md#57-company-requests-manager-admin',
  },
  // ---- Account -------------------------------------------------------------
  {
    id: 'account-settings', category: 'account', roles: [ROLES.USER, ROLES.ANALYST, ROLES.MANAGER],
    surfaces: [{ path: '/settings' }], reviewed: REVIEWED,
    title: 'حساب، ظاهر و راهنما', keywords: ['تنظیمات', 'حساب', 'تم', 'روشن', 'تاریک', 'اعلان', 'راهنما'],
    summary: 'مشخصات حساب، حالت نمایش و اجرای دوبارهٔ راهنما.',
    body: [
      'در تنظیمات می‌توانید مشخصات حساب و شرکت خود را ببینید، بین حالت روشن و تاریک جابه‌جا شوید و راهنمای گام‌به‌گام را دوباره اجرا کنید.',
      'رمز عبور از این نسخه قابل تغییر توسط خودتان نیست؛ برای بازنشانی رمز با مدیر تیم یا پشتیبانی تماس بگیرید.',
    ],
    docRef: 'docs/07-frontend.md#71-route-map-srcapp',
  },
  // ---- Admin: platform management (the administrator guide) -----------------
  {
    id: 'admin-guide-index', category: 'admin', roles: [ROLES.ADMIN],
    surfaces: [{ path: '/admin' }], tourId: 'admin-hub', reviewed: REVIEWED,
    title: 'راهنمای مدیر پلتفرم', keywords: ['مدیریت', 'ادمین', 'پنل', 'شروع', 'میز مدیریت'],
    summary: 'نقطهٔ شروع مدیر: هر بخش پنل چه‌کار می‌کند و ترتیب منطقی کارها.',
    body: [
      'میز مدیریت بخش‌ها را در چهار گروه می‌چیند: بلادرنگ (داشبورد و درخواست شرکت‌ها)، مشتریان و فروش (درخواست خرید ← شرکت‌ها ← کاربران)، گزارش و تحلیل، و داده و عملیات.',
      'گردش کار معمول راه‌اندازی یک مشتری: ۱) درخواست خرید را بررسی کنید، ۲) شرکت را با دامنهٔ خرید بسازید، ۳) کاربران را صادر و دسترسی خودرو را تخصیص دهید.',
      'در هر بخش، دکمهٔ «؟» (یا کلید ؟) راهنمای همان بخش را باز می‌کند.',
    ],
    docRef: 'docs/07-frontend.md#74-admin-panel-appadminpagejsx-1900-lines',
  },
  {
    id: 'admin-dashboard', category: 'admin', roles: [ROLES.ADMIN],
    surfaces: [{ path: '/admin', section: 'dashboard' }], reviewed: REVIEWED,
    title: 'داشبورد بلادرنگ', keywords: ['داشبورد', 'زنده', 'رویداد', 'هشدار', 'ترافیک'],
    summary: 'وضعیت زندهٔ پلتفرم: شاخص‌ها، پردازش، درخواست‌ها، هشدارها و رویدادها.',
    body: [
      'داشبورد شاخص‌های کلیدی، پیشرفت پردازش داده، درخواست‌های تازه، هشدارهای عملیاتی و جریان رویدادها را زنده نشان می‌دهد (از طریق SSE؛ بدون رفرش).',
      'اگر «داده جدید شناسایی شد» را دیدید، به بخش «پردازش داده‌ها» بروید و پردازش را اجرا کنید.',
    ],
    docRef: 'docs/09-realtime-sse.md#94-frontend-consumption',
  },
  {
    id: 'admin-company-requests', category: 'admin', roles: [ROLES.ADMIN],
    surfaces: [{ path: '/admin', section: 'company-requests' }], reviewed: REVIEWED,
    title: 'درخواست‌های شرکت‌ها', keywords: ['درخواست شرکت', 'صندوق', 'رسیدگی', 'مدیر شرکت'],
    summary: 'درخواست‌های مدیران شرکت‌ها را ببینید و وضعیت‌شان را تغییر دهید.',
    body: [
      'این صندوق درخواست‌های مدیران شرکت‌ها (خودرو، ظرفیت، دستیار، پشتیبانی) را نشان می‌دهد. با تغییر وضعیت (در حال انجام / انجام شد / رد) هر دو طرف بلافاصله به‌روز می‌شوند.',
      'برای اجرای درخواست (مثلاً افزودن خودرو)، تغییر واقعی را در بخش «شرکت‌ها» یا «کاربران» انجام دهید، سپس درخواست را «انجام شد» علامت بزنید.',
    ],
    docRef: 'docs/05-api-reference.md#57-company-requests-manager-admin',
  },
  {
    id: 'admin-requests', category: 'admin', roles: [ROLES.ADMIN],
    surfaces: [{ path: '/admin', section: 'requests' }], reviewed: REVIEWED,
    title: 'درخواست‌های خرید', keywords: ['خرید', 'مشتری', 'لید', 'فروش', 'purchase'],
    summary: 'درخواست‌های عمومی خرید را بررسی و به شرکت تبدیل کنید.',
    body: [
      'این‌ها فرم‌های خریدی هستند که از صفحهٔ عمومی «سفارش / خرید» می‌آیند: خودرو، لایه‌های موردنیاز، مشخصات حقوقی و برنامهٔ صندلی به‌تفکیک نقش.',
      'پس از بررسی، از همین‌جا شرکت را بسازید (دکمهٔ ساخت شرکت اطلاعات را از درخواست پیش‌پر می‌کند) و وضعیت درخواست را به‌روز کنید.',
    ],
    docRef: 'docs/03-data-model.md#catalog-sales',
  },
  {
    id: 'admin-companies', category: 'admin', roles: [ROLES.ADMIN],
    surfaces: [{ path: '/admin', section: 'companies' }], reviewed: REVIEWED,
    title: 'شرکت‌ها و دامنهٔ خرید', keywords: ['شرکت', 'دسترسی', 'خرید', 'خودرو', 'بسته', 'دامنه'],
    summary: 'شرکت را تعریف کنید و تعیین کنید چه خودروها/لایه‌هایی خریده است.',
    body: [
      'دامنهٔ خرید شرکت، سقف دسترسی همهٔ کاربران آن است. هنگام ساخت شرکت، چهار نقش پیش‌فرض سازمانی هم برایش ساخته می‌شود.',
      'اگر دامنهٔ خرید را کم کنید، دسترسی کاربران به خودروهای خارج از دامنه هرس می‌شود — مگر دسترسی‌هایی که مستقیماً توسط ادمین (admin_granted) داده شده‌اند که باقی می‌مانند.',
      'برای فعال‌سازی دستیار هوشمند برای یک شرکت، کلید مربوطه را در همین‌جا روشن کنید.',
    ],
    docRef: 'docs/06-permissions-rbac.md#62-what-a-company-bought-purchase-scope',
  },
  {
    id: 'admin-users', category: 'admin', roles: [ROLES.ADMIN],
    surfaces: [{ path: '/admin', section: 'users' }], reviewed: REVIEWED,
    title: 'مدیریت کاربران', keywords: ['کاربر', 'حساب', 'رمز', 'دسترسی', 'نقش', 'قفل'],
    summary: 'حساب‌های کاربری را بسازید و دسترسی هر کاربر را تنظیم کنید.',
    body: [
      'می‌توانید کاربر بسازید (نام کاربری و رمز صادر می‌شود)، نقش و شرکت را تغییر دهید و دسترسی خودرو را تنظیم کنید. دسترسی‌هایی که ادمین می‌دهد می‌توانند از دامنهٔ خرید شرکت فراتر بروند (admin_granted).',
      'تغییر نقش یا سرپرست، ثبات چارت سازمانی شرکت را به‌صورت خودکار حفظ می‌کند.',
    ],
    docRef: 'docs/06-permissions-rbac.md#67-platform-admin',
  },
  {
    id: 'admin-analytics', category: 'admin', roles: [ROLES.ADMIN],
    surfaces: [{ path: '/admin', section: 'analytics' }, { path: '/admin', section: 'activity' }, { path: '/admin', section: 'overview' }], reviewed: REVIEWED,
    title: 'تحلیل و گزارش پلتفرم', keywords: ['تحلیل', 'گزارش', 'فعالیت', 'استفاده', 'نمای کلی'],
    summary: 'استفادهٔ کل پلتفرم به تفکیک شرکت و حوزهٔ فنی، و ریز فعالیت‌ها.',
    body: [
      '«تحلیل کل پلتفرم» میزان استفاده را در همهٔ شرکت‌ها و حوزه‌های فنی نشان می‌دهد؛ «گزارش فعالیت» ریز رویدادهای کاربران را با امکان فیلتر می‌آورد؛ «نمای کلی» خلاصهٔ وضعیت را می‌دهد.',
    ],
    docRef: 'docs/10-analytics-reporting.md#104-platform-analytics-admin',
  },
  {
    id: 'admin-catalog', category: 'admin-ops', roles: [ROLES.ADMIN],
    surfaces: [{ path: '/admin', section: 'catalog' }], reviewed: REVIEWED,
    title: 'فهرست خودروها', keywords: ['خودرو', 'کاتالوگ', 'دیتابیس', 'ثبت', 'فیلتر', 'وضعیت'],
    summary: 'خودروهای ثبت‌شده، فیلتر ناوگان و وضعیت سلامت دادهٔ هرکدام.',
    body: [
      'این فهرست خودروهای کاتالوگ و وضعیت آمادگی فایل دیتابیس هرکدام را نشان می‌دهد. برای افزودن خودرو، فایل دیتابیس و پوشهٔ تصاویرش را در انبار قرار دهید؛ سپس پردازش داده‌ها آن را ثبت و ایندکس می‌کند.',
      'با نوار فیلتر می‌توانید ناوگان را بر اساس برند، سال ساخت و مدل محدود کنید — و همچنین بر اساس وضعیت: «ناقص»، «کار در انتظار» یا «بدون ایندکس». هر ردیف درصد کامل‌بودن داده، تعداد بخش‌های ناقص و وضعیت ایندکس هوشمند، عیب‌یاب، تصاویر و مشخصات را نشان می‌دهد. این شاخص‌ها از آخرین «بررسی انبار داده» می‌آیند؛ برای تازه‌سازی به بخش «سلامت داده‌ها» بروید.',
    ],
    docRef: 'docs/11-operations-deployment.md#114-data-processing-pipeline-admin-operated',
  },
  {
    id: 'admin-dataquality', category: 'admin-ops', roles: [ROLES.ADMIN],
    surfaces: [{ path: '/admin', section: 'dataquality' }], reviewed: REVIEWED,
    title: 'سلامت داده‌ها', keywords: ['کیفیت', 'ممیزی', 'کامل بودن', 'تکراری', 'قرنطینه'],
    summary: 'ممیزی کامل‌بودن و کیفیت مستندات هر خودرو.',
    body: [
      'ممیزی، کامل‌بودن بخش‌های استاندارد هر خودرو، خودروهای تکراری و کاستی‌های داده را می‌سنجد. با «بازخوانی» گزارش تازه می‌شود و با «اصلاح»، تکراری‌ها ادغام و فایل‌های مشکل‌دار به قرنطینه منتقل می‌شوند — هیچ‌چیز حذف نمی‌شود.',
    ],
    docRef: 'docs/11-operations-deployment.md#115-monitoring-alerting-data-quality',
  },
  {
    id: 'admin-pipeline', category: 'admin-ops', roles: [ROLES.ADMIN],
    surfaces: [{ path: '/admin', section: 'pipeline' }], reviewed: REVIEWED,
    title: 'پردازش داده‌ها', keywords: ['پردازش', 'ایندکس', 'rag', 'زمان‌بندی', 'ازسرگیری'],
    summary: 'با یک دکمه همهٔ پردازش‌های لازم روی داده‌های جدید را اجرا کنید.',
    body: [
      'این بخش کل زنجیرهٔ پردازش (ثبت کاتالوگ ← ایندکس RAG ← عیب‌یابی ← بازممیزی) را اجرا می‌کند و پیشرفت، سرعت و زمان تخمینی هر مرحله را زنده نشان می‌دهد.',
      'کار در پس‌زمینه و با اولویت پایین اجرا می‌شود؛ بستن مرورگر یا حتی ری‌استارت سرور آن را قطع نمی‌کند و در صورت توقف، خودکار از سر گرفته می‌شود. می‌توانید زمان‌بندی کنید یا حالت خودکار را روشن بگذارید.',
    ],
    docRef: 'docs/11-operations-deployment.md#114-data-processing-pipeline-admin-operated',
  },
  {
    id: 'admin-system', category: 'admin-ops', roles: [ROLES.ADMIN],
    surfaces: [{ path: '/admin', section: 'system' }], reviewed: REVIEWED,
    title: 'پایش سیستم', keywords: ['پایش', 'منابع', 'دیسک', 'حافظه', 'هشدار', 'ترافیک', 'خطا'],
    summary: 'منابع سرور، ترافیک و هشدارهای عملیاتی.',
    body: [
      'اینجا وضعیت دیسک/حافظه/بار سرور، وضعیت پایگاه‌داده و ایندکس، سری‌های ترافیک و نرخ خطا و تأخیر هر مسیر را می‌بینید.',
      'هشدارها خودکار ساخته و با رفع شرایط خودکار بسته می‌شوند. آستانه‌ها از طریق متغیرهای محیطی KG_ALERT_* قابل تنظیم‌اند.',
    ],
    docRef: 'docs/11-operations-deployment.md#115-monitoring-alerting-data-quality',
  },
  {
    id: 'admin-troubleshooting', category: 'admin-ops', roles: [ROLES.ADMIN],
    surfaces: [{ path: '/admin' }], reviewed: REVIEWED,
    title: 'رفع اشکال‌های رایج', keywords: ['خطا', 'مشکل', 'رفع اشکال', 'troubleshoot', '۴۰۴', '۵۰۰'],
    summary: 'نشانه‌های رایج و اولین کاری که باید کرد.',
    body: [
      'کاربر می‌گوید خودرو را نمی‌بیند: بررسی کنید دسترسی کاربر صادر شده و فایل دیتابیس خودرو آماده است (بخش فهرست خودروها).',
      'دستیار پاسخ نمی‌دهد: سه شرط اهلیت را چک کنید — کلید کاربر، کلید شرکت و وجود بستهٔ منوال.',
      'لینک یا تصویری باز نمی‌شود: احتمالاً خودرو هنوز کامل پردازش/ایندکس نشده — بخش سلامت داده‌ها و پردازش را ببینید.',
      'هشدار عملیاتی: بخش پایش سیستم را باز کنید؛ هشدارها با رفع شرط خودکار بسته می‌شوند.',
    ],
    docRef: 'docs/11-operations-deployment.md#117-operational-runbook-snippets',
  },
];

export function articlesFor(audience) {
  return ARTICLES.filter((a) => audienceMatches(a, audience));
}

// Best contextual article(s) for the current surface, most specific first
// (matching section beats matching path beats a role default).
export function contextualArticles(audience, { pathname = '', section = null } = {}) {
  const mine = articlesFor(audience);
  const scored = mine
    .map((a) => {
      let score = -1;
      for (const s of a.surfaces || []) {
        if (s.section && section && s.section === section && pathname.startsWith(s.path || '/admin')) {
          score = Math.max(score, 3);
        } else if (s.path && pathname === s.path) {
          score = Math.max(score, s.section ? (section ? -1 : 1) : 2);
        } else if (s.path && pathname.startsWith(s.path) && !s.section) {
          score = Math.max(score, 1);
        }
      }
      return { a, score };
    })
    .filter((x) => x.score >= 0)
    .sort((x, y) => y.score - x.score);
  return scored.map((x) => x.a);
}
