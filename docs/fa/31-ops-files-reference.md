<!-- i18n-source: 31-ops-files-reference.md sha256:036da1a585c7 -->
<div dir="rtl" lang="fa">

# ۳۱ — مرجع فایل‌ها و واحدهای عملیاتی (پایش، لاگ، تحلیل، ابزار آفلاین RAG، baselineهای امنیتی)

مکمل [25-ops-inventory.md](../25-ops-inventory.md) (نقشهٔ `ops/`). هر آنچه اینجا آمده از فایل‌های `origin/work` در نسخهٔ `f078878` خوانده شده است **[C]**. اینکه یک پشته اکنون روی میزبان *در حال اجراست* مگر جایی که ذکر شده **[U]** است؛ محدودیت SSH در طول این کار مانع راستی‌آزمایی تازه شد. نسخهٔ انگلیسی: [../31-ops-files-reference.md](../31-ops-files-reference.md).

## ۳۱٫۱ ایمیج فرانت‌اند — `ops/docker/frontend.Dockerfile`

ساخت دومرحله‌ای روی `node:20-bookworm-slim`.

1. **build**: اجرای `npm ci` از روی `kg_frontend/package-lock.json`؛ آرگومان ساخت `NEXT_PUBLIC_API_BASE` (پیش‌فرض `/kg-api`) هنگام ساخت داخل bundle ثابت می‌شود؛ سپس `npm run build` و `npm prune --omit=dev`. تله‌متری خاموش است.
2. **runtime**: بسته‌های سیستم‌عامل ارتقا می‌یابند (ایمیج پایه از اصلاحات امنیتی توزیع عقب است)، `curl` برای health check می‌ماند و `npm`، `npx`، `corepack`، `yarn` **حذف می‌شوند** چون فقط وابستگی‌های بسته‌بندی‌شدهٔ خود را به شمار آسیب‌پذیری‌ها اضافه می‌کنند؛ سرور با `node_modules/.bin/next` شروع می‌شود. مقدار `ENV PORT=3000` است و آرگومان ساخت `KG_RELEASE` به متغیر محیطی تبدیل می‌شود. `HEALTHCHECK` هر ۱۵ ثانیه (timeout ۵ ثانیه، دورهٔ شروع ۶۰ ثانیه، ۴ تلاش) روی `http://127.0.0.1:${PORT}/`. دستور اجرا: `next start -p ${PORT} -H ${KG_BIND:-127.0.0.1}`.

پیامدها: مقدارهای `NEXT_PUBLIC_*` در زمان اجرا قابل تغییر نیستند (باید ایمیج دوباره ساخته شود)؛ رازهای زمان اجرا فقط از فایل envی می‌آیند که `ops/docker/containers.sh` (`KG_FE_ENV`) می‌دهد. hadolint این فایل را در CI (job با نام `security`) بررسی می‌کند. همتای بک‌اند `ops/docker/backend.Dockerfile` است (gunicorn؛ ← [29](29-environment-reference.md) بخش ۲۹٫۳).

## ۳۱٫۲ پشتهٔ مشاهده‌پذیری — `ops/observability/`

با `docker-compose.yml` تعریف می‌شود (نسخه‌های ثابت: Loki 3.4.2، Alloy v1.7.5، Grafana 11.5.2، Prometheus v3.2.1، node-exporter v1.9.0، cAdvisor v0.52.1، blackbox-exporter v0.26.0). همهٔ پورت‌ها فقط روی **`127.0.0.1`** بسته می‌شوند؛ به Grafana از طریق تونل SSH دسترسی داده می‌شود (`ssh -L 3001:127.0.0.1:3001 root@<vps>`، کامنت ابتدای compose). سقف حافظه: Loki یک گیگابایت، Alloy ‏۵۱۲ مگابایت، Grafana ‏۵۱۲ مگابایت، Prometheus یک گیگابایت، cAdvisor ‏۵۱۲ مگابایت، node-exporter و blackbox هرکدام ۱۲۸ مگابایت. volumeهای نام‌دار: `prometheus-data`، `loki-data`، `alloy-data`، `grafana-data`.

<div dir="ltr">

```
 backend (/var/log/kgkg/*.jsonl) ─┐
 nginx access/error logs ─────────┼─► Alloy ─► Loki (90 d)  ─┐
 (further sources: see config.alloy) ─────┘                  ├─► Grafana (127.0.0.1:3001)
 backend /kg-metrics (bearer) ─┐                             │
 node-exporter :9100 ──────────┼─► Prometheus (30 d) ────────┘
 cAdvisor :8080 ───────────────┤        ▲
 blackbox :9115 probes ────────┘        └── alert_rules._infra reads 127.0.0.1:9090
```

</div>

| فایل | آنچه پیکربندی می‌کند |
|---|---|
| `prometheus.yml` | مقدار `scrape_interval: 30s`. jobها: `prometheus` (خودش)، `kgkg_app` (مسیر `/kg-metrics` روی شنوندهٔ scrape حلقوی `172.19.0.1:8081`؛ توکن bearer از فایل mount‌شدهٔ `/etc/prometheus/metrics_token` و هرگز درون‌خطی)، `node` (`172.19.0.1:9100`)، `cadvisor`، `probe` (ماژول `http_2xx`، هر ۶۰ ثانیه، هدف‌ها `https://kgtechvault.com/` و `…/kg-api/api/health/`)، `probe_ext` (ماژول `http_reachable`، هدف‌ها `https://api.metisai.ir/` و `https://console.melipayamak.com/` یعنی ارائه‌دهندگان LLM و پیامک). نگهداشت روی دستور کانتینر تعیین شده است: `--storage.tsdb.retention.time=30d`. |
| `blackbox.yml` | ماژول `http_2xx` (timeout ۱۰ ثانیه، IPv4، User-Agent سفارشی) و `http_reachable` که کدهای 200/301/302/400/401/403/404/405 را «قابل دسترس» می‌شمارد، چون برای APIهای ثالث حتی خطای احراز هویت هم قابل‌دسترسی‌بودن را ثابت می‌کند. |
| `loki.yml` | Loki تک‌فرایندی، ذخیره‌سازی روی فایل‌سیستم، طرح TSDB نسخهٔ v13 از ۲۰۲۶‑۰۱‑۰۱، `retention_period: 90d`، نرخ ورود ۸ مگابایت بر ثانیه (burst برابر ۱۶)، metadata ساختاریافته مجاز، گزارش analytics خاموش، `auth_enabled: false` (فقط حلقوی). |
| `config.alloy` | لاگ‌ها را به Loki می‌فرستد. لاگ‌های JSON جنگو `/var/log/kgkg/*.jsonl` (job با نام `kgkg-backend`؛ برچسب‌های `level` و `logger`؛ زمان از فیلد `ts`)، `access.log`/`error.log` در nginx (job با نام `nginx`، برچسب `stream` و کلاس وضعیت) و منابع بیشتر در ادامهٔ فایل (برچسب‌ها عمداً کم‌کاردینالیتی نگه داشته شده؛ بقیه با `| json` یا فیلتر خط پرس‌وجو می‌شود). |
| `kgkg-watchdog.service` | ← بخش ۳۱٫۵. |

نکات عملیاتی:

- خود برنامه هشدارهایش (پیامک) را از `api/alert_rules.py` صادر می‌کند که بخشی به نام `_infra` دارد و Prometheus محلی را روی `127.0.0.1:9090` می‌خواند. Grafana برای بررسی است، نه مسیر page. آستانه‌ها: [29](29-environment-reference.md) بخش ۲۹٫۵.
- سکوتِ هشدار خودش یک ریسک است: watchdog (بخش ۳۱٫۵) وجود دارد چون یک‌بار موتور هشدار بی‌صدا مرده بود.
- **اینجا بررسی نشده [U]:** چه داشبوردهایی در نمونهٔ در حال اجرای Grafana وجود دارند و آیا پشته اکنون بالاست. ایجاد داشبورد همان چیزی است که سرویس Grafana در compose mount می‌کند؛ پیش از فرض وجود یک داشبورد آن را بخوانید.

## ۳۱٫۳ چرخش لاگ — `ops/nginx/logrotate-nginx.conf` و `logrotate-modsecurity.conf`

| فایل | قاعده |
|---|---|
| `logrotate-nginx.conf` | `access.log` و `error.log` **صریحاً فهرست شده‌اند، نه با الگوی glob**: الگوی `/var/log/nginx/*.log` فایل `modsec_audit.log` را هم می‌گرفت که فایل دیگری آن را تعریف می‌کند؛ ورودی تکراری باعث می‌شود logrotate کل فایل را رد کند و لاگ‌های nginx از ۲۰۲۶‑۱۰‑۲۷ تا زمان اصلاح چرخش نشدند (کامنت فایل). روزانه، ۱۴ نسخه، فشرده‌سازی با تأخیر، `create 0640 www-data adm`، و `nginx rotate` در postrotate. |
| `logrotate-modsecurity.conf` | فایل `modsec_audit.log`: روزانه، ۱۴ نسخه، فشرده، `create 0640 www-data adm`، `dateext`، و بازگشایی nginx با `USR1`. ذاتاً پرحجم است (هدرهای کامل درخواست در هر برخورد)، پس نگهداشت کوتاه است؛ تصمیم WAF در `error.log` خود nginx هم خلاصه می‌شود که همان چیزی است که fail2ban می‌خواند. |

حریم خصوصی: هر دو لاگ شامل IP کلاینت و خط درخواست‌اند؛ به همین دلیل نگهداشت ۱۴ روز است. لاگ‌های برنامه را خود برنامه می‌چرخاند (`KG_LOG_DIR`).

## ۳۱٫۴ تحلیل محصول — `ops/umami/`

Umami خودمیزبان (`ghcr.io/umami-software/umami:postgresql-v2.15.1`) با کانتینر `postgres:16-alpine` مخصوص خودش و volume با نام `umami-db`. داشبورد روی `127.0.0.1:3002` بسته می‌شود (تونل `ssh -L 3002:127.0.0.1:3002`)؛ nginx **فقط** نقاط پایانی tracker را منتشر می‌کند (کامنت ابتدای compose). فایل `setup.sh` (یک‌بار، در `/opt/umami`) گذرواژهٔ پیش‌فرض ادمین Umami را به مقداری تصادفی می‌چرخاند که در `admin.secret` (حالت 077) نوشته می‌شود و وب‌سایت `kgtechvault.com` را ثبت و `website_id` آن را چاپ می‌کند. گذرواژه را هرگز چاپ نمی‌کند. پایگاه آن از `kgkg`/`kgkg_vec` جداست، پس داده‌های Umami در هیچ پشتیبان `kgkg` نیست. نحوهٔ بارگذاری tracker در فرانت‌اند در [24-integrations.md](../24-integrations.md) آمده است **[U]** (برای این سند دوباره بررسی نشد).

## ۳۱٫۵ واحدهای systemd

| واحد (مسیر در مخزن) | نوع | هدف و طراحی |
|---|---|---|
| `ops/observability/kgkg-watchdog.service` (به‌علاوهٔ timer با دورهٔ ۵ دقیقه) | oneshot | `/usr/local/lib/kgkg/watchdog.py` را با Python سیستمی (`-I`، بدون venv، بدون Django، بدون پایگاه داده) اجرا می‌کند و **مستقل از برنامه** است تا خرابی‌ای که برنامه را از کار می‌اندازد تنها ناظرش را هم از کار نیندازد. اسکریپت در هر promote توسط `deploy.sh` به آنجا کپی می‌شود (اجرا از درخت git باعث می‌شد یک فایل ردیابی‌نشده promote از نوع fast-forward را مسدود کند). کد خروج ۱ یعنی «موتور ناظر نیست و page ارسال شد»، پس واحد عمداً در `systemctl list-units --failed` به‌صورت failed دیده می‌شود. sandbox: `StateDirectory=kgkg-watchdog`، `ProtectSystem=strict`، فقط `/var/lib/kgkg-watchdog` و `/var/lib/node-exporter-textfile` قابل نوشتن، `ProtectHome=read-only` (نه `yes`: مهر snapshot زیر `/root` است و `yes` باعث می‌شد بررسی زیر واحد «مهر پیدا نشد» بگوید ولی با اجرای دستی موفق باشد)، `CPUWeight=50`. برای اعتبارنامهٔ پیامک `.env.prod` را می‌خواند. بررسی‌ها: تازگی مرور هشدار، سلامت محلی، واحدهای ناموفق، سنِ snapshot خارج از میزبان. تنظیمات: [29](29-environment-reference.md) بخش ۲۹٫۶. |
| `ops/qa/kgkg-qa-nightly.service` | oneshot | QA شبانه: `qa/nightly.sh origin/work` را از یک **worktree تازه و جداشده (detached)** از `origin/work` زیر `/opt/KGKG_qa/tree` (ساخته‌شده از `/opt/KGKG_work`) اجرا می‌کند، نه از درخت زنده. E2E مرورگر، DAST غیرفعال و baseline کارایی روی پشتهٔ ایزولهٔ QA (`qa/stack.sh`)؛ نتیجه در `/var/lib/node-exporter-textfile/kgkg_qa.prom` نوشته می‌شود که قاعدهٔ هشدار `_qa` را تغذیه می‌کند (`KG_ALERT_QA_STALE_H`). هر اجرا حدود ۱۵ دقیقه، `TimeoutStartSec=90min`، `Nice=15`، `IOSchedulingClass=idle`؛ کانتینرهای QA سقف CPU خودشان را دارند. ← [32-testing-and-qa.md](../32-testing-and-qa.md). |

اینکه این واحدها فعال‌اند و آخرین اجرایشان چه زمانی بوده **[U]** است (راستی‌آزمایی میزبان مسدود بود). مرجع معتبر `systemctl list-timers` روی میزبان است.

## ۳۱٫۶ ابزارهای ارزیابی آفلاین RAG — `ops/rag/`

این‌ها دستی روی ماشینی که مدل‌ها را دارد اجرا می‌شوند؛ **بخشی از سرویس‌دهی نیستند** و در CI هم اجرا نمی‌شوند.

| اسکریپت | هدف | ورودی ← خروجی |
|---|---|---|
| `dump_cands.py` | برای هر پرسش طلایی، ۲۰ نتیجهٔ برتر خط لولهٔ زنده (به ترتیب بازیابی) و امتیاز KG-Reranker هر کاندید را ذخیره می‌کند تا وزن‌های آمیزش آفلاین جاروب شوند، نه با یک اجرای ارزیابی دوساعته برای هر وزن. به تنظیمات جنگو، `sentence_transformers` و `RAG_RERANK_MODEL` در env نیاز دارد. | مجموعه‌های طلایی ← `<out>.jsonl` |
| `fusion_sweep.py` | رتبهٔ بازیابی و امتیاز reranker را برای هر پرسش آمیزش می‌کند: `a · z(ce) + (1 − a) · z(−rank)`؛ مقدار `a = 0` خط لولهٔ زنده و `a = 1` فقط reranker است. `a` را با **اعتبارسنجی متقاطع ۲-فولد** برمی‌گزیند (فولد A بر اساس میانگین nDCG@5 در ترکیب EN+FA انتخاب می‌کند، روی فولد B سنجیده می‌شود و برعکس) تا اعداد گزارش‌شده فقط روی پرسش‌های کنارگذاشته باشند؛ به‌علاوهٔ آزمون جایگشتیِ زوجی در برابر ترتیب زنده. | `<in>.jsonl` ← گزارش کنسول |
| `paired_significance.py` | آزمون جایگشتی زوجی (۱۰٬۰۰۰ نمونه‌گیری، seed برابر ۰) و bootstrap (۲٬۰۰۰) بین دو فایل `results.json` ارزیابی برای `known_item_en`، `known_item_fa`، `known_item_fa_rev` روی nDCG@5، P@1، R@10 و MRR. | دو `results.json` ← گزارش کنسول |

اسکریپت‌های همراه که پیش‌تر مستند شده‌اند: `pgvec_load.py`، `pgfts_load.py`، `pgvec_bench.py` ([23](../23-data-layer.md)). تفسیر نتایج: [30-ai-assistant-deep-dive.md](../30-ai-assistant-deep-dive.md) بخش ۳۰٫۱۱.

## ۳۱٫۷ baselineهای امنیتی — `ops/security/`

| فایل | نقش |
|---|---|
| `bandit-baseline.json` | baseline ثبت‌شدهٔ bandit (بر اساس `generated_at` در ۲۰۲۶‑۱۰‑۲۹T14:26:35Z تولید شده). `scan.sh` یافته‌های جدید را با آن مقایسه می‌کند، پس فقط یافته‌هایی که **در baseline نیستند** CI و گیت دیپلوی را مسدود می‌کنند. بازتولید آن یافته‌ها را پنهان می‌کند: تفاوتش را مثل کد بازبینی کنید. |
| `npm-audit-allow.json` | فهرست مجاز برای advisoryهای Node با کلید شناسهٔ GHSA که `npm_audit_gate.mjs` می‌خواند. `minSeverity` برابر `high` است و `allow` **خالی** است (هدف و وضعیت فعلی؛ `next@16.4.3` در ۲۰۲۶‑۱۰‑۲۷ همه را برطرف کرد). افزودن ورودی نیازمند مانع‌بودن، دست‌یافتنی‌بودن و بازبینی است (سیاست: `ops/security/README.md`). |

ماتریس گیت‌ها (shellcheck، hadolint، gitleaks، pip-audit، npm audit، trivy، bandit) و همتای سمت سرور آن در `ops/security/README.md` تعریف و در [32-testing-and-qa.md](../32-testing-and-qa.md) بخش ۳۲٫۸ خلاصه شده است.

</div>
