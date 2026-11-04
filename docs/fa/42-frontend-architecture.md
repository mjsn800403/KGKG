<!-- i18n-source: 42-frontend-architecture.md sha256:eb368af96074 -->
<div dir="rtl" lang="fa">

# ۴۲ — مرجع معماری فرانت‌اند

مکمل [۰۷ — فرانت‌اند](07-frontend.md) (نقشهٔ مسیرها، هاب ادمین، فیلتر، میز پشتیبانی) با طراحی لایه‌به‌لایه، مدیریت وضعیت، یکپارچه‌سازی API، لایه‌های امنیتی، فهرست همهٔ گروه‌های مؤلفه و گردش‌کارهای پیاده‌شدهٔ کاربر. نسخهٔ انگلیسی: [../42-frontend-architecture.md](../42-frontend-architecture.md). همهٔ گزاره‌ها **[C]** هستند (خوانده‌شده در `kg_frontend/src/`) مگر برچسب دیگری داشته باشند. صفحه‌های طرح‌ها و قیمت‌گذاری تجاری عمداً خارج از این سند است.

## ۴۲٫۱ فناوری و مدل رندر

| جنبه | واقعیت |
|---|---|
| چارچوب | Next.js نسخهٔ ۱۶٫۴ (App Router) با React نسخهٔ ۱۹٫۲؛ TypeScript برای صفحه‌های جدیدتر (`*.tsx`) و JavaScript (`*.jsx`) برای بقیه. `kg_frontend/package.json` |
| کتابخانه‌ها | `@xyflow/react` (بوم سازمانی)، `motion` (انیمیشن)، `@sentry/node` (گزارش خطای سمت سرور)؛ Tailwind نسخهٔ ۴ و افزونهٔ PostCSS آن نصب‌اند اما هیچ استایل‌شیتی Tailwind را import نمی‌کند و کلاس کاربردی Tailwind یافت نشد؛ استایل با CSS دست‌نویس است (`globals.css`، `system.css`، `landing.css`، `plans.css`) |
| بدون کتابخانهٔ وضعیت سراسری | Redux/Zustand/Context برای داده نیست. وضعیت محلی مؤلفه (`useState`/`useReducer`)، حافظهٔ مرورگر و چند رویداد DOM است (§۴۲٫۴) |
| زبان / جهت | `<html lang="fa" dir="rtl">`؛ تمام متن رابط فارسی است؛ تاریخ جلالی با `JalaliDateTimeInput`؛ یکسان‌سازی ارقام با `utils/phone.js` |
| رندر | همهٔ صفحه‌ها پویا هستند (layout ریشه nonce مربوط به CSP هر درخواست را از `headers()` می‌خواند). صفحه‌های محتوای دفترچه **server component** هستند و هنگام SSR از Django می‌خوانند؛ سطوح تعاملی client component هستند (`'use client'`) |
| فونت / دارایی | فونت‌ها خودمیزبان؛ آیکن‌ها مجموعهٔ SVG درون‌خطی (`components/Icon.jsx`)، بدون CDN |
| تحلیل | Umami خودمیزبان، بازدید صفحه به‌صورت دستی از `components/Analytics.jsx` با پنهان‌سازی نشانی (`utils/analytics.js`)؛ auto-track خاموش است |
| فرایند تولید | `next start` در کانتینر `kgkg-frontend:<sha>` روی loopback ‏`:3000`؛ nginx جلوی آن ([۳۳](33-system-design.md)) |

## ۴۲٫۲ مسیر درخواست و احراز هویت

```
Browser ──► nginx ──► Next.js (proxy.ts) ──► page (server component) ──► Django /api/... (SSR, token از کوکی)
   │                                         └► client component ──► /kg-api/... (nginx ← Django)، Bearer یا کوکی
   └─ POST /api/chat ──► Next route handler ──► Django (/api/auth/me، /ai-usage، /diagnose، /assist) و Metis
```

- **دو مبنای API** (`utils/api.jsx`): در مرورگر `NEXT_PUBLIC_API_BASE` (پیش‌فرض `/kg-api`، هم‌مبدأ از طریق nginx)؛ هنگام SSR مقدار `API_BASE_INTERNAL` (پیش‌فرض `http://127.0.0.1:8000`). نشانی رسانه همیشه از مبنای عمومی است.
- **`src/proxy.ts`** روی هر درخواست غیرِدارایی اجرا می‌شود: (۱) بازدیدکنندهٔ بدون کوکی `kg_portal_token` را برای `/browse`، `/assistant`، `/team`، `/settings`، `/requests`، `/admin-review` و مسیرهای برند (`/Toyota/2023/…`) به `/login?next=…` هدایت می‌کند؛ (۲) برای هر درخواست **nonce** تازه می‌سازد و Content-Security-Policy را تنظیم می‌کند (script-src برابر `'self'` + nonce + Turnstile/Insights کلودفلر؛ frameها فقط `'self'` و Turnstile؛ `frame-ancestors 'none'`؛ `object-src 'none'`). `/admin` در فهرست نیست: توکن آن در `sessionStorage`/`localStorage` است و سمت کلاینت بررسی می‌شود.
- **توکن پورتال** — کوکی HttpOnly که بک‌اند می‌گذارد به‌علاوهٔ نسخه‌ای در `localStorage` (کلید `kg_portal_token`، کاربر کش‌شده `kg_portal_user`) که `setPortalSession` آن را به کوکی هم‌سایت آینه می‌کند تا server componentها بتوانند ارسالش کنند (`utils/serverAuth.js`). **توکن ادمین** — جدا (`kg_admin_token`) و به‌صورت Bearer؛ `shareAdminToken`/`obtainAdminToken` آن را میان تب‌ها به اشتراک می‌گذارند.
- **۴۰۱** روی محتوا ← هدایت به `/login`؛ **۴۰۳ با بدنهٔ `{"error":"forbidden"}`** ← «در اشتراک شما نیست»؛ ۴۰۳ بدون آن بدنه مسدودسازی WAF تلقی می‌شود (`contentError`).

## ۴۲٫۳ لایه‌های امنیتی در مرورگر

| لایه | فایل‌ها | هدف |
|---|---|---|
| CSP + nonce | `proxy.ts`، `app/layout.tsx` | جلوگیری از اسکریپت تزریق‌شده؛ اسکریپت راه‌اندازی تم nonce دارد |
| پاک‌ساز HTML | `lib/sanitizeHtml.js` | پاک‌سازی بر پایهٔ فهرست مجاز برای HTML انبار پیش از `dangerouslySetInnerHTML` (`ContentRenderer`، `StackedContent`) |
| نشانی امن | `lib/safeUrl.js` | پیوند ارجاع‌شده توسط دستیار فقط می‌تواند به درون برنامه اشاره کند |
| سپر محتوا | `lib/shield.js`، `utils/shieldServer.js`، `lib/useUnsealed.jsx`، `lib/shieldBase.js` | امضای درخواست (`shieldFetch`) با کلیدهای چرخان هر نشست از `/api/shield/key/`؛ propهای SSR مهر می‌شوند تا HTML/RSC حاوی متن رمزشده باشد؛ `useUnsealed` در مرورگر بازشان می‌کند. هنگام ساخت مبهم‌سازی می‌شود (`javascript-obfuscator`). نیمهٔ بک‌اند: `api/shield.py`؛ بازدارنده است نه DRM ([۲۶](26-auth-and-sessions.md)) |
| نگهبان محتوا | `components/ContentGuard.jsx` | از کپی جلوگیری می‌کند و نشت را ردیابی‌پذیر می‌سازد؛ محدودیت‌های واقعی سمت سرور است (`api/contentguard.py`) |
| Turnstile | ورود، بازیابی، ورود ادمین، چت پشتیبانی | توکن چالش کلودفلر به بک‌اند ارسال می‌شود |

## ۴۲٫۴ مدیریت وضعیت و حافظهٔ مرورگر

| وضعیت | محل | یادداشت |
|---|---|---|
| کاربر واردشده | `getPortalUser()` روی `localStorage` کلید `kg_portal_user`؛ `portalRefreshMe()` تازه‌سازی می‌کند؛ رویداد DOM به نام **`kg:me`** به `Sidebar`، `SettingsView` و … می‌گوید دوباره بخوانند | هر مؤلفهٔ تازه که قابلیت‌ها را لازم دارد همین الگو را دنبال کند |
| تم | `localStorage` کلید `kg-theme` + صفت `data-theme`؛ رویداد `kg:theme` کلیدها را هماهنگ نگه می‌دارد؛ اسکریپت boot از پرش جلوگیری می‌کند | `ThemeToggle`، `SettingsView` |
| وضعیت تور | `kg-tour-done`؛ وضعیت راهنما با پیشوند `kg-guide:` (`guidance/storage.js`) | هر خواندن/نوشتن با try/catch محافظت شده |
| دستیار | `kg_assistant_uid` (شناسهٔ ناشناس هر مرورگر برای چت)، تاریخچهٔ چت در state مؤلفه | تاریخچه به route فرستاده و سمت سرور پاک‌سازی می‌شود |
| ویجت چت پشتیبانی | `localStorage kg_sc_v1` (شناسهٔ رشته، توکن، قصد)، `sessionStorage kg_sc_q_v1` (پیام‌های ارسال‌نشده، سقف ۲۴ ساعت) | reducer خالص `support-chat/state.js`؛ توکن در مرورگر ساخته می‌شود (۳۲ بایت تصادفی، فقط SHA-256 در سرور ذخیره می‌شود) |
| رویدادهای زنده | `utils/sharedEventStream.js` — **یک اتصال SSE برای هر مخاطب در هر تب**، مشترک میان مشترکان `useEventStream`؛ ادامه با `Last-Event-ID`؛ مبتنی بر fetch تا سرآیند Bearer بتواند عبور کند (`utils/eventStreamConnector.js`) | داشبورد ادمین هر ۶۰ ثانیه همگام‌سازی مجدد دارد |
| مودال | رویداد پنجره‌ای **`kg:modal`** با `{title, body, icon}` که `Modal` سراسری پردازش می‌کند | هر مؤلفه می‌تواند باز کند |
| راهنماهای زمینه‌ای | `reportSignal()` (`guidance/signals.js`) مؤلفه‌ها را از provider راهنما جدا می‌کند؛ `SignalReporter` به server componentها امکان گزارش می‌دهد | |
| وضعیت در URL | قطعات brand/year/model/path (با `⁄` یعنی NAV_SLASH برای اسلش داخل نام قطعه)، `?cfg=` برای پیکربندی قطعات، هش `#section` در ادمین | `utils/api.jsx` |

## ۴۲٫۵ یکپارچه‌سازی API (`utils/api.jsx`، تنها لایهٔ fetch)

| گروه | exportها (نمونه) | حوزهٔ بک‌اند |
|---|---|---|
| کاتالوگ و دفترچه | `fetchAllBrands`، `fetchBrands`، `fetchYearData`، `fetchNodes`، `fetchNav`، `fetchSubtree`، `fetchModels`، `resolveHref`، `fetchRawPage`، `searchNodes`، `fetchVehicleSpec` | `car_view`، `api/views.py`، `cardb*` |
| قطعات و جدول‌ها | `fetchPartsRoot`، `fetchPartsNodes`، `fetchPartsSearch`، `fetchFrm`، `laborTimesCsvUrl`، `sstCsvUrl`، `fetchSstAvailable` | `api/parts.py`، `api/frm.py`، `labortimes`، `sst` |
| نشست | `portalLogin`، `verifyOtp`، `resendOtp`، `recoverStart`، `recoverReset`، `portalRefreshMe`، `portalLogout`، `updateBrowseMode`، `updateNotifyPrefs`، `updateOtpEnabled`، `fetchGrantedFleet` | `api/portal.py` |
| تیم | `teamApi.*` (تحلیل، گزارش گفتگو)، `orgGraph`، `orgCreateNode`، `orgUpdateNode`، `orgDeleteNode`، `orgSetPermission`، `orgCreateUser`، `validateInvite`، `acceptInvite`، `downloadTeamReport` | `api/team.py`، `orggraph_api.py` |
| میز پشتیبانی | `feedbackApi.*`، `kbApi.*`، `onboardingApi.*`، `fetchRecommendations` | `requests_api.py`، `knowledge.py`، `onboarding.py`، `recommend.py` |
| ادمین | `adminLogin`، `adminVerifyOtp`، `adminApi.*` (تقریباً همهٔ بخش‌های ادمین) | `api/admin.py`، `adminops.py`، `insights.py`، `audit.py`، `pipeline.py` |
| بازخورد دستیار | `chatFeedback`، `rateAnswer`، `pinFeedback`، `fetchRecentFeedback` | `rag/feedback.py` |
| زنده | `openEventStream` | `api/events.py` (SSE) |
| چت پشتیبانی (بازدیدکننده) | `support-chat/client.js` (هرگز throw نمی‌کند، `{ok, kind, …}` برمی‌گرداند) | `api/support_chat/` |
| چت پشتیبانی (کارکنان) | `utils/supportChatApi.js` (توکن ادمین) | همان |
| فعالیت | `logActivity` (ارسال بدون انتظار)، `ActivityBeacon` برای صفحه‌های سمت سرور | `ActivityLog` |

دستیار از `api.jsx` عبور **نمی‌کند**: `app/api/chat/route.js` یک route handler سمت سرور است که کلید API متیس را نگه می‌دارد و چرخهٔ [۳۰ بخش ۳۰٫۳](30-ai-assistant-deep-dive.md) را پیاده می‌کند؛ ماژول‌های کمکی `lib/chatPrompt.js`، `lib/contextualize.js`، `lib/faTerms.js`، `lib/safeUrl.js` آزمون واحد دارند.

## ۴۲٫۶ فهرست مؤلفه‌ها

**پوسته و ناوبری** — `DashboardShell` (سایدبار + محتوا)، `Sidebar` (گروه‌ها: مستندات، تیم، حساب؛ آیتم‌ها بر پایهٔ payload کاربر محدود می‌شوند؛ لنگرهای `data-tour`)، `Breadcrumb` (مسیرهای عمیق دفترچه را جمع می‌کند)، `UserChip` (چیزی رندر نمی‌کند؛ هویت در سایدبار است)، `ThemeToggle`، `Modal`، `BackgroundFX`، `Skeleton`، `Icon`، `Switch`.
**دفترچه‌ها** — `CarBrowser` (سایدبار درخت + پنجرهٔ محتوا)، `CarNav` (درخت تنبل، مسیر فعلی را پررنگ می‌کند)، `NodeList`/`NodeItem`/`SectionList`/`CardGrid`، `ContentRenderer` (پیوندهای قدیمی `pages/<id>.html` را بازنویسی می‌کند)، `StackedContent` (زیردرخت مسطح‌شده با لنگر `node-<id>`)، `SearchBox` (تکمیل خودکار، حداکثر ۵ پیشنهاد، ورودی انگلیسی)، `VehicleCover` (واقعیت‌ها از `VehicleSpec`، اقدام‌ها، ظرفیت‌ها)، `FleetView`، `VehicleFilter`/`VehicleCardGrid`/`VehicleGroupList` (یک فیلتر و گروه‌بندی برای هر فهرست خودرو).
**قطعات و زمان استاندارد** — `PartsConfigPicker`، `PartsNav`، `PartsViewer` (نقشهٔ انفجاری با pan/zoom + جدول)، `FrmShell`، `FrmTable` (جدول LTS با حدود ۵٬۰۰۰ ردیف، فیلتر، صفحه‌بندی).
**دستیار** — `AssistantChat` (پیوند markdown و شکل `[BUTTON]`، استریم، پرسش‌های پیشنهادی)، `EvidencePanel` (چرا این پاسخ: تطابق دقیق کد / کلیدواژه / معنایی، همین خودرو، تأییدشدهٔ کارشناس، موتور عیب‌یابی؛ مفید/نامفید)، `FeedbackBar` (👍/👎 با دلیل)، `app/assistant/page.jsx` (ابتدا خودرو را انتخاب کنید).
**تیم** — `OrgGraphCanvas` (بوم + نمای فهرست؛ ویرایش فقط توسط جایگاه ریشه)، `AnalyticsView` (۷/۳۰/۹۰ روز، جزئیات هر کارمند، PDF)، `ChatLogsView` (مشترک با پنل ادمین)، `RecommendationsWidget`، `OnboardingStrip`، `SettingsView` (زبانه‌ها: اطلاعات حساب، اعلان‌ها، امنیت و دسترسی؛ تم، شیوهٔ مرور، شروع دوبارهٔ راهنما).
**میز پشتیبانی** — `RequestsView` (مشتری)، `RequestsInbox` (کارشناس)، `TicketThread`، `CsatPrompt`، `FeedbackWidget` (بازخورد صفحه)، `components/desk/*` (`DeskLayout` دو پنجره بالای ۸۶۰ پیکسل، `TicketList`، `DeskFilters`، `KbSuggestions` — «این پاسخ داد» تنها چیزی است که انحراف تیکت را ثبت می‌کند)، `SupportAdmin` (شاخص‌های پشتیبانی، بازخورد محصول، میز دانش‌نامه).
**ادمین** — `app/admin/page.jsx` (۲۴ بخش، §۴۲٫۷)، `AdminDashboard` (شاخص‌های زنده با SSE)، `AdminInsights` (ردپای ممیزی، هزینهٔ AI، بینش جست‌وجو، قیف پذیرش)، `JalaliDateTimeInput`.
**راهنما** — `GuidanceProvider` (ریشهٔ یگانه؛ مخاطب، سطح، تورها و راهنماهای زمینه‌ای را تعیین می‌کند)، `TourEngine`، `HintLayer` (حداکثر یک راهنما، هرگز مودال)، `HelpCenter` (مقاله‌های داخلی `content.js` + دانش‌نامه)، `hintRules.js`، `SiteTour`. انحراف شناخته‌شده: تورهای صفحهٔ تیم به لنگرهای حذف‌شده اشاره می‌کنند ([۰۷ بخش ۷٫۳](07-frontend.md)).
**چت پشتیبانی (ویجت بازدیدکننده، در تولید غیرفعال)** — `SupportChat.jsx`، `Parts.jsx`، `useSupportChat.js`، ماژول‌های خالص `client`، `state`، `schedule` (back-off تکرار؛ بازدیدکنندگان poll می‌کنند و رشتهٔ SSE نگه نمی‌دارند)، `storage`، `token`، `turnstile` (هنگام اولین ارسال بارگذاری می‌شود)، `copy.fa.js` (همهٔ متن‌ها تا تأیید پیشنهادند)؛ سمت کارکنان `admin/SupportDesk.jsx` (زبانه کنار تیکت‌ها)، `SupportChatInbox.jsx`، `logic.js`.

## ۴۲٫۷ بخش‌های پنل ادمین (۲۴ مورد، از `SECTIONS`)

آنلاین: `dashboard`، `company-requests` (میز پشتیبانی). پشتیبانی و دانش: `support-metrics`، `product-feedback`، `knowledge`. مشتریان: `requests` (خرید)، `companies`، `users`. گزارش: `overview`، `analytics`، `activity`، `chats`، `funnel`، `search-insights`، `assistant-behavior`، `ai-cost`، `experiments` (A/B)، `audit`، `logs` (داشبوردهای Grafana). داده و عملیات: `catalog`، `dataquality`، `pipeline`، `vehicle-specs`، `system`. سند ۰۷ بخش ۷٫۴ زیرمجموعهٔ قدیمی‌تری را فهرست می‌کند؛ این فهرست ثبت‌نام فعلی است.

## ۴۲٫۸ گردش‌کارهای پیاده‌شده (سمت مرورگر)

۱. **ورود:** نام کاربری + رمز + Turnstile ← (اگر حساب شماره دارد و OTP روشن است) کد ۶ رقمی پیامکی با زمان‌سنج ۲ دقیقه و ارسال مجدد ← کوکی/توکن نشست ← هدایت به `next`. بازیابی: شناسه ← کد پیامکی ← رمز جدید (حداقل ۸ نویسه).
۲. **مرور دفترچه:** ناوگان `/browse` ← خودرو ← درخت رندرشده در سرور ← صفحهٔ برگ؛ جست‌وجوی هر خودرو با تکمیل خودکار؛ breadcrumb؛ هر بازدید یک beacon فعالیت ثبت می‌کند.
۳. **قطعات:** خودرو ← انتخاب پیکربندی (EPC) ← درخت گروه‌ها ← نقشهٔ انفجاری + جدول.
۴. **پرسش از دستیار:** انتخاب خودرو ← نوشتن علامت فارسی، کد DTC یا پرسش رویه ← پاسخ استریم با منابع، پنل شواهد، امتیازدهی.
۵. **ثبت و پیگیری تیکت:** `/requests` ← درخواست جدید (نوع، دسته، خودروی اختیاری، موضوع، توضیح، اولویت) ← پیشنهاد مقالهٔ دانش ← گفت‌وگو، وضعیت SLA، بازگشایی با پاسخ، پرسش رضایت پس از بستن.
۶. **مدیریت تیم (جایگاه ریشه):** بوم `/team` ← افزودن جایگاه ← انتخاب/ساخت کاربر (مشخصات با پیامک) ← تعیین دسترسی‌ها؛ دیگران فقط‌خواندنی؛ تحلیل و گفتگوهای دستیار در محدودهٔ دسترسی.
۷. **ادمین:** `/admin/login` (+OTP) ← هاب ← بخش‌های بالا؛ رویدادهای زنده داشبورد را به‌روز نگه می‌دارند.
۸. **چت پشتیبانی (هنگام فعال‌بودن):** ویجت شناور ← اولین پیام رشته‌ای با توکن ساخته‌شده در کلاینت می‌سازد ← polling ← پاسخ کارکنان در زبانهٔ صندوق.

## ۴۲٫۹ آزمون و ساخت

آزمون‌های واحد (`node --test`، ۲۱ فایل زیر `src/**/__tests__/`): پرامپت چت، زمینه‌ساز، اصطلاحات فارسی (با artifact تولیدشده)، خطاهای دوستانه، محتوای دفترچه، onboarding، بسته‌ها/قیمت، نشانی امن، پاک‌ساز، قواعد پشتیبانی، محتوای خودرو، client/state/schedule/token/storage/turnstile/logic چت پشتیبانی، اتصال‌دهندهٔ جریان رویداد و اشتراک‌گذاری آن. E2E مرورگر (`qa/e2e/tests`): مشخصات a11y، auth، authz، media، public، session، support و support-chat ([۳۲](32-testing-and-qa.md))؛ اجرای شبانه اکنون ۶ مورد از آن‌ها را شکست می‌دهد ([۳۸](38-implementation-status-matrix.md)، [۴۷](../47-engineering-followups.md)). نکات ساخت و مبهم‌سازی: [۰۷ بخش ۷٫۶](07-frontend.md).

</div>
