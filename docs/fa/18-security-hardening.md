<!-- i18n-source: 18-security-hardening.md sha256:3856cdb33cd5 -->
<div dir="rtl" lang="fa">

# ۱۸ — سخت‌سازی امنیت: رازها، محدودسازی نرخ، WAF، پایش خطا

ساخته‌شده در ۲۰۲۶‑۰۸‑۰۵. سه شکاف را پوشش می‌دهد: رازهایی که هرگز چرخانده نشده بودند و برای همه خواندنی بودند، نبود محدودسازی نرخ در لبه، و نبود WAF یا پایش خطا.

> **سند تاریخی.** در ۲۰۲۶‑۰۸‑۰۵ نوشته شد، وقتی سایت با HTTP ساده و با IP سرو می‌شد. از آن زمان سایت روی TLS سرو می‌شود (گواهی مبدأ Cloudflare؛ [12-security.md](12-security.md) مورد ۱ بسته شد، [33-system-design.md](33-system-design.md))، پس جمله‌هایی مانند «بدون TLS» یا اینکه سایت به‌صورت `http://103.75.197.155/` منتشر شده وضعیت همان تاریخ را شرح می‌دهند، نه امروز.

مرتبط: [05-api-reference](05-api-reference.md)، [12-security](12-security.md) (نقاط پایانی احراز هویت)، [11-operations-deployment](../11-operations-deployment.md) (واحدهای systemd، timerها).

---

## ۱. مدیریت کلید و چرخش توکن

### رازها در حالت ذخیره

`.env.prod`، `.env.production`، `db.sqlite3` و هر نسخهٔ پشتیبانشان اکنون با حالت **۰۶۰۰ و فقط root** هستند. پیش از آن ۰۶۴۴ بودند — برای هر حساب محلی روی جعبه‌ای با چند حساب خواندنی — و هرکدام کلید راز Django، توکن ادمین و کلید API پولی Metis را داشتند.

همچنین قفل شدند: ۱۷ نسخهٔ پراکنده زیر `/root` (پشتیبان‌های قدیمی دیپلوی، درخت staging با نام `/root/kgtest`) و ۷ فایل `db.sqlite3.bak*` در `KG_backend/` که هرکدام توکن‌های نشست زنده و هش گذرواژه را به‌صورت متن ساده داشتند.

### توکن‌های نشست هش‌شده و منقضی‌شونده‌اند

`AuthToken` و `AdminAuthToken` پیش‌تر مقدار bearer را **به‌صورت متن ساده** ذخیره می‌کردند و **هرگز منقضی نمی‌شدند**. پس نسخه‌ای از `db.sqlite3` — که مدتی در تاریخچهٔ git بود — مجموعه‌ای از نشست‌های دائمی و آمادهٔ استفاده بود.

اکنون (migration با نام `0017_hash_session_tokens`، کلاس پایه مدل `SessionTokenBase`):

| | کاربر پرتال | ادمین پلتفرم |
|---|---|---|
| ذخیره‌شده | ‏`sha256(raw)` در `key_hash` | همان |
| timeout بی‌کاری | ۱۴ روز | ۱۲ ساعت |
| سقف مطلق | ۹۰ روز | ۷ روز |

* `issue(owner)` نمونه را با مقدار خام الصاق‌شده به‌صورت `.key` برمی‌گرداند، **فقط یک صفت درون‌حافظه** — `key` دیگر فیلد مدل نیست، پس هر محل فراخوانی موجود (`token.key` بلافاصله پس از issue) کار می‌کند در حالی که پایگاه داده هرگز راز را نمی‌بیند.
* `resolve(raw)` انقضا را درون query اعمال می‌کند، پس ردیف کهنه هرگز resolve نمی‌شود.
* `touch()` پنجرهٔ بی‌کاری را به جلو می‌لغزاند، با کلمپ به سقف مطلق، و حداکثر هر ۵ دقیقه یک‌بار برای هر توکن می‌نویسد (`TOUCH_INTERVAL`) — در هر درخواست احرازشده اجرا می‌شود.
* TTLها با env قابل override‌اند: `KG_TOKEN_IDLE_DAYS`، `KG_TOKEN_MAX_DAYS`، `KG_ADMIN_TOKEN_IDLE_DAYS`، `KG_ADMIN_TOKEN_MAX_DAYS`.

migration ۸۹ ردیف متن ساده موجود را **حذف می‌کند** به‌جای هش‌کردن دوباره: هش دوباره مقادیر bearer از‌پیش‌نشت‌کرده را کارا نگه می‌داشت، که دقیقاً همان مشکلی است که برای پایان‌دادنش وجود دارد. همه یک بار دیگر وارد شدند.

### ابزار چرخش

<div dir="ltr">

```bash
# Report ages and fingerprints — never prints a secret value.
manage.py rotate_secrets --status

# Rotate. The outgoing Django key is pushed onto DJANGO_SECRET_KEY_FALLBACKS so
# signatures already in flight keep verifying for one window.
manage.py rotate_secrets --what django-key
manage.py rotate_secrets --what admin-token --print-new
manage.py rotate_secrets --what all --prune-fallbacks 1
# OUTDATED (2026-11-04): the backend is a container now and `kgkg-backend.service` is retired (it crash-looped beside the
# container on 2026-11-02). Reload the env with `ops/deploy/deploy.sh --reload` run by the owner; see docs/25-ops-inventory.md.
systemctl restart kgkg-backend        # nothing is live until this runs  [do not run on the current host]
```

</div>

فایل env **اتمی** بازنویسی می‌شود (فایل موقت + `os.replace`) با حالت ۰۶۰۰، با حفظ کامنت‌ها و کلیدهای نامرتبط، همراه پشتیبان تاریخ‌دار.

<div dir="ltr">

```bash
manage.py rotate_tokens                     # report
manage.py rotate_tokens --prune             # delete expired (daily timer)
manage.py rotate_tokens --revoke-user NAME  # incident response
manage.py rotate_tokens --revoke-admin
manage.py rotate_tokens --revoke-all --yes
```

</div>

`kgkg-token-prune.timer` هرس را روزانه اجرا می‌کند.

**هر دو راز تولید در ۲۰۲۶‑۰۸‑۰۵ چرخانده شدند** و رد توکن قدیمی ادمین (401) و کارکردن توکن جدید (200) راستی‌آزمایی شد.

### تنظیمات

`SECRET_KEY_FALLBACKS` از `DJANGO_SECRET_KEY_FALLBACKS` خوانده می‌شود. هدرهای امنیتی که روی HTTP ساده کار می‌کنند روشن‌اند (`SECURE_CONTENT_TYPE_NOSNIFF`، `X_FRAME_OPTIONS=DENY`، `SECURE_REFERRER_POLICY`، `SESSION_COOKIE_HTTPONLY`). گروه وابسته به TLS (`SECURE_SSL_REDIRECT`، کوکی‌های secure، HSTS) پشت `DJANGO_SECURE_SSL=1` است و **خاموش**، چون این استقرار فقط پورت ۸۰ را سرو می‌کند — روشن‌کردنشان بدون گواهی سایت را در redirect-loop می‌اندازد.

---

## ۲. محدودسازی نرخ (nginx)

`/etc/nginx/conf.d/kgkg-limits.conf` منطقه‌ها را تعریف می‌کند؛ پیکربندی سایت آن‌ها را برای هر location اعمال می‌کند.

> **مقادیر تا ۲۰۲۶‑۰۸‑۰۵.** منطقه‌ها اکنون در مخزن هستند (`ops/nginx/kgkg-limits.conf`) و از آن زمان تنظیم شده‌اند؛ در ۲۰۲۶‑۱۱‑۰۴ فایل `kg_general` ‏۳۰ r/s، `kg_static` ‏۱۰۰ r/s، `kg_api` ‏۲۰ r/s، `kg_auth` ‏۳۰ r/min، `kg_chat` ‏۶۰ r/min و `kg_admin` ‏۲۰ r/s (وضعیت 429) را تعریف می‌کند. برای اعداد فعلی آن فایل را بخوانید، نه این جدول را.

| منطقه | نرخ | burst | اعمال روی |
|---|---|---|---|
| `kg_static` | ‏۱۰۰ r/s | ۳۰۰ | `/kg-api/media/`، `/_next/static/` |
| `kg_general` | ‏۳۰ r/s | ۱۲۰ | هر چیز دیگر روی فرانت‌اند |
| `kg_api` | ‏۲۰ r/s | ۱۰۰ | `/kg-api/` |
| `kg_auth` | ‏۳۰ r/min | ۱۰ | نقاط پایانی ورود، `/kg-api/api/invite/` |
| `kg_chat` | ‏۶۰ r/min | ۱۵ | `/api/chat` (هر فراخوانی در Metis هزینه دارد) |
| `kg_admin` | ‏۶۰ r/min | ۴۰ | `/kg-api/api/admin/` |
| `kg_conn` | ۶۰ هم‌زمان | — | به‌ازای هر IP |
| `kg_sse` | ۸ هم‌زمان | — | فقط جریان SSE |

ردها **429** برمی‌گردانند و در سطح `warn` لاگ می‌شوند که jail مربوط به fail2ban آن را می‌خواند.

**دو چیز که حیاتی‌اند و به‌راحتی شکسته می‌شوند:**

۱. **معافیت loopback.** `NEXT_PUBLIC_API_BASE` نشانی *عمومی* است، پس هر رندر سمت سرور از نشانی خود این ماشین به nginx برمی‌گردد. جفت `geo`/`map` در بالای فایل محدودیت‌ها به 127.0.0.1، ::1 و 103.75.197.155 کلید محدودیت خالی می‌دهد که محدودیت را غیرفعال می‌کند. بدون آن، همهٔ ترافیک SSR یک سطل مشترک دارد و کل سایت یک‌باره throttle می‌شود.
۲. **`proxy_pass` برای هر location است، نه در snippet مشترک.** nginx URI را با جایگزینی بخش مطابق location با مسیر proxy_pass بازنویسی می‌کند، پس یک مقدار مشترک در `location /kg-api/` معنایی متفاوت از `location = /kg-api/api/auth/login/` می‌داشت (دومی کل URI را به `/` بازنویسی می‌کرد). `snippets/kgkg-backend-proxy.conf` **فقط هدرها** را دارد؛ هر location هدف خودش را بیان می‌کند.

محدودکنندهٔ درون‌فرایندی (`api/ratelimit.py`) می‌ماند — معناشناسی هر نقطهٔ پایانی را نگه می‌دارد. nginx محافظ حجمی است که هم یک‌بار می‌شمارد نه یک‌بار برای هر worker گانیکورن.

---

## ۳. WAF — ModSecurity 3 + OWASP CRS 3.3.5

`modsecurity on` در کل سایت، `off` در دو location استاتیک. قواعد از `/etc/nginx/modsecurity/main.conf` بارگذاری می‌شوند:

<div dir="ltr">

```
modsecurity-base.conf   # engine settings (tailored from the shipped file)
crs-setup.conf          # stock
kgkg-before-crs.conf    # paranoia level
<CRS rules>             # 926 rules
kgkg-after-crs.conf     # our exclusions, by rule id
```

</div>

تغییرات پیکربندی پایه نسبت به پیش‌فرض تحویلی: `SecRuleEngine On`، `SecStatusEngine Off` (بدون تماس با بیرون)، `SecResponseBodyAccess Off` (صفحات دفترچه به‌صورت JSON سرو می‌شوند که به‌هرحال اسکن نمی‌شود، و این جعبه bge-m3 هم اجرا می‌کند)، بخش‌های ممیزی `ABIJDFHZ`، پوشه‌های موقت/داده از `/tmp` بیرون برده شد.

### سطح paranoia برابر ۱، عمداً

ترافیک عادی اینجا متن آزاد فارسی و مسیرهای دفترچه پر از `&`، `/`، `:`، پرانتز و U+2044 است — دقیقاً شکل‌هایی که PL2+ مشکوک می‌خواند. PL1 تزریق واقعی را می‌گیرد با نرخ مثبت کاذبی که می‌تواند واقعاً در حالت مسدودکننده اجرا شود.

### استثناها و چرایی هرکدام

* **920271** (نویسه‌های غیرقابل‌چاپ) — حذف شد. عبارت‌های پرسش فارسی و U+2044 (اسلش کسری که parser برای رمزگذاری `/` درون عنوان بخش‌ها استفاده می‌کند) همه طبق تعریف این قاعده «غیرقابل‌چاپ»اند. بررسی‌های null-byte/کنترل در 920270 روشن می‌ماند.
* **920350** (IP عددی در هدر Host) — حذف شد. در اجرای تشخیص روی **۱۱۲ از ۱۱۲** درخواست مشروع فعال شد، چون سایت به‌صورت `http://103.75.197.155/` بدون نام DNS منتشر شده است. در سطح WARNING (3) در برابر آستانهٔ ۵ تنها چیزی را مسدود نمی‌کند، اما هر نمایش صفحهٔ عادی را روی ۳ از ۵ می‌گذاشت، پس هر قاعدهٔ مرزی دیگری یک کاربر واقعی را ۴۰۳ می‌کرد. **وقتی سایت نام دامنه گرفت دوباره فعالش کنید.**
* **10100/10101/10102** — امتیازدهی SQLi/XSS فقط از *آرگومان‌های متن آزاد نام‌دار* در search/assist/diagnose، `/api/chat` و مسیرهای `seg` دفترچه حذف شد. یک مکانیک قانوناً می‌نویسد `P0171 or P0174 - select which sensor`. این نقاط پایانی دروازهٔ ورود و محدودیت نرخ دارند و لایهٔ RAG پارامتر bind شده استفاده می‌کند. هر آرگومان دیگر در همان درخواست همچنان بازرسی می‌شود.
* **10103** — بازرسی بدنهٔ درخواست برای آپلودهای pipeline/ingest ادمین خاموش شد (ZIPهای چند صد مگابایتی دفترچه)، که پشت امتیازدارترین دروازهٔ جعبه‌اند.

### روال استفاده‌شده

در `DetectionOnly` مستقر شد، کل سایت به‌علاوهٔ payloadهای حمله اجرا شد، لاگ ممیزی خوانده شد، استثناهای بالا نوشته شد، تأیید شد **هیچ درخواست مشروعی از آستانهٔ anomaly رد نشد**، سپس به `On` تغییر یافت و دوباره راستی‌آزمایی شد.

پس از هر ارتقای CRS آن روال را تکرار کنید:

<div dir="ltr">

```bash
sed -i 's/^SecRuleEngine .*/SecRuleEngine DetectionOnly/' \
    /etc/nginx/modsecurity/modsecurity-base.conf
nginx -t && systemctl reload nginx && : > /var/log/nginx/modsec_audit.log
# ...drive real traffic, then:
grep -o '\[id "[0-9]*"\].*\[msg "[^"]*"\]' /var/log/nginx/modsec_audit.log \
  | sed -E 's/\[id "([0-9]+)"\].*\[msg "([^"]*)"\].*/\1 \2/' | sort | uniq -c | sort -rn
```

</div>

### fail2ban

| jail | می‌خواند | فعال می‌شود در | مسدودسازی |
|---|---|---|---|
| `sshd` | journal | ۵ | ۲ ساعت |
| `nginx-limit-req` | error.log در nginx | ۳۰ در ۵ دقیقه | ۱ ساعت |
| `kgkg-modsecurity` | error.log در nginx | ۸ در ۱۰ دقیقه | ۶ ساعت |
| `kgkg-auth` | access.log در nginx | ۲۵ بار 401 در ۳۰ دقیقه | ۴ ساعت |

مسدودسازی‌ها تشدید می‌شوند (`bantime.increment`، حداکثر ۱ هفته). **`ignoreip` شامل 127.0.0.1، ::1 و 103.75.197.155 است — ورودی خود-میزبان الزامی است**، چون سرور Next دوباره به nginx فراخوانی می‌زند. همچنین **IP ایستگاه کاری ادمین** را فهرست می‌کند که عمداً اینجا نوشته نشده: این مخزن عمومی است و نشانی‌ای که `ignoreip` از fail2ban معاف می‌کند فقط به کار کسی می‌آید که می‌خواهد مسدود نشود. مقدار زنده در `/etc/fail2ban/jail.local` روی میزبان است؛ اگر IP دفتر عوض شد آن ورودی را بازبینی کنید.

---

## ۴. پایش خطا — GlitchTip خودمیزبان

`/opt/glitchtip` (docker compose، واحد `glitchtip.service`، فعال در boot). Postgres + Redis + web + worker. پروتکل سیمی Sentry را می‌فهمد، پس کلاینت‌های استاندارد `sentry-sdk` کار می‌کنند — اما هیچ چیز از ماشین بیرون نمی‌رود، که مهم است چون بار خطا اینجا می‌تواند محتوای دفترچه فارسی مشتری را حمل کند.

**فقط روی 127.0.0.1:8010 bind شده.** عمداً از طریق nginx منتشر *نمی‌شود*: این جعبه TLS ندارد و گذاشتن فرم ورود یک داشبورد خطا روی HTTP ساده بقیهٔ این کار را خنثی می‌کرد. از طریق تونل SSH دسترسی بگیرید:

<div dir="ltr">

```bash
ssh -L 8010:127.0.0.1:8010 root@103.75.197.155
# then open http://127.0.0.1:8010/ and sign in with the GlitchTip admin
# account. Neither the account nor the file holding its password is named
# here, for the same reason as the fail2ban entry above; both are on the host.
```

</div>

وقتی ۴۴۳ وجود داشت درست منتشرش کنید.

پروژه‌ها: `kgkg-backend` (id ‏۱)، `kgkg-frontend` (id ‏۲). DSNها در فایل‌های `.env` مربوط هستند. نگهداشت ۳۰ روز؛ لاگ کانتینرها با سقف ۲۰ مگابایت × ۳.

### دو تلهٔ سازگاری، هر دو بی‌صدا

۱. **SDK پایتون باید به gzip قفل شود.** sentry-sdk نسخهٔ 2.x هر وقت ماژول `brotli` قابل import باشد (اینجا هست، تراگذری) خودکار Brotli را برمی‌گزیند و GlitchTip نسخهٔ 4.1.3 نمی‌تواند آن را باز کند — با `400 {"detail": "Cannot parse request body"}` پاسخ می‌دهد که SDK در سطح DEBUG لاگ و رها می‌کند. برنامه ابزاربندی‌شده به نظر می‌رسد و حتی یک خطا نمی‌رسد. با `_experiments={'transport_compression_algo': 'gzip'}` اصلاح شد (گزینهٔ سطح‌بالا *نیست*).
۲. **SDK جاوااسکریپت قالب DSN خود GlitchTip را رد می‌کند.** `DSN_REGEX` آن کلید عمومی را با `\w+` تطبیق می‌دهد که خط تیرهٔ کلیدهای UUID در GlitchTip را کنار می‌گذارد. GlitchTip شکل ۳۲ هگزای بدون خط تیره را به همان UUID تبدیل می‌کند، پس DSN فرانت‌اند از آن استفاده می‌کند.

### چه چیزی گزارش می‌شود

* **Django** — `DjangoIntegration` (استثناهای درخواست مدیریت‌نشده) به‌علاوهٔ `LoggingIntegration` با `event_level=ERROR`.
* **Next.js** — `@sentry/node` از طریق `src/instrumentation.ts` (`register()` + `onRequestError`). کامپوننت‌های سرور، route handlerها و `/api/chat` را پوشش می‌دهد. `@sentry/nextjs` عمداً کنار گذاشته شد: از طریق build plugin کار می‌کند که پشتیبانی Next 16 آن هنوز در حال تثبیت است و hook پایدار ابزاربندی به plugin نیاز ندارد. **JS سمت مرورگر ابزاربندی نشده** — نیازمند route تونل است چون GlitchTip فقط‌loopback است.

`send_default_pii=False` همه‌جا، به‌علاوهٔ پاک‌سازی `before_send` در هر دو سمت.

> پاک‌سازی **جراحی است، نه پیمایش کور کل رویداد**. نسخهٔ قبلی پاک‌سازی بازگشتی روی کل دیکشنری رویداد اجرا می‌کرد؛ رویدادهای Sentry عمیق‌تر از سقف بازگشت تودرتو هستند، پس frameهای stack به‌صورت رشتهٔ literal با نام `'<max-depth>'` درآمدند و GlitchTip هر رویداد را با 400 رد کرد. فقط فیلدهای message/exception-value/extra/tags/request را لمس کنید.

### لاگ‌های ساختاریافته

`KG_backend/KG_backend/jsonlog.py` — یک شیء JSON در هر خط، زمان UTC.

* `/var/log/kgkg/app.jsonl` — همه‌چیز در `KG_LOG_LEVEL` (پیش‌فرض INFO)
* `/var/log/kgkg/error.jsonl` — WARNING و بالاتر

هر دو روزانه می‌چرخند و ۳۰ روز نگه داشته می‌شوند (`/etc/logrotate.d/kgkg`)، با `WatchedFileHandler` نوشته می‌شوند پس چرخش ری‌استارت نمی‌خواهد. کلیدهای شبیه اعتبارنامه و مقادیر درون‌خطی `token=`/`Bearer` پیش از نوشتن حذف (redact) می‌شوند. `QuietInTests` خروجی را زیر اجراکنندهٔ تست خاموش می‌کند که عمداً مسیرهای 4xx/5xx را تمرین می‌کند.

<div dir="ltr">

```bash
jq -c 'select(.level=="ERROR")' /var/log/kgkg/error.jsonl | tail -20
```

</div>

---

## ۵. راستی‌آزمایی (۲۰۲۶‑۰۸‑۰۵)

* مجموعهٔ بک‌اند: **۳۰۵ تست، همه موفق** (۲۶۵ از قبل + ۴۰ جدید در `api/test_security.py`).
* probe خارجی از IP غیرمعاف: **۴۴/۴۴** — هدرهای امنیتی، احراز، دروازه‌بندی محتوا، شش probe مثبت کاذب فارسی/RTL، ده payload حمله مسدود (403)، چهار UA اسکنر مسدود، محدودسازی نرخ، SSE، دروازهٔ ادمین.
* پیمایش کل سایت: **۳۹/۳۹** — هر route فرانت‌اند، سطح API بک‌اند، کاتالوگ، پیمایش عمیق دفترچه، search/assist/diagnose به فارسی و انگلیسی، SSE، دارایی‌های رسانه، ابطال با خروج.
* تصاویر رسانه سرو می‌شوند (200، `image/png`)؛ توکن‌های نشست ادمین روی هر سه نقطهٔ پایانی ادمین از nginx + WAF + محدودسازی نرخ می‌گذرند.

### مشکلات شناخته‌شده یافت‌شده، رفع‌نشده

* **`/admin/<anything>` ‏500 برمی‌گرداند.** از قبل بود (ساعت‌ها پیش از این کار در لاگ‌های دسترسی). catch-all با نام `[brand]/[year]` مسیرهای دوبخشی ناشناخته را می‌بلعد — `/admin/config` می‌شود brand=`admin`، year=`config` — و `JSON.parse` روی پاسخ خطای HTML می‌شکند. **هیچ `not-found.tsx` یا `error.tsx`** در `src/app` نیست. نشت اطلاعات نیست (بدنه صفحهٔ خطای استاندارد تولید Next است، بدون stack و مسیر)، اما باید 404 بدهد. GlitchTip اکنون آن را به‌صورت `SyntaxError: Unexpected token '<'` ثبت می‌کند.
* **فرایند staging یتیم.** PID 467246، یک `next-server` دستی از یک نشست SSH ۱۸ روز پیش، شنونده روی `*:3123` با نسخه‌ای از کلید API Metis در محیطش. از بیرون در دسترس نیست (ufw فقط 22/80/443/3389 را می‌پذیرد) و تولید نیست، اما باید کشته شود.
* **بدون TLS.** بزرگ‌ترین مواجهه‌ٔ باقی‌مانده: اعتبارنامهٔ ادمین، توکن‌های نشست و همهٔ محتوای پولی به‌صورت متن ساده در سیم می‌روند. هر چیز بالا طوری نوشته شده که وقتی ۴۴۳ وجود داشت تمیز روشن شود — `DJANGO_SECURE_SSL=1`، فعال‌سازی دوبارهٔ CRS 920350، انتشار GlitchTip.

## ۶. بازگشت

پشتیبان‌های این کار: `/root/sec_hardening_bak_1785964985/` (منابع بک‌اند، کل `/etc/nginx`، هر دو فایل env، `db.sqlite3` و `.next.bak`)، به‌علاوهٔ `/root/db_premigrate_0017.sqlite3` که بلافاصله پیش از migration توکن گرفته شد.

</div>
