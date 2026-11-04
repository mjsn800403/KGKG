<!-- i18n-source: 02-architecture.md sha256:4e09fe534fc3 -->
<div dir="rtl" lang="fa">

# ۰۲ — معماری

## توپولوژی زمان اجرا (میزبان واحد)

<div dir="ltr">

```
                         nginx :80/:443  (TLS 1.2/1.3, Cloudflare origin certificate; see 33-system-design.md)
        ┌───────────────────────────┼───────────────────────────────┐
        │ /kg-api/media/*           │ /kg-api/*                     │ /*
        │ alias → static_warehouse/ │ proxy → gunicorn :8000        │ proxy → Next.js :3000
        │ (30d immutable cache)     │ (+ dedicated SSE location:    │ (websocket upgrade kept
        │                           │  /kg-api/api/events/stream/   │  for HMR/dev parity)
        │                           │  proxy_buffering off, 3600s)  │
        ▼                           ▼                               ▼
   Disk (nginx)              Django 5.2 (KG_backend)          Next.js 16 (kg_frontend)
                             ├─ PostgreSQL 16 `kgkg` ───── users/RBAC/companies/rollups/events/jobs
                             │    (since 2026-10-29; db.sqlite3 frozen as the way back)
                             ├─ PostgreSQL `kgkg_vec` ───── manual content of 222 cars, one schema per car (docs/23-data-layer.md, ADR-0007)
                             ├─ Database_warehouse/_parts/*.db ─ one SQLite per parts-only vehicle (15 on 2026-11-03)
                             │    ├─ _rag/index.rag.db ──── unified deduplicated semantic index (~2.3GB)
                             │    ├─ _rag/diag/*.db ─────── per-vehicle diagnostic sidecars
                             │    ├─ _rag/feedback.db ───── ratings/pins/click log (assistant HITL)
                             │    └─ _quarantine/ ────────── corrupt/duplicate files (moved, never deleted)
                             └─ static_warehouse/<car>/ ─── manual images (SVG/PNG), served by nginx

   Backend and frontend run as Docker containers (kgkg-backend:<sha>, kgkg-frontend:<sha>; host network, loopback only)
   started by ops/deploy/deploy.sh (ADR-0003). Host systemd: nginx, kgkg-hostjobs, timers (alerts 5m, pipeline 5m, detect 30s,
   watchdog, outbox, qa-nightly) and transient kgkg-pipeline-job<id>-a<n> units (detached pipeline workers).
   The pre-container units kgkg-backend.service / kgkg-frontend.service are historical; whether they still exist on the host is [U].
```

</div>

سرور Next.js هم فرانت‌اند SSR است و هم یک پراکسی نازک API برای دقیقاً یک route: `/api/chat` (کلید Metis را سمت سرور نگه می‌دارد). هر چیز دیگری که مرورگر صدا می‌زند از طریق `/kg-api/…` به Django می‌رود (متغیر `NEXT_PUBLIC_API_BASE`). صفحات SSR مستقیم Django را روی `127.0.0.1:8000` (`BACKEND_URL`) فرامی‌خوانند و توکن پرتال را از کوکی هم‌سایت ارسال می‌کنند.

## پشته

| لایه | فناوری (نسخه‌ها از `package.json` و `ops/docker/backend-requirements.lock`، ۲۰۲۶‑۱۱‑۰۴) | نکات |
|---|---|---|
| فرانت‌اند | Next.js 16.4.3، React 19.2.4، `motion` ^12.42 | App Router؛ JS به‌علاوهٔ چند فایل TS؛ Tailwind v4 حاضر است اما استایل‌دهی در `globals.css` دستی است (حدود ۲۶۵۰ خط، متغیرهای CSS + `data-theme`) |
| بک‌اند | Django 5.2.17، gunicorn 26 (gthread) | بدون DRF — viewهای ساده با `JsonResponse`، `@csrf_exempt` + احراز هویت با توکن |
| پایگاه‌های داده | PostgreSQL 16 (داده پرتال `kgkg`؛ محتوای دفترچه خودرو `kgkg_vec` با یک schema برای هر خودرو) + SQLite (کاتالوگ خودروهای فقط‌قطعات، ایندکس RAG با `sqlite-vec`، پایگاه‌های جانبی کوچک) | داده پرتال: `KG_DB_ENGINE=postgres` از ۲۰۲۶‑۱۰‑۲۹. محتوای خودرو: `api/cardb.py` یا اتصال به فایل SQLite برمی‌گرداند یا، برای خودروهای موجود در `KG_CARDB_PG`/`public.car_dbs`، اتصال PostgreSQL (`api/cardb_pg.py`). نقشهٔ کامل: [23-data-layer.md](../23-data-layer.md)؛ رکورد تصمیم: ADR-0007 (Proposed) |
| Embedding | bge-m3 (sentence-transformers 5.6.0، torch 2.12.1 CPU) | کاملاً آفلاین: کش HF در `/root/.cache/huggingface`، `HF_HUB_OFFLINE=1` |
| PDF | WeasyPrint 70 + فونت‌های Vazirmatn همراه | گزارش‌های تیم به فارسی/RTL |
| LLM | Metis (api.metisai.ir، پولی، خارجی) | فقط بازنویسی؛ کلید در env سرور فرانت‌اند است |
| پراکسی | nginx 1.24 | gzip، alias رسانه، عبور SSE |

## اصول طراحی («چرا»ی پشت شکل سیستم)

۱. **یک خودرو = یک مخزن محتوای تغییرناپذیر.** تقسیم محتوا از روی طراحی: انزوای هر خودرو، موازی‌سازی بدیهی، بدون migration شمای مشترک برای تغییر محتوا. امروز مخزن یک خودروی دارای دفترچه یک schema در PostgreSQL پایگاه `kgkg_vec` است (مسیر خواندن فقط query است) و مخزن خودروی فقط‌قطعات یک فایل SQLite فقط‌خواندنی زیر `_parts/` است؛ `api/cardb.py` فایل‌های SQLite را کاملاً فقط‌خواندنی با یک LRU pool برای هر thread باز می‌کند (mmap، کش صفحهٔ ۱۶ مگابایتی، busy timeout، بازگشایی خودکار هنگام جایگزینی فایل). *تاریخچه:* طراحی اولیه (ADR-0001) یک فایل SQLite برای هر خودرو و برای همه‌چیز بود؛ تغییر به schemaهای PostgreSQL به‌صورت گذشته‌نگر در ADR-0007 ثبت شده است که دلیل و تاریخ آن مشخص نیست.
۲. **فرادادهٔ تجاری در یک پایگاه رابطه‌ای.** همهٔ مدل‌های Django مستقل از موتورند. تولید PostgreSQL 16 (پایگاه `kgkg`، از ۲۰۲۶‑۱۰‑۲۹) را اجرا می‌کند؛ SQLite پیش‌فرض توسعه و فایل منجمدِ تولید قبلی است.
۳. **داده مشتق‌شده دورریختنی است.** هر چیز زیر `_rag/` (ایندکس، diag) و گزارش‌های ممیزی از مخزن‌های محتوای خودرو قابل بازسازی است (بازخورد در `_rag/feedback.db` داده کاربر است، نه مشتق). حذف `_rag/` سایت را به مرور دستی دفترچه تنزل می‌دهد — هرگز آن را خراب نمی‌کند.
۴. **تا وقتی نیاز اندازه‌گیری نشده زیرساخت جدید نیاوریم.** گذرگاه SSE جدولی در پایگاه داده اصلی است (مدل `Event`؛ هنگام نوشتن این متن SQLite بود، از ۲۰۲۶‑۱۰‑۲۹ PostgreSQL با نام `kgkg`) چون مجموعهٔ فرایندها (۳ worker گانیکورن + worker جداشدهٔ pipeline) دقیقاً یک رسانهٔ مشترک و پایدار دارد و Redis ندارد. محدودکنندهٔ نرخ (`api/ratelimit.py`) شمارنده‌هایش را در یک فایل کوچک SQLite نگه می‌دارد که worker‌های یک کانتینر مشترکاً استفاده می‌کنند (`KG_RL_STORE`، پیش‌فرض `/tmp/kg_ratelimit.sqlite3`، پس با جایگزینی کانتینر صفر می‌شود) و اگر آن فایل قابل استفاده نباشد به یک پنجرهٔ درون‌فرایندی برمی‌گردد. هر یک از این قطعات محدودهٔ عملکرد و مسیر جایگزینی خود را مستند می‌کند (← «مسیر مقیاس» پایین).
۵. **مجوزدهی در پایین‌ترین لایه‌ای است که محتوا سرو می‌کند.** دسترسی هر خودرو هم در viewهای Django بررسی می‌شود و هم به‌صورت فهرست مجاز (`allowed_cars`) در بازیابی RAG عبور داده می‌شود، تا نتیجهٔ کش‌شده یا بین‌خودرویی هرگز محتوای نخریده را فاش نکند (← اسناد ۰۶ و ۰۸).
۶. **کار سنگین هرگز سرویس‌دهی را مسدود نمی‌کند.** ساخت embedding/diag در یک واحد گذرای systemd جداشده با اولویت CPU/IO پایین اجرا می‌شود؛ پیشرفت از روی مصنوعات (تعداد بردارها، فایل‌های sidecar) استخراج می‌شود تا خرابی هرگز به پنل ادمین دروغ نگوید.

## کارایی مسیر درخواست

- فهرست کاتالوگ/برند: کش درون‌فرایندی ۶۰ ثانیه؛ بررسی وجود فایل برای هر خودرو با TTL کش می‌شود (`cardb.ready_path`) تا فهرست‌ها در هر درخواست کل ناوگان را `stat()` نکنند.
- breadcrumb: برای هر صفحه یک CTE بازگشتی، نه N query.
- پایگاه اصلی: روی PostgreSQL (تولید) MVCC معمول؛ تنظیمات WAL + `IMMEDIATE` + busy-timeout ۲۰ ثانیه که در ادامه آمده برای پیش‌فرض توسعهٔ SQLite و فایل منجمد تولید قبلی است — خواننده‌ها هرگز روی flush متریک‌ها یا نوشتن فعالیت مسدود نمی‌شوند.
- gunicorn با `gthread` (۳×۸): خواندن پایگاه داده و رسانه I/O-bound است؛ thread‌ها هم‌زمانی را بدون چندبرابرکردن مدل embedding حدود ۲٫۳ گیگابایتی افزایش می‌دهند (در هر فرایند یک‌بار بارگذاری می‌شود).
- nginx تصاویر دفترچه را مستقیم از دیسک با کش ۳۰ روزهٔ immutable سرو و JSON را gzip می‌کند.
- middleware متریک‌ها در حافظه تجمیع و rollupهای دسته‌ای را flush می‌کند — صفر نوشتن پایگاه داده در هر درخواست.

## خلاصهٔ جریان‌های داده

**ورود محتوا (آفلاین ← سرو):** خزندهٔ TIS (`toyota_tis.py`، روی Chrome واردشده به TIS با دست اجرا می‌شود) HTML دفترچه را ذخیره می‌کند ← `tis_parser.py` (خزش‌های TIS) یا `htmlparser_logical.py` / `parser_gui.py` (ZIPهای قدیمی) آن را به `<car>.db` (درخت گره‌ها) + فایل‌های تصویر پارس می‌کنند ← فایل‌ها در `Database_warehouse/` / `static_warehouse/` می‌نشینند ← `sync_car_catalog` ردیف کاتالوگ را ثبت می‌کند ← pipeline embed/graph/diag-build را اجرا می‌کند ← ممیزی کیفیت داده راستی‌آزمایی می‌کند.

**یک درخواست مرور:** صفحهٔ SSR در Next ← `car_view` در Django (توکن از کوکی، گیت هر خودرو) ← پایگاه هر خودرو از طریق pool ← محتوای HTML با بازنویسی URL تصاویر به `/kg-api/media/<car>/…` ← رندر؛ کلاینت فعالیت را beacon می‌کند.

**یک پرسش دستیار:** مرورگر ← `/api/chat` در Next ← اعتبارسنجی `/api/auth/me/` + `ai_eligible` ← `/api/diagnose/` در Django (موتور قواعد؛ زمینهٔ خودرو) ← اگر خالی بود `/api/assist/` (RAG) ← زمینهٔ پایه‌دار ← بازنویسی Metis (پرامپت سخت‌گیرانه فقط‌زمینه) ← دروازهٔ وفاداری ← پاسخ با پیوندهای واقعی درون برنامه؛ fallback بدون LLM رندر می‌کند.

**یک به‌روزرسانی بی‌درنگ:** هر فرایند یک ردیف `Event` منتشر می‌کند ← نقطهٔ پایانی SSE جدول را دنبال می‌کند (poll هر ۱ ثانیه، heartbeat هر ۱۵ ثانیه، بازیافت هر ۳۰۰ ثانیه، ازسرگیری با `Last-Event-ID`) ← nginx بدون بافر جریان می‌دهد ← hook با نام `useEventStream` به کامپوننت‌های داشبورد توزیع می‌کند.

## مسیر مقیاس (محرک‌های اندازه‌گیری‌شده، نه حدس)

| سیگنال فشار | اقدام |
|---|---|
| `database is locked` در لاگ‌ها (رقابت نوشتن) | PostgreSQL با جایگزینی `DATABASES` — **برای پایگاه داده پرتال در ۲۰۲۶‑۱۰‑۲۹ انجام شد** |
| نیاز به بیش از یک میزبان برنامه | انبار + رسانه ← ذخیره‌سازی مشترک/شیء؛ محدودیت نرخ + کش ← Redis؛ نشست‌ها از قبل بر پایه پایگاه داده‌اند |
| پهنای باند رسانه | ذخیره‌سازی شیء/CDN برای `static_warehouse` (URLها از قبل نسبی‌اند) |
| زمان بازسازی embedding | `build_rag --add` افزایشی و مبتنی بر حذف تکرار محتواست؛ تقسیم بر اساس خودرو بین میزبان‌ها |
| انتشار SSE به بیش از چند صد کلاینت | دنبال‌کردن Event را به Redis pub/sub یا یک broker واقعی منتقل کنید؛ پروتکل کلاینت (SSE + Last-Event-ID) همان می‌ماند |

ظرفیت عمودی امروز: ۱۸۵ گیگابایت از ۲۹۰ گیگابایت دیسک استفاده شده؛ CPU/RAM با ترافیک فعلی فاصلهٔ زیادی با حدود دارند. سقف عملی دیسک (رشد ناوگان) و زمان بازسازی embedding است که هر دو از سرو درخواست جدا هستند.

## چیدمان مخزن

<div dir="ltr">

```
/opt/KGKG
├─ KG_backend/               Django project
│  ├─ KG_backend/            settings.py, urls.py (includes api.urls), wsgi
│  ├─ api/                   ALL application code (see doc 04)
│  ├─ Database_warehouse/    per-car DBs + _rag/ + _quarantine/  (NOT in git)
│  ├─ static_warehouse/      per-car images                       (NOT in git)
│  ├─ db.sqlite3             FORMER main DB, frozen 2026-10-29    (untracked 2026-07-10; old copies exist in git history)
│                            the portal now runs on PostgreSQL 16, database `kgkg`
│  ├─ ARCHITECTURE.md        original scale-strategy note (kept; superseded by docs/)
│  └─ requirements.txt
├─ kg_frontend/              Next.js app (src/app routes, src/components, src/utils, src/guidance)
├─ docs/                     ← THIS documentation suite
├─ htmlparser_logical.py     manual HTML → per-car SQLite parser
├─ parser_gui.py             tk GUI wrapper for the parser
├─ tis_parser.py            TIS crawl folder → per-car SQLite parser (same output as above)
├─ run_rag_build.sh / run_diag_build.sh / run_eval.sh / run_server.sh   convenience scripts
└─ Book1.csv                 EN↔FA parts glossary feeding RAG query expansion
```

</div>

**نکات git:** `work` شاخهٔ یکپارچه‌سازی و شاخه‌ای است که توسعه روی آن انجام می‌شود؛ `main` شاخهٔ پیش‌فرض GitHub است و از آن عقب است ([36-cicd-and-deployment.md](36-cicd-and-deployment.md) بخش ۳۶٫۱). (این یادداشت زمانی شاخهٔ دیگری را نام می‌برد؛ در ۲۰۲۶‑۰۷ درست بود.) `.gitignore` فایل‌های `*.md` را به‌طور سراسری نادیده می‌گیرد (حفاظت از محتوای خزیده‌شده) — اسناد باید با `git add -f` اضافه شوند. `db.sqlite3` و انبارها عمداً ردیابی نمی‌شوند.

</div>
