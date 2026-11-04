<!-- i18n-source: 26-auth-and-sessions.md sha256:e1a6bf4dfe2f -->
<div dir="rtl" lang="fa">

# ۲۶ — احراز هویت و نشست‌ها همان‌گونه که ساخته شده

مکمل `06-permissions-rbac.md` (چه کسی چه کاری مجاز است) و `12-security.md` (تضمین‌ها و تاریخچهٔ سخت‌سازی). این سند **رفتاری را ثبت می‌کند که در کد هست اما جایی نوشته نشده بود**، همراه با فایلی که آن را اثبات می‌کند. هر آنچه اینجاست در `origin/work` نسخهٔ `8a380f6` **[C]** است مگر برچسب دیگر.

## ۲۶٫۱ توکن‌های نشست

| | پرتال (`AuthToken`) | ادمین پلتفرم (`AdminAuthToken`) |
|---|---|---|
| کلاس پایه | `SessionTokenBase` (`api/models.py`) | همان |
| TTL بی‌کاری | ۱۴ روز | **۱۲ ساعت** |
| TTL مطلق | ۹۰ روز | **۷ روز** |
| override | `KG_TOKEN_IDLE_DAYS`، `KG_TOKEN_MAX_DAYS` (`SessionTokenBase._ttls`)، بدون نیاز به دیپلوی | `KG_ADMIN_TOKEN_IDLE_DAYS`، `KG_ADMIN_TOKEN_MAX_DAYS` |
| ذخیره‌شده به‌صورت | SHA-256 کلید؛ کلید خام یک‌بار برگردانده می‌شود | همان |
| لغزان | هر استفاده `expires_at` را به `min(last_used + idle, created + absolute)` می‌برد | همان؛ برای pingهای پس‌زمینه `touch=False` استفاده می‌شود (`X-Kg-Background: 1`) تا کنسول باز خودش را واردشده نگه ندارد |

نشست‌های پرتال به‌صورت کوکی `HttpOnly; Secure; SameSite=Lax` که بک‌اند تنظیم می‌کند (`portal._set_portal_cookie`) یا به‌صورت `Authorization: Bearer` حمل می‌شوند.

## ۲۶٫۲ جریان ورود (پرتال)

۱. `/api/auth/login/`: نام کاربری یا ایمیل + گذرواژه، به‌علاوهٔ توکن Cloudflare Turnstile که سمت سرور اعتبارسنجی می‌شود (`portal._verify_turnstile`؛ `TURNSTILE_SECRET`، اختیاری `TURNSTILE_HOSTNAMES`؛ action باید مطابق باشد). اعتبارسنجی `challenges.cloudflare.com` را فرامی‌خواند؛ در ۲۰۲۶‑۱۱‑۰۳ نبودن مسیر IPv6 این فراخوانی را حدود ۴۰ ثانیه کرد تا زمانی که ایمیج بک‌اند IPv4 را ترجیح داد (`ops/docker/backend.Dockerfile`). [D ‏Slack #kg-dev]
۲. اگر حساب تلفن ثبت‌شده دارد و `otp_enabled` است، کد پیامکی لازم است (`OtpChallenge`: TTL دو دقیقه، ارسال مجدد در همان لحظه باز می‌شود، حداکثر ۵ تلاش؛ سقف روزانه `KG_OTP_MAX_SENDS_PER_DAY`، `KG_OTP_MAX_FAILS_PER_DAY`). حساب بدون تلفن فقط با گذرواژه و Turnstile وارد می‌شود. ادمین‌ها همان جریان را دارند (`AdminOtpChallenge`، `/api/admin/verify-otp/`).
۳. `portal._issue_session` مقدار `last_login_at` را تنظیم می‌کند، توکن می‌سازد، **هر توکن دیگر کاربر را حذف می‌کند**، ردیف فعالیت `login` را می‌نویسد و رویداد زنده منتشر می‌کند.
۴. `notify.check_login_device` یک کوکی چرخان `kg_dev` را اجرا می‌کند: شناسهٔ دستگاه بازنشستهٔ (کپی‌شده) به مالک پیامک می‌دهد و همهٔ نشست‌های دیگر را خارج می‌کند؛ دستگاه ناشناخته به مالک پیامک می‌دهد (مگر نخستین دستگاه حساب باشد).

## ۲۶٫۳ یک نشست فعال برای هر حساب

ورود جدید هر مرورگر دیگر را خارج می‌کند. با `7200db7` (۲۰۲۶‑۱۰‑۲۱، «content protection ... one session per account») معرفی شد، بخشی از بستهٔ ضد-scraping همراه با `contentguard.py` و `shield.py`؛ بدون ارجاع به issue push شد. کلید قطع: `KG_SINGLE_SESSION=0`؛ به‌صورت پیش‌فرض روشن است. تست‌ها: `SingleSessionTests` در `test_contentguard.py` و `test_qa_auth.py`. [C، تاریخچه git]

## ۲۶٫۴ دروازهٔ ادمین

`admin_auth.require_admin_token` می‌پذیرد (الف) توکن نشست ادمین پلتفرم، یا (ب) `KG_ADMIN_TOKEN` ثابت **فقط برای فراخوانی مستقیم loopback بدون هدرهای پراکسی** (`_from_server_itself`)، تا اسکریپت‌ها و cron روی میزبان کار کنند و اینترنت نتواند از رازی ثابت و بدون 2FA استفاده کند. توکن loopback هرگز «شخص» برای RBAC چت پشتیبانی نیست. `vncauth.py` صفحهٔ مرورگر مورد استفادهٔ خزندهٔ TIS (`/kg-vnc/`) را با کوکی امضاشدهٔ ۲ ساعته و محدود به مسیر که nginx با `auth_request` بررسی می‌کند دروازه‌بندی می‌کند.

## ۲۶٫۵ حفاظت محتوا (احراز هویت نیست، اما نشست‌ها کلید آن‌اند)

`shield.py` (`KG_SHIELD=1` + `KG_SHIELD_SECRET`) بارهای سند را با کلیدهای هر نشست و هر epoch رمزگذاری می‌کند و درخواست‌های امضاشدهٔ یک‌بارمصرف را الزامی می‌کند؛ سرور Next.js همان کلیدها را مشتق می‌کند (`utils/shieldServer.js`). `contentguard.py` آستانه‌های صفحه/رسانه را بالا می‌برد (`KG_CG_PAGE_WARN/BLOCK`، `KG_CG_MEDIA_WARN/BLOCK`). اینکه shield در تولید فعال است **[U]** است (env خوانده نشد).

## ۲۶٫۶ شکاف‌های شناخته‌شده

- **بازیابی** حساب با تأیید پیامکی برای کاربران پرتال وجود دارد (`api/auth/recover/start|reset`، محدود نرخ، تست‌شده در `api/test_recover.py`). هیچ route‌ای برای کاربر واردشده جهت **تغییر گذرواژهٔ خودش** نیست و برای ادمین‌های پلتفرم اصلاً چیزی نیست [C: ورودی تغییر گذرواژه در `api/urls.py` نیست]. سند ۱۲ بازیابی را بسته‌شده فهرست می‌کند.
- بدون توکن CSRF؛ تعدیل‌ها `SameSite=Lax` و `OriginGuardMiddleware` هستند (`KG_ORIGIN_GUARD=0` غیرفعالش می‌کند). سند ۲۱.
- `KG_TRUST_XFF` کنترل می‌کند آیا `X-Forwarded-For` برای IP کلاینت مورد اعتماد است؛ فقط پشت زنجیرهٔ Cloudflare/nginx درست است [C ‏`ratelimit.py`؛ مقدار تولید **U**].

</div>
