<!-- i18n-source: 24-integrations.md sha256:6027c8b89b25 -->
<div dir="rtl" lang="fa">

# ۲۴ — یکپارچگی‌های خارجی

هر شخص ثالثی که سیستم فرامی‌خواند، برای چه، چه نام‌های پیکربندی‌ای می‌خواند (فقط نام؛ مقدارها در `.env.prod` / `kg_frontend/.env.production` روی میزبان هستند و هرگز در مخزن ثبت نمی‌شوند)، و هنگام شکست چه می‌شود. **[C]** = خوانده‌شده از کد در `8a380f6`؛ **[D]** = ادعای Slack/نشست.

| یکپارچگی | کاربرد | کجا | نام‌های پیکربندی | رفتار هنگام شکست |
|---|---|---|---|---|
| **Metis AI** (`api.metisai.ir`، پولی) | پاسخ‌های دستیار را از متن‌های بازیابی‌شده بازنویسی می‌کند؛ همچنین ترجمهٔ پرسش فارسی←انگلیسی | `kg_frontend/src/app/api/chat/route.js` (سمت سرور؛ `RAG_MQ_TRANSLATE` همان‌جا خوانده می‌شود و با `FeatureFlag` گیت می‌شود، migration 0034). ابزارهای آفلاین هم فراخوانی می‌کنند: `evalsuite/answer_eval.py`، `manage.py translate_terms` | `METIS_API_KEY`، `METIS_BOT_ID`، `METIS_FALLBACK_BOT_IDS` (نشانی پایه ثابت در کد است، نه پیکربندی) | `withFallback` به ترتیب روی شناسه‌های ربات جایگزین دوباره تلاش می‌کند؛ اگر همه شکست خوردند رندرکنندهٔ قطعی فارسی از متن‌ها پاسخ می‌دهد (fallback بدون LLM، ADR-0002). زنجیرهٔ جایگزین در ۲۰۲۶‑۱۱‑۰۳ تنظیم شد: `deepseek-v4-1-flash-1017`، سپس `gpt-6-luna`، سپس `gpt-5.4-mini` [D]؛ ربات اصلی آن روز 503/400 برگرداند |
| **Melipayamak** (پیامک) | کدهای ورود OTP، اعلان‌های امنیتی، page هشدار، پیامک چت پشتیبانی | OTP/امنیت: `api/portal.py`، `api/notify.py`؛ هشدارها: `api/alert_rules.py`؛ پیام‌های مشتری: `api/notifications/providers.py` | `SMS_USERNAME`، `SMS_API_KEY`، `SMS_FROM`؛ سوئیچ‌های صندوق خروجی `KG_NOTIFY_SMS`، `KG_NOTIFY_EMAIL`، `KG_NOTIFY_SMS_MAX_PER_HOUR` (سند ۱۱) | پیکربندی ناموجود هشدار لاگ می‌کند و رد می‌شود. مسیر page سرتاسری هرگز راستی‌آزمایی نشده است (GitHub #24، A-18) [D] |
| **ایمیل (SMTP)** | اعلان‌های مشتری فقط از طریق صندوق خروجی | `api/notifications/providers.py` | `EMAIL_HOST`، `EMAIL_PORT`، `EMAIL_HOST_USER`، `EMAIL_HOST_PASSWORD`، `EMAIL_USE_TLS`، `KG_NOTIFY_FROM_EMAIL` | در ۲۰۲۶‑۱۱‑۰۱ در تولید SMTP وجود نداشت [D memory، **اکنون U**]؛ صندوق خروجی به‌صورت پیش‌فرض خاموش است |
| **Cloudflare Turnstile** | بررسی ربات در ورود پرتال و ادمین | `api/portal.py` ← `_verify_turnstile` | `TURNSTILE_SECRET`، `TURNSTILE_HOSTNAMES` | `challenges.cloudflare.com` را فرامی‌خواند؛ میزبانی بدون مسیر IPv6 یک‌بار حدود ۴۰ ثانیه گیر کرد (در `backend.Dockerfile` اصلاح شد، ۲۰۲۶‑۱۱‑۰۳ [D]) |
| **Cloudflare (پراکسی/DNS/TLS)** | ورودی عمومی، گواهی مبدأ | nginx با `ops/nginx/kgkg.conf` به `CF-Connecting-IP` اعتماد می‌کند؛ اسناد ۱۱، ۱۸ | کلید مبدأ عمداً از پشتیبان‌ها کنار گذاشته شده (سند ۱۲) | تنظیمات داشبورد در مخزن نیست **[U]** |
| **GitHub** | منبع، CI، CodeQL، Dependabot، اسکن راز | `.github/` | رازهای Actions با نام `DEPLOY_HOST`، `DEPLOY_KNOWN_HOSTS`، `DEPLOY_SSH_KEY` (فقط نام) [D]؛ environment با نام `production` بازبین می‌خواهد | job با نام `stage` اگر رازها نباشند قرمز می‌شود |
| **GlitchTip** (API سازگار Sentry خودمیزبان) | ردیابی خطا برای بک‌اند و فرانت‌اند | سند ۱۸ بخش پایش خطا؛ compose در `/opt/glitchtip` | `SENTRY_DSN`، `SENTRY_ENVIRONMENT`، `SENTRY_TRACES_RATE` (فرانت‌اند)؛ DSN بک‌اند در env | شناسهٔ پروژه‌ها: `kgkg-backend` ‏۱، `kgkg-frontend` ‏۲ (سند ۱۸) |
| **Prometheus، Loki، Grafana، Alloy، cAdvisor، blackbox** | متریک، لاگ، داشبورد، probe | `ops/observability/`؛ compose در `/opt/observability` | `KG_PROMETHEUS_URL`، آستانه‌های `KG_ALERT_*`، `KG_ALERT_SLO_MONTHLY` | probeها Metis و ارائه‌دهندهٔ پیامک را شامل می‌شوند؛ آن دو بودجهٔ ثالث‌اند، نه ما (CHANGELOG ‏۲۰۲۶‑۱۱‑۰۳) |
| **Umami** | تحلیل محصول | `/opt/umami`، `ops/umami/` | خوانده نمی‌شود | **[U]** |
| **Jira (KGTEC)، Trello، Slack** | پیگیری کار، بُرد آینه، ارتباط | در کد نیست؛ وظیفهٔ زمان‌بندی‌شده با نام `kgkg-daily-reconcile` در اپ دسکتاپ | — | ← سند ۲۸ |
| **TIS (Toyota Technical Information System)** | منبع دفترچه‌ها (خزنده / دانلودها) | `api/tis_crawler.py`، دروازهٔ `/kg-vnc/` (`vncauth.py`)، `/opt/toyota_tis` | `KG_TIS_*` | اعتبارنامه هرگز ثبت نمی‌شود؛ وضعیت حقوقی/مجوز **[U]** |
| **Partsouq** | خزش کاتالوگ قطعات | `api/partsouq_crawler.py`، `api/partsouq_build.py`، `ops/partsouq/partsouq_vin_crawl.py` | `KG_PS_*` | تا کنون فقط در اسناد ۰۰ و ۱۶ بود |

## قواعد تغییر یک یکپارچگی

۱. افزودن یا تغییر نام یک نام پیکربندی ← `python3 ops/governance/gen_inventory.py` را اجرا و متغیر را اینجا یا در سند مرجع مناسب توصیف کنید.
۲. هر چیزی که API پولی را فرامی‌خواند باید محدودیت نرخ و fallback داشته باشد؛ `api/quota.py` و `CHAT_RL_LIMIT` / `CHAT_RL_WINDOW` (فرانت‌اند) برای دستیار وجود دارند.
۳. پاسخ‌های ارائه‌دهنده را که ممکن است متن کاربر یا کلید داشته باشند لاگ نکنید.

</div>
