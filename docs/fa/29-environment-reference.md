<!-- i18n-source: 29-environment-reference.md sha256:80bbd25ab765 -->
<!-- i18n-source: 29-environment-reference.md sha256:b06c7d70ccda -->
<div dir="rtl" lang="fa">

# ۲۹ — مرجع متغیرهای محیطی (متغیرهای عملیاتی و تنظیمی)

**دامنه.** هر متغیری که در این سند آمده توسط کدِ همین مخزن خوانده می‌شود. مقدارها هرگز در این سند ثبت نمی‌شوند؛ فقط نام، معنا، نوع، مقدار پیش‌فرض و مصرف‌کننده. پیش‌فرض‌ها از سورس `origin/work` در نسخهٔ `f078878` خوانده شده‌اند **[C]**. اگر مقداری در `.env.prod` تنظیم شده باشد، اینجا نیست و این سند از آن خبر ندارد **[U]**. نسخهٔ انگلیسی: [../29-environment-reference.md](../29-environment-reference.md).

قراردادها: *bool* یعنی با همان تابع کمکیِ ذکرشده در ستون مصرف‌کننده پارس می‌شود (در بیشتر سوئیچ‌های `RAG_*` مقدار `'0'` غیرفعال می‌کند و برای `ADMIN_REQUIRE_2FA` مقدار `'1'` فعال می‌کند)؛ *num* یعنی با `_env_num` / `float()` / `int()` هنگام import خوانده می‌شود، پس مقدار نادرست در زمان راه‌اندازی خطا می‌دهد نه در زمان استفاده. همهٔ مقادیر `KG_ALERT_*`، `RAG_*`، `KG_CG_*` و `KG_PIPELINE_*` **یک‌بار هنگام import** خوانده می‌شوند؛ تغییر `.env.prod` نیازمند ری‌استارت بک‌اند است (دیپلوی این کار را انجام می‌دهد).

اسناد مرتبط: [11-operations-deployment.md](../11-operations-deployment.md)، [25-ops-inventory.md](../25-ops-inventory.md)، [08-ai-assistant-rag.md](../08-ai-assistant-rag.md)، [23-data-layer.md](../23-data-layer.md)، [generated/inventory.md](../generated/inventory.md) (فهرست کامل و ماشینی).

## ۲۹٫۱ سوئیچ‌های وب، امنیت و فریم‌ورک

| متغیر | پیش‌فرض | مصرف‌کننده | معنا و پیامد |
|---|---|---|---|
| `DJANGO_CORS_ALLOW_ALL` | مقدار `DEBUG` | `KG_backend/KG_backend/settings.py:104` | مقدار `true` همهٔ originها را مجاز می‌کند. در تولید باید خاموش بماند؛ در غیر این صورت فهرست مجازِ `DJANGO_CORS_*` اعمال می‌شود. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | فهرست خالی | `settings.py:277` | originهای جداشده با کاما که برای بررسی CSRF در POSTهای میان‌مبدأ مورد اعتماد هستند. |
| `DJANGO_SSL_REDIRECT` | `false` | `settings.py:267` | ریدایرکت HTTP→HTTPS در سطح Django. پشت پراکسی Next.js **خاموش بماند**: در ۲۰۲۶‑۰۹‑۰۷ روشن شد، رندر سمت سرور را به `https://127.0.0.1:8000` کشاند و شکست خورد، و دوباره خاموش شد (کامنتِ `settings.py`). TLS را nginx پایان می‌دهد. |
| `ADMIN_REQUIRE_2FA` | تنظیم‌نشده (خاموش) | `api/portal.py:958` | مقدار `1` عامل دوم (OTP) را برای ورود ادمین اجباری می‌کند. ← [26-auth-and-sessions.md](../26-auth-and-sessions.md). |
| `RUN_MAIN` | توسط autoreload جنگو تنظیم می‌شود | `api/apps.py:21` | در توسعه فقط فرایند فرزندِ autoreload کش‌ها را گرم می‌کند؛ مقدار `false` یعنی فرایند ناظر. تنظیم اپراتور نیست. |
| `KG_RELEASE` | `dev` (متریک‌ها) / تنظیم‌نشده (Sentry) | `settings.py:361`، `api/metrics_exposition.py:221` | شناسهٔ انتشار (SHA کامیت) که به رویدادهای GlitchTip/Sentry چسبانده می‌شود و برچسب `release` متریک build-info است. توسط دیپلوی تنظیم می‌شود. |
| `KG_TESTING` | تنظیم‌نشده | `KG_backend/KG_backend/jsonlog.py:166` | اگر تنظیم باشد، لاگ ساختاریافتهٔ JSON نصب نمی‌شود (تست‌ها خروجی ساده دارند). وقتی `test` در `argv[:2]` باشد هم نصب نمی‌شود. |
| `API_BASE_INTERNAL` | `http://backend:8000` در `docker-compose.yml` | `kg_frontend/src/utils/api.jsx` | نشانی پایه‌ای که سرور Next.js برای فراخوانی‌های سمت سرور به Django استفاده می‌کند (`docker-compose.yml:31`). اگر بک‌اند جابه‌جا شد override شود. |
| `KG_MEDIA_ROOT` | `/media` در compose | `kg_frontend/src/app/[brand]/[year]/[model]/[...path]/page.jsx:27` | پوشه‌ای که فرانت‌اند هنگام رندر نمایشگر دفترچه، رسانهٔ خودرو را از آن می‌خواند. |
| `KG_PUBLIC_MEDIA_PREFIX` | `/kg-api/media` | `api/sst.py:74` | پیشوند URL عمومی که nginx مخزن رسانه را زیر آن سرو می‌کند. یک واقعیتِ استقرار است، پس قابل override است. |

## ۲۹٫۲ مسیرهای ذخیره‌سازی و دسترسی به پایگاه داده

| متغیر | پیش‌فرض | مصرف‌کننده | معنا و پیامد |
|---|---|---|---|
| `KG_DB_PATH` | تنظیم‌نشده | `settings.py:132` | مسیر پایگاه SQLite اصلی (توسعه / فایل منجمدِ تولیدِ قبلی). با PostgreSQL مسیری وجود ندارد. |
| `KG_DATA_DIR` | پوشهٔ والدِ `KG_DB_PATH`، وگرنه `BASE_DIR` | `settings.py:133`؛ ۱۲ فایل | پوشهٔ داده‌های غیرپایگاهی (انبار، `_rag/`، spoolها). چون با PostgreSQL فایل DB برای گرفتن والد وجود ندارد، تنظیم مستقل شد. |
| `KG_LOG_DIR` | `/var/log/kgkg` | `settings.py:288`؛ `KG_backend/Dockerfile:6` | محل فایل‌های لاگ چرخشیِ برنامه. |
| `KG_WAREHOUSE` | `/opt/KGKG/KG_backend/Database_warehouse` | `KG_backend/scripts/wal_checkpoint.py:21` | ریشهٔ انبار برای ابزار WAL-checkpoint (فقط فایل‌های SQLite؛ `kgkg_vec` تأثیری نمی‌پذیرد). |
| `KG_PG_USER` | `kgkg` | `settings.py:147` | نقش PostgreSQL برای پایگاه پرتال. |
| `KG_PG_PASSWORD` | خالی | `settings.py:148` | **محرمانه.** خالی یعنی احراز هویت peer/trust. مقدار را هرگز در سند یا لاگ ننویسید. |
| `KG_PG_HOST` | `127.0.0.1` | `settings.py:150` | رشتهٔ خالی = سوکت یونیکسِ محلی (احراز هویت peer). گیتِ دیپلوی با نقش `root` از سوکت استفاده می‌کند. |
| `KG_PG_PORT` | `5432` | `settings.py:151`؛ همچنین `api/rag/config.py:688` | پورت؛ به DSN مربوط به pgvector هم منتقل می‌شود. |
| `KG_PG_TEST_NAME` | تنظیم‌نشده | `settings.py:157` | نام پایگاه تستِ جنگو. گیت برای هر اجرا نامی جدا می‌گذارد (`test_kgkg_gate_$$`) تا گیت CI و گیت دیپلوی پایگاه یکدیگر را حذف نکنند. |
| `KG_CARDB_ADMIN_DSN` | `dbname=kgkg_vec` | `api/cardb_pg.py:203` | DSN از نوع libpq که `adopt()` و بارگذارها برای ساخت و پرکردن schemaهای هر خودرو در `kgkg_vec` به کار می‌برند. نیازمند اجازهٔ ساخت schema است. ← [23-data-layer.md](../23-data-layer.md). |
| `RAG_PGVEC_DB` | `kgkg_vec` | `api/rag/config.py:686` | نام پایگاهِ pgvector. **در تولید روی PostgreSQL تنظیم است** (`RAG_VEC_BACKEND=pgvector` و `RAG_FTS_BACKEND=pg`، مشاهده‌شده ۲۰۲۶-۱۱-۰۴)؛ فقط وقتی فعال است که `RAG_VEC_BACKEND`/`RAG_FTS_BACKEND` به PostgreSQL اشاره کنند. |
| `RAG_INDEX_DB` | `_rag/index.rag.db` | `api/rag/config.py:33` | فایل ایندکس جایگزین برای آزمایش‌های آفلاین. در تولید تنظیم نیست. |
| `RAG_PARTS_DB` | محاسبه در `config.py:66` | `api/rag/config.py:66` | override برای پایگاه کاتالوگ قطعاتی که دستیار استفاده می‌کند. |
| `RAG_FEEDBACK_DB` | `_rag/feedback.db` | `api/rag/config.py:654` | SQLite جانبی برای لاگ پرسش‌ها و امتیازها. **پشته‌های staging/QA پوشهٔ `_rag/` تولید را mount می‌کنند و باید این را تنظیم کنند**؛ وگرنه پرسش‌ها و امتیازهایشان در مخزن تولید می‌نشیند و نتایج زندهٔ جست‌وجو را بازرتبه‌بندی می‌کند. |

## ۲۹٫۳ مدل فرایند بک‌اند و اجرای کانتینر

| متغیر | پیش‌فرض | مصرف‌کننده | معنا |
|---|---|---|---|
| `KG_BIND` | `127.0.0.1` | `ops/docker/backend.Dockerfile:49`، `frontend.Dockerfile:28` | نشانی گوش‌دادن درون کانتینر (تنها شنوندهٔ عمومی nginx است). |
| `KG_PORT` | `8000` | `backend.Dockerfile:49`؛ `ops/docker/containers.sh:39` | پورت بک‌اند؛ `containers.sh` برای هر کانتینر یک پورت آزاد میزبان انتخاب می‌کند. |
| `KG_HEALTH_PORT` | `18999` | `backend.Dockerfile:40`؛ `containers.sh:39` | پورت دومِ یکتا برای هر کانتینر که `HEALTHCHECK` داکر از آن استفاده می‌کند تا پورت اصلی به‌تنهایی نتواند بگوید کدام کانتینر پاسخ داده است. |
| `KG_WORKERS` | `3` (staging: `2`) | `backend.Dockerfile:51`؛ `deploy.sh:424` | تعداد فرایندهای worker در gunicorn. کلاس worker برابر `gthread`، `--timeout 300` و بازیافت بر اساس تعداد درخواست (کامنت Dockerfile). |
| `KG_THREADS` | `8` (staging: `4`) | همان | تعداد thread در هر worker. هم‌زمانی = worker × thread. |
| `KG_FE_ENV` | `/opt/KGKG/kg_frontend/.env.production` | `ops/docker/containers.sh:11` | فایل env که به کانتینر فرانت‌اند داده می‌شود. |
| `KG_ENV_FILE` | `DEFAULT_ENV` دستور؛ در CI برابر `/tmp/ci-dummy.env` | `management/commands/rotate_secrets.py:118`؛ `ci.yml:43,354` | فایل env که `rotate_secrets` می‌خواند/می‌چرخاند؛ CI آن را به فایلی ساختگی اشاره می‌دهد. |
| `KG_ENV_FILE_WATCHDOG` | `/opt/KGKG/KG_backend/.env.prod` | `ops/observability/watchdog.py:47` | فایل env که watchdog میزبان برای اعتبارنامهٔ پیامک می‌خواند. فقط خواندنی. |
| `KG_HOSTJOBS_DIR` | خالی | `api/hostjobs.py:33`؛ `ops/hostjobs/hostjobs_daemon.py` | پوشهٔ spoolِ پل host-jobs. درون کانتینر مقدار دارد؛ خالی یعنی «کار را محلی اجرا کن» (timerهای میزبان، دستورات مدیریتی). |
| `KG_BACKEND_DIR` | `/opt/KGKG/KG_backend` | `ops/hostjobs/hostjobs_daemon.py:19` | checkout بک‌اندی که دیمون میزبان کارها را از آن اجرا می‌کند. |
| `KG_SPOOL` | به‌ازای هر پشته | `ops/deploy/deploy.sh:417-420` | پوشهٔ spool که به کانتینرهای staging داده می‌شود تا کارهای staging وارد صف تولید نشوند. |

## ۲۹٫۴ خط لولهٔ ورود محتوا و خزنده‌ها

| متغیر | پیش‌فرض | مصرف‌کننده | معنا |
|---|---|---|---|
| `KG_PIPELINE_BATCH` | `32` | `management/commands/run_pipeline.py:398` | تعداد آیتم در هر دسته در مرحلهٔ embedding. |
| `KG_PIPELINE_THREADS` | `12` | `api/pipeline.py:308` | تعداد thread‌های OpenMP برای pipeline؛ مقدار صریح `KG_PARSE_WORKERS`/`KG_PIPELINE_THREADS` بر اندازه‌گیری خودکار غلبه دارد. عمداً کمتر از کل هسته‌هاست تا سرویس‌دهی پاسخگو بماند. |
| `KG_PIPELINE_DISK_RECOVERY_MARGIN` | `1.1` | `api/ingest.py:134` | ضریب فاصلهٔ بازیابی برای محافظ حداقل فضای دیسک تا هشدار در مرز نوسان نکند. |
| `KG_PARSER_PATH` | محاسبه در `ingest.py:90` | `api/ingest.py` | مسیر فایل اجرایی/اسکریپت پارسر دفترچه. |
| `KG_TIS_PARSER_PATH` | محاسبه در `ingest.py:107` | `api/ingest.py` | مسیر پارسر TIS. |
| `KG_CG_PAGE_WARN` / `KG_CG_PAGE_BLOCK` | `300` / `900` | `api/contentguard.py:27` | نگهبان محتوا: آستانه‌های تعداد صفحه (هشدار / مسدودسازی) برای دفترچهٔ واردشده. |
| `KG_CG_MEDIA_WARN` / `KG_CG_MEDIA_BLOCK` | `2000` / `6000` | `contentguard.py:28` | همان برای تعداد فایل‌های رسانه. |
| `KG_TIS_DIR` | `/root/Desktop/tis_crawler` | `api/tis_crawler.py:25` | پوشهٔ کار خزندهٔ TIS. |
| `KG_TIS_DISPLAY` | `:99` | `tis_crawler.py:38` | نمایشگر X که روی VNC (فقط localhost، از طریق تونل SSH) در دسترس است تا یک انسان کد یک‌بارمصرف را وارد کند. |
| `KG_TIS_CHROME_PROFILE` | `/root/.chrome-tis-profile` | `tis_crawler.py:39` | پوشهٔ پروفایل Chrome که بین اجراها حفظ می‌شود. |
| `KG_PS_DIR` | `/root/partsouq_crawl` | `api/partsouq_crawler.py:23` | ریشهٔ خروجی خزندهٔ VIN سایت PartSouq (`<vehicle>/`). |
| `KG_PS_SCRIPT` | `/opt/KGKG/ops/partsouq/partsouq_vin_crawl.py` | `partsouq_crawler.py:25` | اسکریپتی که **روی میزبان** اجرا می‌شود (کانتینر بک‌اند درخت `ops/` ندارد و از طریق پل host-jobs از میزبان می‌خواهد). |

## ۲۹٫۵ آستانه‌های هشدار (`api/alert_rules.py`، `api/monitoring.py`)

همه عددی و در زمان import خوانده می‌شوند و بدون تغییر کد از `.env.prod` قابل override‌اند. هشدارها با پیامک و زمان خنک‌شدن (cooldown) ارسال می‌شوند (← [11-operations-deployment.md](../11-operations-deployment.md)، [25-ops-inventory.md](../25-ops-inventory.md)).

| متغیر | پیش‌فرض | واحد / بازه | شرط |
|---|---|---|---|
| `KG_ALERT_LOGIN_FAIL_IP` | 20 | در ۱۵ دقیقه | ورودهای ناموفق از یک IP. |
| `KG_ALERT_LOGIN_FAIL_ACCOUNT` | 10 | در ۱۵ دقیقه | ورودهای ناموفق برای یک حساب. |
| `KG_ALERT_ADMIN_FAILS` | 5 | در ۱۵ دقیقه | ورودهای ناموفق ادمین. |
| `KG_ALERT_SMS_FAILS` | 3 | در ۱ ساعت | شکست‌های ارسال پیامک. |
| `KG_ALERT_AI_DEGRADED` | 0.3 | نسبت در ۱ ساعت | سهم پاسخ‌های دستیار که در حالت تنزل‌یافته (بدون LLM) داده شده‌اند. |
| `KG_ALERT_AI_MIN_N` | 5 | پاسخ | حداقل پاسخ لازم پیش از ارزیابی سهم تنزل. |
| `KG_ALERT_AI_COST_X` | 3.0 | برابر | هزینهٔ ۲۴ ساعتهٔ دستیار نسبت به میانگین روزانهٔ ۷ روز. |
| `KG_ALERT_AI_COST_FLOOR` | 0.5 | واحد پولیِ لاگ هزینه | جهش‌های کمتر از این مبلغ مطلق نادیده گرفته می‌شود. |
| `KG_ALERT_SMS_COOLDOWN_H` | 6 | ساعت | حداقل فاصلهٔ تکرار یک هشدار یکسان. |
| `KG_ALERT_ADMIN_NO2FA` | روشن (`1`) | سوئیچ | مقدار `0` هشدار «ادمین بدون OTP» را برای موارد عمدی خاموش می‌کند. |
| `KG_ALERT_DISK_PCT` | 85 | درصد استفاده | هشدار دیسک در موتور قواعد. |
| `KG_ALERT_MEM_FREE_PCT` | 10 | درصد آزاد | هشدار کمبود حافظهٔ آزاد. |
| `KG_ALERT_RESTARTS` | 3 | در ۳۰ دقیقه | ری‌استارت کانتینرها. |
| `KG_ALERT_TLS_DAYS` | 14 | روز | هشدار انقضای گواهی. |
| `KG_ALERT_NETWORK_DOWN_MIN` | 30 | دقیقه | شکست هم‌زمان تقریباً همهٔ probeها یعنی قطع شبکهٔ خود میزبان؛ فقط وقتی هشدار می‌دهد که این‌قدر طول بکشد. |
| `KG_ALERT_SCRAPE_DOWN_MIN` | 10 | دقیقه | نبودِ یک هدف متریک؛ برای نادیده‌گرفتن نوسان کوتاه تا promote هشدار ندهد. |
| `KG_ALERT_WATCHDOG_STALE_S` | 1800 | ثانیه | ضربان watchdog قدیمی‌تر از این مقدار (timer هر ۵ دقیقه اجرا می‌شود؛ ۳۰ دقیقه = شش اجرای از دست‌رفته). |
| `KG_ALERT_5XX` | 5 | در ساعت | پاسخ‌های 5xx؛ انتخاب شد چون بیشینهٔ ۷ روز پیش از ۲۰۲۶‑۱۰‑۲۹ برابر ۰ بود. |
| `KG_ALERT_BUDGET_MIN_H` | 24 | ساعت | حداقل پنجرهٔ مشاهده پیش از ارزیابی هشدار سوخت بودجه. |
| `KG_ALERT_CANARY_DAYS` | 7 | روز | فاصلهٔ پیامک‌های آزمایشی مسیر هشدار (یک پیامک آزمایشی به هر شمارهٔ `KG_ALERT_PHONES`، ساعت ۱۰ تا ۱۲ تهران)؛ `0` آن را خاموش می‌کند. |
| `KG_ALERT_CANARY_WAIT_H` | 2 | ساعت | مدتی که پیامک آزمایشی می‌تواند بدون رسید تحویل بماند پیش از باز شدن `infra:sms_canary`. |
| `KG_ALERT_QA_STALE_H` | 36 | ساعت | نتیجهٔ QA شبانه قدیمی‌تر از این مقدار. |
| `KG_LOCAL_HEALTH_URL` | `http://127.0.0.1:8000/api/health/` | URL | probe سلامت محلی که هم موتور قواعد و هم watchdog استفاده می‌کنند. |
| `KG_ALERT_DISK_WARN` / `KG_ALERT_DISK_CRIT` | 85 / 93 | درصد | آستانه‌های رنگ در صفحهٔ پایش ادمین (`monitoring.py:283-284`). |
| `KG_ALERT_MEM_WARN` | 92 | درصد استفاده | همان صفحه، حافظه. |
| `KG_ALERT_ERR_RATE` | 0.05 | نسبت | همان صفحه، هشدار نرخ خطا. |
| `KG_ALERT_ERR_MIN_N` | 50 | درخواست | حداقل درخواست پیش از ارزیابی نرخ خطا. |
| `KG_ALERT_LATENCY_MS` | 5000 | میلی‌ثانیه | همان صفحه، هشدار تأخیر. |

## ۲۹٫۶ watchdog میزبان (`ops/observability/watchdog.py`، واحد `kgkg-watchdog.service`)

| متغیر | پیش‌فرض | معنا |
|---|---|---|
| `KG_WATCHDOG_STATE` | `/var/lib/kgkg-watchdog` | پوشهٔ وضعیت (شمارندهٔ شکست‌ها، زمان آخرین ارسال). |
| `KG_WATCHDOG_STALE_S` | 1200 | مرور هشدارها هر ۵ دقیقه اجرا می‌شود؛ ۳ بار از دست رفتن = توقف. |
| `KG_WATCHDOG_COOLDOWN_H` | 6 | فاصله بین اعلان‌های تکراری. |
| `KG_WATCHDOG_PAGE_AFTER` | 2 | تعداد شکست متوالی پیش از page (با timer پنج‌دقیقه‌ای حدود ۱۰ دقیقه تا کشف). |
| `KG_WATCHDOG_UNITS_COOLDOWN_H` | 12 | cooldown بلندتر برای اعلان «واحد systemd ناموفق» که به دخالت انسان نیاز دارد. |
| `KG_WATCHDOG_IGNORE_UNITS` | خالی | واحدهای جداشده با کاما که از page کنار گذاشته می‌شوند (همچنان شمرده می‌شوند تا خاموش‌سازی دیده شود). |
| `KG_SNAPSHOT_STAMP` | `/root/backup_snapshot/SNAPSHOT_AT` | فایلی که سنِ آن اثبات می‌کند snapshot ساعتیِ خارج از میزبان اجرا شده است. |
| `KG_TEXTFILE_DIR` | `/var/lib/node-exporter-textfile` | پوشهٔ textfile مربوط به node-exporter؛ `deploy.sh` هم برای انتشار متریک «چه چیزی زنده است / چه زمانی staged شد» از آن استفاده می‌کند. |

## ۲۹٫۷ تنظیمات RAG و دستیار (`api/rag/config.py`)

جزئیات اثر هر پارامتر بر خط لوله: [30-ai-assistant-deep-dive.md](../30-ai-assistant-deep-dive.md) و [08-ai-assistant-rag.md](../08-ai-assistant-rag.md).

| متغیر | پیش‌فرض | اثر |
|---|---|---|
| `RAG_EMBED_MODEL` | `bge-m3` | مدل embedding. `build_rag` از گسترش ایندکسی که با مدل دیگری ساخته شده خودداری می‌کند. به host jobs هم منتقل می‌شود. |
| `RAG_EMBED_FP16` | روشن | نیم‌دقت روی GPU: حافظهٔ مقیم حدود ۲٫۳ → ۱٫۲ گیگابایت؛ روی CPU نادیده گرفته می‌شود. |
| `RAG_RERANK_MODEL` | `BAAI/bge-reranker-v2-m3` | cross-encoder؛ فقط با `RAG_RERANK=1` فعال است. |
| `RAG_RERANK_FUSE` | `1.0` | وزن آمیزش امتیاز cross-encoder با امتیاز مرحلهٔ اول؛ `1.0` = بازرتبه‌بندی کامل (رفتار قدیمی). کامنت سورس نتیجهٔ اعتبارسنجی متقاطع ۲-فولد را ثبت کرده که روی مجموعه‌های طلایی مقداری حدود ۰٫۴ را برتر نشان داد (nDCG@5 انگلیسی ‎+۰٫۱۲، Hit@1 فارسی ‎+۰٫۱۹). پیش‌فرض تغییر نکرده است. |
| `RAG_SEARCH_SIM_FLOOR` | `0.55` | حداقل شباهت برداری برای نگه‌داشتن یک نتیجه. کامنت سورس ثبت کرده که ۰٫۵۵ فقط ۱ پرسش از ۸۱ پرسش واقعی را خالی می‌گذارد. |
| `RAG_SEARCH_OVERFETCH` | `4` | ضریب واکشی اضافه از کاندیدها پیش از فیلتر. |
| `RAG_SEARCH_MAX_DEPTH` | `120` | سقف سخت عمق کاندیدها. |
| `RAG_SCOPE_FTS_K` | `30` | تعداد کاندیدهای FTS درون خودرو. |
| `RAG_SCOPE_FTS_SCAN` | `4000` | عمق اسکن FTS تک‌جدولی پیش از اشتراک‌گیری با blobهای خودرو. |
| `RAG_CAR_VEC_K` | `40` | عمق جست‌وجوی برداری برای گذر مخصوص خودروی pin‌شده. |
| `RAG_CAR_BLOBS_CACHE` | `8` | تعداد مجموعه‌های شناسهٔ blob هر خودرو که در حافظه نگه داشته می‌شود (هرکدام حدود ۷ هزار عدد صحیح). |
| `RAG_FTS_CLEAN` | روشن | رشتهٔ MATCH کوتاه‌تر و پاک‌شده؛ بر اساس کامنت سورس، p50 از ۱۱۶۸ به ۸۱۹ میلی‌ثانیه (انگلیسی) و از ۱۰۴۸ به ۸۴۲ (فارسی) کاهش یافت. |
| `RAG_FTS_W_TEXT` / `RAG_FTS_W_TITLE` / `RAG_FTS_W_COMP` | 1.0 / 4.0 / 12.0 | وزن ستون‌های BM25 (متن، عنوان، مؤلفه). |
| `RAG_NEARMISS_GUARD` | روشن | نگهبان مؤلفه در برابر شواهد «تقریباً درست»؛ مقدار `0` بدون دیپلوی به نگهبان مبتنی بر عنوان برمی‌گرداند. |
| `RAG_GRAPH_WORKERS` | `0` | تعداد فرایند برای مرحلهٔ kNN معنایی ساخت گراف (`0` = هسته‌ها را برای سرویس‌دهی نگه‌دار). |
| `RAG_CACHE_TTL` / `RAG_CACHE_MAX` | 900 ثانیه / 512 | کش پاسخ درون‌فرایندی با کلید «پرسش نرمال‌شده + دامنه». |
| `RAG_DIAG_CACHE_TTL` | 900 ثانیه | کش نتیجهٔ عیب‌یابی. |
| `RAG_SEM_CACHE` | روشن | کش پاسخ تحمل‌کنندهٔ بازنویسی، روی بردار پرسشِ از‌پیش‌محاسبه‌شده. |
| `RAG_SEM_CACHE_SIM` | `0.95` | شباهت لازم برای برخورد کش معنایی؛ فقط برای غلط تایپی/نشانه‌گذاری/صرف طراحی شده است. |
| `RAG_LOG_QUERIES` | روشن | ثبت هر پرسش در `feedback.db`. پیامد حریم خصوصی: پرسش‌های کاربران ذخیره می‌شود. |
| `RAG_FEEDBACK_BOOST` | روشن | اعمال امتیازهای ذخیره‌شده در رتبه‌بندی. |
| `RAG_FB_CACHE_TTL` | 300 ثانیه | دورهٔ تازه‌سازی نقشهٔ boost. |
| `RAG_MQ_CACHE` | `/root/paraphrases_known_item_fa.json` | کش baseline ارزیابی آفلاین (`api/evalsuite/baselines.py:341`). مسیری مربوط به ماشین توسعه‌دهنده؛ در سرویس‌دهی استفاده نمی‌شود. |

## ۲۹٫۸ اسکریپت‌های دیپلوی، گیت، smoke و CI

| متغیر | پیش‌فرض | مصرف‌کننده | معنا |
|---|---|---|---|
| `KG_BE_DIR` | `$PROD/KG_backend` | `ops/deploy/deploy.sh:62` | پوشهٔ بک‌اندی که دیپلوی `.env.prod` آن را می‌خواند (فقط سوئیچ موتور پایگاه). |
| `KG_PROD_DIR` | `/opt/KGKG` | `kg-deploy-gate`، `ci_evidence.sh` | ریشهٔ checkout تولید. |
| `KG_PROD_ENV` | `/opt/KGKG/KG_backend/.env.prod` | `gate.sh:24` | برای تشخیص `KG_DB_ENGINE=postgres` و انتخاب پایگاه گیت. |
| `KG_VENV` | `/opt/KGKG/KG_backend/.venv/bin` | `gate.sh:11` | محل مفسر Python برای گیت. |
| `KG_GATE_LOGS` | `$W/.gate-logs` | `gate.sh:12`، `deploy.sh:368` | محل نوشتن لاگ‌های گیت (`$REL/logs/gate-<ts>` هنگام دیپلوی). |
| `KG_MIGRATION_BASE` | `HEAD` در `/opt/KGKG` | `gate.sh:62` | نسخهٔ مبنا برای بررسی «migration فقط افزایشی». |
| `KG_SECTOOLS` / `KG_SECTOOLS_BIN` | `/opt/KGKG_release/sectools` | `gate.sh`، `ops/security/scan.sh` | محل bandit/pip-audit؛ در اولین استفاده ساخته می‌شود. اسکنری که اجرا نشود گیت را رد می‌کند و نادیده گرفته نمی‌شود. |
| `KG_DEPLOY_LOCK_WAIT` | `1800` ثانیه | `deploy.sh:316` | مدت انتظار دیپلوی برای قفل؛ `0` رفتار fail-fast را برمی‌گرداند. |
| `KG_KEEP_STAGING` | `0` | `deploy.sh:430` | مقدار `1` کانتینرهای staging را پس از اجرا نگه می‌دارد. |
| `KG_STAGING_QA_USER` | `qa_e_root` | `deploy.sh:37` | حساب QA که برای بررسی‌های staging استفاده می‌شود. |
| `KG_NGINX_SITE` / `KG_NGINX_CONFD` / `KG_NGINX_BACKUPS` | `/etc/nginx/sites-enabled/kgkg`، `/etc/nginx/conf.d`، `/etc/nginx/config-backups` | `deploy.sh:146-148` | فایل‌های nginx که دیپلوی نصب و پشتیبان‌گیری می‌کند. |
| `KG_SMOKE_HOST` | `kgtechvault.com` | `smoke.sh:91` | هدر `Host:` برای بررسی smoke پراکسی معکوس. |
| `KG_SMOKE_SCRAPE` | `http://127.0.0.1:8081` | `smoke.sh:98` | شنوندهٔ scrape؛ باید برای هر چیز جز متریک‌ها 403 بدهد. |
| `KG_SMOKE_TOKEN` | در اجرای smoke تولید می‌شود | `smoke.sh:82`، `smoke_fleet.py` | توکن پرتال **محرمانه** که تست smoke ناوگان استفاده می‌کند. |
| `KG_SMOKE_SAMPLE` | `3` (از ۱ تا ۲۰) | `smoke_fleet.py:392` | تعداد خودروی بازشونده در هر دسته. |
| `KG_DOCKER` / `KG_IMAGE_REPOS` / `KEEP_IMAGES` | `docker` / `kgkg-backend kgkg-frontend` | `prune_images.sh` | پاک‌سازی ایمیج‌ها (فایل اجرایی برای تست قابل جایگزینی است). |
| `KG_BIN_DIR` / `KG_SSH_DIR` / `KG_HOST_KEY` | `/usr/local/bin`، `/root/.ssh`، `/etc/ssh/ssh_host_ed25519_key.pub` | `setup_ci_access.sh` | مسیرهای نصاب دسترسی CI؛ اگر sshd کلید میزبان دیگری سرو کند ادامه نمی‌دهد. |
| `KG_CI_SSH_DIR` | `$HOME/.ssh` | `ci_ssh.sh:33` | جایگزین `~/.ssh` برای تست‌ها. |
| `KG_CI_REPO` / `KG_CI_REQUIRED` / `KG_CI_TIMEOUT` / `KG_CI_FETCH` / `KG_CI_REQUIRED_ARG` | remote مبدأ / `backend frontend security images` / `20` ثانیه / curl / داخلی | `ci_evidence.sh` | شیوهٔ اثبات اینکه jobهای CIِ لازمِ کامیت موفق بوده‌اند. `KG_CI_FETCH` فراخوانی HTTP را (برای تست) جایگزین می‌کند؛ `KG_CI_REQUIRED_ARG` تحویل داخلی به اسکریپت تعبیه‌شده است. |
| `KG_TIP_CMD` | `git ls-remote` | `ci_is_tip.sh:33` | جایگزین جست‌وجوی tip (برای تست‌ها). |
| `GITHUB_EVENT_PATH` | توسط GitHub Actions تنظیم می‌شود | `ops/governance/check_traceability.py:44` | بارِ رویداد pull request که بررسی ردیابی‌پذیری استفاده می‌کند. |

## ۲۹٫۹ پشتهٔ QA

| متغیر | معنا |
|---|---|
| `KG_QA_STACK` | برای اجرای `seed_qa_fixtures` باید `1` باشد. یکی از سه محافظ مستقل که seeder را از تولید دور نگه می‌دارد. |
| `KG_QA_PASSWORD` | **محرمانه.** در هر اجرا توسط `qa/stack.sh` تولید می‌شود؛ seeder بدون آن اجرا نمی‌شود. |

## ۲۹٫۱۰ آنچه این سند پوشش نمی‌دهد

مقادیر `.env.prod` تولید، اینکه هر سوئیچ اختیاری اکنون تنظیم شده یا نه، و متغیرهای مؤلفه‌های ثالث (nginx، Prometheus، Grafana، Umami) پوشش داده نشده‌اند **[U]**. اعتبارنامه‌های Metis/LLM و خانوادهٔ `RAG_VEC_BACKEND`، `RAG_FTS_BACKEND`، `RAG_RERANK`، `KG_CARDB_PG`، `KG_DB_ENGINE` در [08](../08-ai-assistant-rag.md) و [23](../23-data-layer.md) آمده‌اند.

</div>
