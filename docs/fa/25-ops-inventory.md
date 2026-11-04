<!-- i18n-source: 25-ops-inventory.md sha256:4e59d7b7b3b5 -->
<div dir="rtl" lang="fa">

# ۲۵ — موجودی عملیات: میزبان، واحدها، کانتینرها، پوشه‌ها

مکمل `11-operations-deployment.md` (دیپلوی و هشدارها چگونه کار می‌کنند) و `20-runbooks.md` (وقتی خراب شد چه کنیم). این فایل یک **موجودی لحظه‌ای** از آنچه وجود دارد است، با برچسب شواهد. عمداً فهرست است تا اختلاف با واقعیت به‌راحتی دیده شود. پیش از اتکا دوباره مشاهده کنید. بخش برگرفته از مخزن تولید می‌شود: `docs/generated/inventory.md` (واحدهای systemd در `ops/`، هر فایل `ops/`، jobهای CI).

## ۲۵٫۱ میزبان

یک سرور اوبونتو ۲۴ (`103.75.197.155`، hostname برابر `srv8684671457`) تولید، staging، QA و پشتهٔ مشاهده‌پذیری را اجرا می‌کند. [C سند ۱۱؛ D ‏GitHub #25]. دیسک `/` ‏۲۹۰ گیگابایت، ۷۵٪ پر (۲۱۶ گیگابایت) در ۲۰۲۶‑۱۱‑۰۴ [S].

## ۲۵٫۲ وضعیت تولید مشاهده‌شده در ۲۰۲۶‑۱۱‑۰۴ ساعت ۰۶:۰۰ UTC [S، فقط‌خواندنی]

- `/opt/KGKG` روی `8a380f6` = `origin/work`؛ دو فایل ردیابی‌نشده `KG_backend/RECONSTRUCTED-ACTIVITY.md` و `KG_backend/pgcut-marks.json` (← ریسک R6). اسناد ۱۶ تا ۱۸ ردیابی‌نشدهٔ قبلی در ۲۰۲۶‑۱۱‑۰۳ به `/root/prod-untracked-backup/` منتقل شدند و اکنون در مخزن‌اند. [D ‏Slack]
- کانتینرها: `kgkg-backend-<ts>` و `kgkg-frontend-<ts>` (سالم)، پشتهٔ مشاهده‌پذیری (Prometheus، node-exporter، blackbox، Grafana، cAdvisor، Loki، Alloy)، GlitchTip (web، worker، Postgres، Redis)، Umami (برنامه، Postgres).
- سرویس‌های میزبان در حال اجرا: Docker، nginx، PostgreSQL 16 (`postgresql@16-main`)، `kgkg-hostjobs.service` (پل host-job برای کانتینر بک‌اند، `ops/hostjobs/`)، و، هنگام اجرای staging، یک `kgkg-stage-<ts>.service` گذرا که `deploy.sh --staging <sha>` را اجرا می‌کند.
- `kgkg-backend.service` (واحد gunicorn پیش از کانتینر) **در حال اجرا نبود**. نشستی در ۲۰۲۶‑۱۱‑۰۲ آن را متوقف کرد چون کنار کانتینر روی پورت ۸۰۰۰ crash-loop می‌کرد؛ با `Restart=always` در حالت `disabled` ماند. اینکه اکنون mask یا حذف شده **[U]** است. دستورهای قدیمی‌تر `systemctl restart kgkg-backend` را دنبال نکنید. [D نشست f197e5f1]

## ۲۵٫۳ timerهای دیده‌شده روی میزبان [S]

| timer | مستند در جای دیگر | هدف |
|---|---|---|
| `kgkg-pipeline.timer` | سند ۱۱ | `pipeline_tick` هر ۵ دقیقه |
| `kgkg-detect.timer` | سند ۱۱ | `realtime_tick` هر ۳۰ ثانیه |
| `kgkg-alerts.timer` | سند ۱۱ | `check_alerts` هر ۵ دقیقه |
| `kgkg-watchdog.timer` | سند ۱۱ (`ops/observability/`) | مرور هشدار را پایش می‌کند |
| `kgkg-bizsnap.timer` | سند ۱۱ | عکس فوری کسب‌وکار برای داشبوردها (`ops/observability/bizsnap.py`) |
| `kgkg-token-prune.timer` | سند ۱۸ | هرس روزانهٔ توکن‌های نشست منقضی |
| `kgkg-qa-nightly.timer` | `ops/qa/` در مخزن | ساعت ۰۱:۳۰ UTC؛ `qa/nightly.sh origin/work` را از worktree مربوط به `/opt/KGKG_work` اجرا می‌کند (E2E، baseline DAST، baseline کارایی) |
| `kgkg-walcheckpoint.timer` | **مستندنشده** | ساعتی؛ هدف از نام استنباط شده (WAL checkpoint در SQLite) **[U]** |
| `kgkg-coverage.timer` | سند ۰۴ | حدود ۰۳:۲۴ UTC هر روز؛ `manage.py check_coverage` را اجرا می‌کند (پوشش عیب‌یابی و بازیابی هر خودرو در برابر baseline، طبق docstring آن) [C docstring، S timer] |
| `kgkg-outbox.timer` | سند ۱۱ می‌گوید **نصب نشده** | قالب در `ops/outbox/` دارای `ExecStart=/bin/true # REPLACE` است؛ در فهرست timerها نیست، مطابق سند [S] |

## ۲۵٫۴ پوشه‌ها زیر `/opt` [S فهرست، هدف از اسناد در جاهایی که موجود است]

| مسیر | هدف |
|---|---|
| `KGKG` | checkout تولید و هدف دیپلوی. هرگز دستی ویرایش نکنید |
| `KGKG_work` | worktree توسعه که QA شبانه استفاده می‌کند |
| `KGKG_staging`، `KGKG_qa` | پشته‌های staging و QA |
| `KGKG_release` | `staging.env`، `e2e/`، `promote-overrides.log`، `db-backups/` (سه `pg_dump` آخر از `kgkg`) |
| `KGKG_backups` | پشتیبان‌ها (محتوا **[U]**) |
| `KGKG_wt22` | **مستندنشده**؛ شبیه worktree بازمانده **[U]** |
| `glitchtip`، `observability`، `umami` | پروژه‌های compose برای پایش خودمیزبان |
| `kgci-tools`، `kgci-trivy` | **مستندنشده**؛ ابزار گیت CI **[U]** |
| `partsouq`، `toyota_tis` | خزندهٔ قطعات (`api/partsouq_crawler.py`، `ops/partsouq/`) و داده دانلود TIS (سند ۱۵) |
| `npmbuild*.log`، `npminstall.log`، `pipinstall.*` | لاگ‌های build از دورهٔ پیش از کانتینر **[U]** |

همچنین بیرون از `/opt` (در نشست‌ها نام برده شده، اینکه هنوز موجودند **[U]** است): `/root/downloads` (ZIPهای منبع)، `/root/parts_build`، `/root/partsouq_crawl`، `/root/pgmig`، `/root/prod-untracked-backup/`، `/root/backup_snapshot/` (محل آماده‌سازی snapshot ساعتی خارج از میزبان؛ مهر `SNAPSHOT_AT` را watchdog می‌خواند).

## ۲۵٫۵ آنچه کار مستندسازی بررسی نمی‌کند

`.env.prod` (مقدارها هرگز)، پیکربندی زندهٔ nginx، فهرست schemaهای PostgreSQL، فایل‌های cron کاربران دیگر، محتوای پشتیبان‌ها، تنظیمات Cloudflare. هر چیز در این حوزه‌ها در هر جای این اسناد **[U]** برچسب می‌خورد. در ۲۰۲۶‑۱۱‑۰۴ یک گذر فقط‌خواندنی دوم تلاش شد و لایهٔ مجوز آن را رد کرد؛ برای دستورهای مشخص به تأیید مالک نیاز دارد.

## ۲۵٫۶ کنترل رانش برای این فایل

نیمهٔ مخزن این موجودی تولید و در CI بررسی می‌شود. نیمهٔ میزبان نمی‌تواند: مشاهدهٔ انسان یا عامل است. بررسی‌های `docs/AGENTS.md` بخش ۶ و دستورات میزبان در سند ۱۱ بخش ۱۱٫۱ را پس از هر تغییر واحدها یا پوشه‌ها دوباره اجرا کنید و تاریخ ابتدای بخش ۲۵٫۲ را فقط وقتی جابه‌جا کنید که اجرا کرده‌اید.

## ۲۵٫۷ نقشهٔ `ops/` (هدف‌ها از سرصفحهٔ هر فایل) [C]

| مسیر | هدف |
|---|---|
| `ops/deploy/deploy.sh`، `kgkg-promote`، `gate.sh` | build، staging، promote، rollback؛ `gate.sh` گیت کیفیت است که در worktree تمیز با محیط پاک‌شده (بدون رازهای تولید، پیامک، Sentry یا Metis) اجرا می‌شود. سند ۱۱ بخش ۱۱٫۳ |
| `ops/deploy/ci_evidence.sh` | گزارش می‌دهد GitHub CI دربارهٔ یک کامیت چه می‌گوید (`verdict <sha>` ← pass/fail/unknown) تا promote بتواند CI سبز را الزامی کند |
| `ops/deploy/ci_is_tip.sh` | اگر کامیت هنوز tip شاخه‌ای باشد که CI در حال stage آن است با کد ۰ خارج می‌شود (CI اجراهای جایگزین‌شده را لغو می‌کند) |
| `ops/deploy/prune_images.sh` | ایمیج‌های انتشار هر-sha را که هیچ‌کس لازم ندارد حذف می‌کند؛ SHAهای داده‌شده و هر چیز در حال استفاده را نگه می‌دارد. هرگز `docker prune -a` |
| `ops/deploy/cutover_postgres.sh` | انتقال یک‌باره پایگاه پرتال از SQLite به PostgreSQL (`--rehearse`، `--back`) |
| `ops/deploy/check_migrations.py` | migrationهایی را که انتشار قبلی نمی‌تواند در برابرشان اجرا شود رد می‌کند (ایمنی rollback) |
| `ops/deploy/sanitize_staging_db.py` | نسخهٔ staging/QA پایگاه پرتال را با داده شخصی ماسک‌شده می‌سازد، با `--strict-audit` در حالت بسته شکست می‌خورد |
| `ops/docker/*.Dockerfile`، `containers.sh`، `backend-requirements.lock` | ایمیج‌های تولید (فرانت‌اند `NEXT_PUBLIC_*` را هنگام build ثابت می‌کند)؛ کانتینرهای شبکهٔ میزبان با bind روی loopback؛ کمک‌های source شده توسط `deploy.sh` |
| `ops/hostjobs/hostjobs_daemon.py` + `kgkg-hostjobs.service` | سمت میزبان `api/hostjobs.py`: spool درخواست‌های JSON از کانتینر بک‌اند؛ فهرست ثابت اقدام با پارامترهای اعتبارسنجی‌شده |
| `ops/nginx/*` | پیکربندی سایت، محدودیت‌ها، احراز رسانه، logrotate برای nginx و ModSecurity (لاگ ممیزی modsec روزانه می‌چرخد، ۱۴ نسخه) |
| `ops/observability/*` | Loki، Alloy، provisioning مربوط به Grafana، Prometheus، blackbox، `watchdog.py`، `bizsnap.py`، `delivery.py` (متریک‌های DORA از لاگ‌های دیپلوی و git). هشدار در `api/alert_rules.py` می‌ماند؛ این پشته برای جست‌وجو و نمودار است؛ همه روی loopback bind می‌شوند (تونل SSH) |
| `ops/umami/*` | تحلیل بدون کوکی؛ nginx فقط اسکریپت tracker و نقطهٔ collect را زیر `/stats/` منتشر می‌کند |
| `ops/qa/*` | سرویس و timer مربوط به QA شبانه (ساعت ۰۱:۳۰ UTC) |
| `ops/outbox/*` | قالب‌های واحد برای صندوق خروجی اعلان (نصب‌نشده؛ `ExecStart` جایگزین است) |
| `ops/rag/*` | آزمایش‌های آفلاین: بارگذارها و benchmarkهای pgvector/FTS، جاروب آمیزش، معناداری زوجی، dump کاندیدها. در مسیرهای تولید اجرا نمی‌شود |
| `ops/cardb/*` | بارگذار خودرو در PostgreSQL و بررسی تطابق ([23](23-data-layer.md)) |
| `ops/partsouq/partsouq_vin_crawl.py` | خزش مؤدبانهٔ Partsouq برای یک خودرو؛ روی چالش پایدار Cloudflare متوقف می‌شود |
| `ops/security/*` | baseline مربوط به bandit، فهرست مجاز npm audit و گیت (`npm_audit_gate.mjs`: فقط روی advisoryهای خارج از فهرست مجاز در شدت مشخص یا بالاتر شکست می‌خورد) |
| `ops/governance/*` | تازگی مستندات، ردیابی‌پذیری PR، موجودی تولیدشده + بررسی رانش |

</div>
