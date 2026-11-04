<!-- i18n-source: 11-operations-deployment.md sha256:6de144303c06 -->
<div dir="rtl" lang="fa">

# ۱۱ — عملیات و استقرار

## ۱۱٫۱ چیدمان سرور

یک میزبان اوبونتو ۲۴ با نشانی `103.75.197.155` (۱۶ هسته / ۳۱ گیگابایت RAM / ۲۹۰ گیگابایت دیسک؛ هنگام نوشتن این فصل حدود ۶۴٪ پر، در ۲۰۲۶‑۱۱‑۰۴ ‏۷۵٪ **[S]**). checkout تولید `/opt/KGKG` است (نسخهٔ کاری git؛ خود برنامه‌ها به‌صورت کانتینر از روی آن ساخته و اجرا می‌شوند، ← ۱۱٫۳). venv پایتون میزبان: `KG_backend/.venv` (۳٫۱۲)، که timerهای میزبان و jobهای pipeline استفاده می‌کنند. Node نسخهٔ ۲۰. موجودی کامل میزبان: [25-ops-inventory.md](25-ops-inventory.md).

### واحدهای systemd

| واحد | چیست |
|---|---|
| `kgkg-backend.service` (بازنشسته؛ اکنون کانتینرها سرو می‌کنند — ← ۱۱٫۳) | gunicorn با `KG_backend.wsgi` روی `:8000` — ۳ worker از نوع gthread × ۸ thread، `--timeout 300 --max-requests 20000(+jitter)`؛ env از `.env.prod` + متغیرهای HF آفلاین + `KG_WARMUP=1` |
| `kgkg-frontend.service` (بازنشسته؛ اکنون کانتینرها سرو می‌کنند — ← ۱۱٫۳) | ‏`npm run start` (Next.js) روی `:3000`؛ env از `kg_frontend/.env.production` |
| `nginx` | پراکسی معکوس روی `:80` (← ۱۱٫۲) |
| `kgkg-alerts.timer` ← سرویس | ‏`manage.py check_alerts` هر ۵ دقیقه (مرور هشدار + هرس نگهداشت) |
| `kgkg-outbox.timer` ← سرویس | ‏`manage.py process_outbox` هر دقیقه. **نصب نشده**؛ قالب‌های واحد در `ops/outbox/`. ← «صندوق خروجی اعلان» پایین |
| `kgkg-watchdog.timer` ← سرویس | ‏`ops/observability/watchdog.py` هر ۵ دقیقه — خود مرور هشدار را می‌پاید و اگر کسی نمی‌پاید با پیامک page می‌دهد |
| `kgkg-pipeline.timer` ← سرویس | ‏`manage.py pipeline_tick` هر ۵ دقیقه (watchdog / زمان‌بند / خلبان خودکار) |
| `kgkg-detect.timer` ← سرویس | ‏`manage.py realtime_tick` هر ۳۰ ثانیه (آشکارساز تغییر ← رویدادها) |
| `kgkg-pipeline-job<id>-a<n>` | واحدهای گذرا برای workerهای جداشدهٔ pipeline (systemd-run، Nice 15 / CPUWeight 25 / IO idle) |

### صندوق خروجی اعلان

پیامک/ایمیل پشتیبانی از طریق جدول `NotificationOutbox` (`api/notifications/`) می‌روند، هرگز مستقیم به ارائه‌دهنده. ردیف‌ها توسط `process_outbox` (و یک thread فرصت‌طلب) فرستاده می‌شوند، در ۱/۵/۱۵/۶۰/۲۴۰ دقیقه دوباره تلاش می‌شوند، سپس `dead` علامت می‌خورند و به‌صورت هشدار `notify:dead` بروز می‌کنند.

| متغیر | پیش‌فرض | معنا |
|---|---|---|
| `KG_NOTIFY_SMS`، `KG_NOTIFY_EMAIL` | `off` | مقدار `off` ردیف‌ها را `suppressed` می‌نویسد و چیزی نمی‌فرستد؛ `dry_run` فقط تولید متن و لاگ؛ `live` با ارائه‌دهنده تماس می‌گیرد. هر مقدار دیگر `off` است |
| `KG_NOTIFY_SMS_MAX_PER_HOUR` | `10` | سقف پیامک live؛ ردیف‌های بیشتر ۱۰ دقیقه به تعویق می‌افتند، هرگز حذف نمی‌شوند |
| `EMAIL_HOST`، `EMAIL_PORT`، `EMAIL_HOST_USER`، `EMAIL_HOST_PASSWORD`، `EMAIL_USE_TLS`، `KG_NOTIFY_FROM_EMAIL` | تنظیم‌نشده | تنظیمات SMTP؛ بدون آن‌ها ایمیل در حالت بسته شکست می‌خورد (`email not configured`) |

مقدار `sent` یعنی ارائه‌دهنده پیام را پذیرفت، نه اینکه تحویل شد. ترتیب فعال‌سازی: timer را نصب کنید (یک انسان، روی سرور)، یک کانال را روی `dry_run` بگذارید، ردیف‌ها را بازبینی کنید، سپس پیش از `live` تأیید صریح مالک را بگیرید.

### چت پشتیبانی (با اداره انسانی)

`api/support_chat/` گفتگوهای صفحهٔ فرود و مشتری را با کارکنان واقعی سرو می‌کند. وابستگی به AI، LLM یا RAG ندارد. پیش‌فرض‌های زیر مقدارهای اولیه‌اند که با متغیر محیطی تغییر می‌کنند.

| متغیر | پیش‌فرض | معنا |
|---|---|---|
| `KG_SC_POLL`، `KG_SC_SEND`، `KG_SC_SEND_HOUR`، `KG_SC_CONTACT`، `KG_SC_CSAT`، `KG_SC_REOPEN` | ‏`30/60`، `20/60`، `30/3600`، `10/60`، `5/60`، `5/60` | محدودیت‌های هر thread به‌صورت `count/seconds`؛ `0/0` یکی را خاموش می‌کند. پنجره‌های poll به‌ازای هر worker گانیکورن‌اند |
| `KG_SC_CREATE_IP`، `KG_SC_BAD_TOKEN_IP`، `KG_SC_STATUS_IP` | ‏`20/600`، `30/60`، `60/60` | به‌ازای هر IP: threadهای جدید، فقط بررسی‌های توکن ناموفق، خواندن status |
| `KG_SUPPORT_CHAT_ENABLED` | تنظیم‌نشده (خاموش) | کلید قطع. فقط `1` چت عمومی را روشن می‌کند: API آن‌گاه threadهای *جدید* بازدیدکننده را می‌پذیرد (threadهای موجود و پاسخ کارکنان در هر دو حالت کار می‌کنند) و، اگر برای سرور وب هم تنظیم شود، ویجت فرود/خرید رندر می‌شود. یک انسان آن را می‌زند، هرگز یک دیپلوی؛ پیش از دروازهٔ راه‌اندازی آن را تنظیم نکنید (docs/superpowers/plans، G2) |
| `KG_SUPPORT_RBAC` | تنظیم‌نشده (`off`) | اعمال نقش پشتیبانی: `off` (مدل مسطح ادمین امروز)، `audit` (همان دسترسی، ردیف ممیزی فقط‌شناسه برای هر درخواستی که اعمال رد می‌کرد) یا `enforce` (پیش‌فرض رد، محدود به نقش و intent، بدون جایگزین). تنظیم‌نشده، خالی و املاهای صریح `off`، `0`، `false`، `no`، `disabled`، `none` یعنی `off`؛ **هر مقدار ناشناختهٔ دیگر (غلط تایپی مثل `enforc`) اعمال می‌شود** (در حالت بسته، یک‌بار لاگ، 403 با `rbac_invalid_mode`، با `support_roles check` علامت می‌خورد)، پس اشتباه هرگز بی‌صدا RBAC را خاموش نمی‌کند. فقط وقتی `off` را به `audit` و سپس `enforce` ببرید که `manage.py support_roles check --for-enforce` با کد ۰ خارج شود؛ بازگشت = برگرداندن آن به `off`. فقط `/api/admin/support-chat/*` را کنترل می‌کند |
| `KG_SUPPORT_OWNERS` | تنظیم‌نشده | نام‌های کاربری مدیران جداشده با کاما که صرف‌نظر از هر جدول `support_owner` دارند (راه‌اندازی و بازیابی)؛ بدون حساسیت به حروف با ادمین‌های ACTIVE تطبیق می‌شود؛ غلط املایی چیزی نمی‌دهد، پس `support_roles check` گزارش می‌دهد. هرگز راز نیست |
| `NEXT_PUBLIC_SUPPORT_INBOX_REFRESH_S` | `20` | فقط زمان build: بازخوانی جایگزین صندوق ورودی کارکنان وقتی جریان رویداد قطع است. پیش‌فرض را بگذارید؛ پشتهٔ E2E آن را روی ۳۶۰۰ می‌گذارد تا اثبات کند خود جریان تنها تحویل می‌دهد |
| `KG_PRIVACY_DRAFT_PAGE` | تنظیم‌نشده (خاموش) | فقط سرور وب. مقدار `1` صفحهٔ پیش‌نویس `/privacy` را سرو می‌کند (هرگز ایندکس نمی‌شود، بنر می‌گوید تأیید نشده)؛ بدون آن route برابر 404 است |
| `KG_SUPPORT_REOPEN_DAYS` | `14` | مدتی که بازدیدکننده می‌تواند thread بستهٔ خودش را دوباره باز کند |
| `KG_SUPPORT_REPLY_TARGET_MINUTES` | تنظیم‌نشده | هدف پاسخ منتشرشده؛ تنظیم‌نشده یعنی هیچ وعده‌ای نشان داده نمی‌شود |
| `KG_SUPPORT_PRESENCE_WINDOW_S` | `60` | ping کارکنان تا چه مدت «متصل» حساب می‌شود |
| `KG_SUPPORT_WAIT_WARN_S`، `KG_SUPPORT_WAIT_CRIT_S` | ‏`300` / `900` | آستانه‌های `manage.py support_health` (بازدیدکنندگان منتظر پاسخ انسانی)؛ مقدار نامعتبر یا غیرمثبت به پیش‌فرض برمی‌گردد؛ هنوز هیچ‌چیز روی آن‌ها هشدار نمی‌دهد |
| `KG_SUPPORT_ALERTS` | تنظیم‌نشده (خاموش) | هشدار بازدیدکنندهٔ بی‌پاسخ روی موتور هشدار (`api/alert_rules.py`): ‏`1` = هشدار warning با نام `support:unanswered` (فقط داشبورد، هرگز پیامک)، `page` = علاوه بر آن هشدار critical با نام `support:unanswered:critical` پس از `KG_SUPPORT_WAIT_CRIT_S` که تحویل موجود یک‌بار پیامکش می‌کند؛ هر مقدار دیگر خاموش است. فقط شمارش‌ها در هشدار، هرگز داده پیام یا تماس |
| `KG_SUPPORT_RETENTION_*_DAYS`، `KG_SUPPORT_RETENTION_ENABLED` | پیشنهادها / تنظیم‌نشده | ‏`purge_support_chat` در برابر دوره‌های پیشنهادی گزارش می‌دهد؛ حذف به `ENABLED=1` و `--apply` نیاز دارد و هنوز سیاستی تأیید نشده |

routeهای چت از بدنهٔ درخواست‌های `AuditLog` کنار گذاشته شده‌اند (فهرست skip در `api/audit.py`)؛ اقدام‌های کارکنان فقط با شناسه ممیزی می‌شوند. پشتیبان‌ها داده حذف‌شده را تا پایان نگهداشت خودشان نگه می‌دارند.

### فایل‌های محیطی

`KG_backend/.env.prod`: ‏`DJANGO_SECRET_KEY` (الزامی — بدون آن boot امتناع می‌کند)، `DJANGO_DEBUG=0`، `DJANGO_ALLOWED_HOSTS`، `DJANGO_CORS_ORIGINS`/`_ALLOW_ALL`، `KG_ADMIN_TOKEN` (توکن ثابت ادمین ops)، `KG_TRUST_PROXY=1` (محدودسازی نرخ به‌ازای IP پشت nginx). تنظیمات اختیاری: آستانه‌های `KG_ALERT_*`، قواعد نرخ `KG_RL_*`، `KG_METRICS_FLUSH_S`، `KG_CARDB_POOL`، `KG_INVITE_EMAIL` (ایمیل دعوت به‌صورت پیش‌فرض خاموش — بدون SMTP)، `KG_FRONTEND_BASE_URL` (پایه لینک دعوت).

`kg_frontend/.env.production`: تنظیمات زمان اجرا و رازهای کانتینر فرانت‌اند (`NEXT_PUBLIC_API_BASE` دیگر اینجا نیست: آرگومان build در `ops/docker/frontend.Dockerfile` با پیش‌فرض `/kg-api` است؛ مقدار قدیمی‌تر مطلق `http://<ip>/kg-api` تاریخی است)، `BACKEND_URL=http://127.0.0.1:8000` (SSR + چت)، `METIS_API_KEY`، `METIS_BOT_ID` (LLM پولی — فقط سمت سرور).

## ۱۱٫۲ nginx

پیکربندی: `/etc/nginx/sites-enabled/kgkg`، در git با نام `ops/nginx/kgkg.conf` ردیابی می‌شود. پشتیبان‌ها باید در `/etc/nginx/config-backups/` باشند، **هرگز** در `sites-enabled/` — هر چیز آنجا مانده باشد nginx آن را include می‌کند و هر reload را می‌شکند (در ۲۰۲۶‑۱۰‑۲۷ شکست).

سرور عمومی، `:80` و `:443` (گواهی‌های مبدأ Cloudflare در `/etc/nginx/cloudflare/`): gzip برای JSON/متن؛ `^~ /kg-api/media/` انبار استاتیک را alias می‌کند (کش `private` ‏immutable ۳۰ روزه؛ هر فایل از طریق `auth_request` به `api/mediaauth.py` می‌گذرد، پس ورود و دسترسی به آن خودرو لازم است؛ `www-data` به پوشه‌های خودروی جدید دسترسی خواندن می‌خواهد)؛ `= /kg-api/api/events/stream/` پراکسی SSE بدون بافر است (read timeout برابر ۳۶۰۰ ثانیه)؛ `^~ /grafana/` فقط با کوکی تیکت معتبر ادمین (`api/grafanaauth.py`) پذیرفته می‌شود و سپس `X-WEBAUTH-USER` سمت سرور تنظیم می‌شود؛ `/kg-api/` به `127.0.0.1:8000` پراکسی می‌شود؛ `/` به `127.0.0.1:3000`.

دو چیز فقط برای پایش وجود دارند:

- `= /kg-api/api/metrics/` به‌کلی **ممنوع** است. تطبیق دقیق، پس بر پیشوند `/kg-api/` غلبه می‌کند: داخلیات برنامه چیزی نیست که اینترنت بتواند بخواهد، با توکن یا بدون آن.
- یک سرور دوم روی `:8081` دقیقاً یک location دارد، `= /kg-metrics`، که به `/api/metrics/` پراکسی می‌شود و به `172.19.0.0/16` و loopback فهرست مجاز شده. این وجود دارد چون ufw ‏`80/443` را فقط از بازه‌های Cloudflare می‌پذیرد — وضعیت درست برای origin پشت CDN، و چیزی که برای scrape نباید باز شود. ufw پورت `8081` را فقط از پل docker می‌پذیرد. سه قفل مستقل: دامنهٔ فایروال، فهرست مجاز nginx، توکن bearer.

  عمداً `snippets/kgkg-backend-proxy.conf` را include **نمی‌کند**: آن snippet `Host $host` را می‌گذارد، `proxy_set_header` دوم اضافه می‌کند نه جایگزین، و Django آن‌گاه دو مقدار Host می‌بیند و 400 می‌دهد.

## ۱۱٫۳ تحویل: CI، staging، promote

**تولید هرگز بدون یک انسان promote نمی‌شود.** هیچ timer، cron یا مسیر CI نمی‌تواند. این روی همین میزبان، با اینکه یک کلید به کدام فرمان گره خورده، اعمال می‌شود، نه با تنظیمی در GitHub.

### مسیری که یک تغییر می‌پیماید

۱. **روی شاخهٔ `work` کار کنید**، در worktree با نام `/opt/KGKG_work` یا روی لپ‌تاپ. تولید (`/opt/KGKG`) هرگز دستی ویرایش نمی‌شود؛ `deploy.sh` درخت زندهٔ کثیف را رد می‌کند و فقط fast-forward می‌کند.
۲. **Push.** ‏`.github/workflows/ci.yml` روی هر شاخه اجرا می‌شود: مجموعهٔ بک‌اند با کف پوشش (`ops/deploy/coverage_min`)، lint فرانت‌اند (کف هشدار در `ops/deploy/lint_max_warnings`) و build تولید، هر دو ایمیج تولید ساخته و بوت‌شده، و گیت‌های امنیتی — shellcheck، hadolint، gitleaks، pip-audit، npm audit، و اسکن trivy هر دو ایمیج. سیاست و فایل‌های استثنا: `ops/security/README.md`.
۳. **Staging، خودکار.** روی push به `work` با همه چیز سبز، job با نام `stage` از این سرور می‌خواهد همان کامیت را stage کند. سرور `ops/deploy/deploy.sh --staging <sha>` را اجرا می‌کند: گیت در worktree یک‌بارمصرف با محیط پاک‌شده (ابتدا اسکن‌های امنیتی — bandit، pip-audit، npm audit از طریق `ops/security/scan.sh`، همان CI — سپس تست‌ها، lint، build)، ساخت هر دو ایمیج، اجرا روی `:8110`/`:3107` در برابر **نسخهٔ پاک‌سازی‌شده** پایگاه داده تولید، migrate آن، و smoke مسیرهای واردشده با توکن QA ساخته‌شده در همان نسخه. تولید دست‌نخورده است. نتیجه در `/opt/KGKG_release/staging.env` ثبت می‌شود.

   smoke واردشده شامل `ops/deploy/smoke_fleet.py` (GETهای فقط‌خواندنی) است: برای خودروهایی که حساب QA به آن‌ها اعطا شده، پرچم‌های `has_manual` / `has_parts` در `/api/auth/fleet/` باید با نقاط پایانی دفترچه و قطعات هم‌خوان باشند و کاتالوگ قطعات باید تا یک برگ با ردیف قطعه قابل پیمایش باشد. فقط آنچه آن حساب اعطا دارد را می‌بیند، پس دسته‌ای بدون خودرو `SKIP` چاپ می‌کند (بررسی اجرا نشد، نگذشت)؛ `KG_SMOKE_STRICT=1` اجرا را روی چنین skipی شکست می‌دهد. Staging `kgkg_vec` و `_parts` تولید را به اشتراک می‌گذارد، پس این بررسی‌ها شواهد داده واقعی‌اند، و پرچم‌ها و نقاط پایانی را اثبات می‌کنند، نه اینکه chip رندر می‌شود. تست‌های خودش: `smoke_fleet.py --selftest`.
۴. **Promote، دستی:**

<div dir="ltr">

   ```bash
   kgkg-promote <sha>     # or bare, to promote whatever CI last staged
   kgkg-promote --status  # live release, last staged, what would change
   ```

</div>

   کامیتی را که رکورد staging موفق ندارد، یا بیش از ۷۲ ساعت پیش stage شده، و کامیتی را که اجرای **کامل** E2E مرورگر موفق ثبت‌شده توسط `qa/run_e2e.sh` (`/opt/KGKG_release/e2e/<sha>.env`، آن هم ۷۲ ساعت) ندارد رد می‌کند، مگر عبارت عمدی طولانی‌تری تایپ کنید (`promote <sha> without staging|e2e|staging and e2e`)؛ هر override چنین به `/opt/KGKG_release/promote-overrides.log` اضافه می‌شود. کامیت‌ها و فایل‌هایی را که اعمال می‌شود، وجود migration و تغییر قفل وابستگی را چاپ می‌کند و سپس کلمهٔ `promote` را می‌خواهد. `--yes` ندارد.

   `deploy.sh` سپس پیش از لمس تولید گیت و staging را روی آن کامیت دوباره اجرا می‌کند: نتیجهٔ CI شاهد است، نه مجوز.

۵. **پیکربندی nginx بخشی از انتشار است.** ‏`ops/nginx/kgkg.conf`، `kgkg-limits.conf` و `kgkg-mediaauth.conf` در برابر nginx در حال اجرا *پیش از* گیت اعتبارسنجی می‌شوند (پیکربندی بد با تولید دست‌نخورده متوقف می‌کند) و *پس از* جایگزینی کانتینر نصب می‌شوند، تا پیکربندی با کدی که اکنون سرو می‌کند جفت شود. پیکربندی که nginx رد کند برگردانده و انتشار rollback می‌شود. این وجود دارد چون اصلاح دروازهٔ رسانه به هر دو نیمه نیاز دارد — بررسی مسیر نرمال‌شده در `api/mediaauth.py` و کلید کش نرمال‌شده در nginx — و اصلاح امنیتی نباید به یادآوری یک گام دستی وابسته باشد. پشتیبان‌ها به `/etc/nginx/config-backups/` می‌روند.

۵. **خود promote:** پشتیبان DB ← fast-forward ← migrate در ایمیج جدید ← کانتینر جدید بک‌اند *کنار* قدیمی روی `:8000` بالا می‌آید (SO_REUSEPORT) و قدیمی فقط وقتی متوقف می‌شود که جدید سالم باشد، پس وقفه‌ای نیست؛ فرانت‌اند stop/start حدود یک ثانیه است. سپس smoke، شامل بررسی‌های پراکسی معکوس. هر شکستی خودکار به ایمیج‌های قبلی rollback می‌کند. migrationها **برگردانده نمی‌شوند** — افزایشی نگه دارید؛ پشتیبان DB پیش از دیپلوی راه بازگشت است.

### کلیدها و امتیاز

| forced command | نقش | افعال |
|---|---|---|
| `/usr/local/bin/kg-ci-gate` | `ci` | `stage`، `status` |
| `/usr/local/bin/kg-deploy-gate` | `operator` | `stage`، `status`، `deploy` |

کلید موجود در راز `DEPLOY_SSH_KEY` مخزن به `kg-ci-gate` گره خورده است. **نمی‌تواند** promote کند: نقش فعل `deploy` ندارد. رازِ نشت‌کردهٔ CI فقط یک اجرای staging می‌خرد. هر دو فعل تغییردهنده فقط کامیت ۴۰هگزایی را که از قبل روی `origin/work` است می‌پذیرند، `flock` نگه می‌دارند تا دو اجرا درهم نشوند، و به‌صورت واحد گذرای systemd اجرا می‌شوند تا قطع اتصال SSH نتواند دیپلوی را نیمه‌کاره بکشد. ماتریس تست می‌شود: `ops/deploy/test_gate_roles.sh`.

**GitHub امروز چگونه به این سرور می‌رسد (بررسی‌شده ۲۰۲۶‑۱۰‑۲۹ ساعت ۱۸:۳۰ UTC):** **SSH مستقیم به پورت عمومی**، نه تونلی که در ادامه شرح داده شده. روی میزبان `systemctl is-active cloudflared` پاسخ `inactive` می‌دهد و فایل اجرایی نصب نیست؛ `ufw status` پورت `22/tcp` را از Anywhere می‌پذیرد؛ و job با نام `stage` در اجرای CI شمارهٔ 40907083135 عبارت `direct SSH: not needed` را چاپ کرد، که خطی است که `ci_ssh.sh` وقتی `~/.ssh/kgkg-target` عبارت `TRANSPORT=cloudflare` را نمی‌گوید می‌نویسد. این بند وجود دارد چون بندهای پس از آن دو روز تونل را در زمان حال شرح می‌دادند در حالی که اجرا نمی‌شد، و سندی که دربارهٔ چیزی که ممیز با یک دستور می‌تواند بررسی کند اشتباه باشد اعتبار بیشتری از خود شکاف پیکربندی هزینه می‌برد.

آنچه در نبود تونل از پورت باز محافظت می‌کند: sshd فقط کلید می‌پذیرد (`passwordauthentication no`، `permitrootlogin without-password`، هر دو از `sshd -T` بازخوانده شد)، و `fail2ban` فعال است با یک jail به نام `sshd` از میان چهار jail. روزانه حدود ۴۳۰ تلاش احراز ناموفق می‌رسد و هیچ‌کدام بدون کلید نمی‌تواند موفق شود. مواجههٔ واقعی — `3389/tcp` باز به Anywhere با `xrdp` شنونده پشت آن، و بدون هیچ نشست انسانی ثبت‌شده‌ای که از آن استفاده کرده باشد — در ۲۰۲۶‑۱۰‑۲۹ بسته شد (`ufw delete allow 3389/tcp`؛ فایل‌های قواعد در `/root/ufw-user*.rules.bak-20261029-183306` پشتیبان گرفته شد). `xrdp` هنوز نصب و فعال است، پس برداشتن خود سرویس هنوز ارزش دارد.

**طراحی موردنظر، هنوز فعال نشده:** یک Cloudflare Tunnel. کانکتور `cloudflared` اینجا به Cloudflare وصل می‌شود؛ runner با `cloudflared access ssh` و یک توکن سرویس Cloudflare Access وارد می‌شود (یک Access application با یک سیاست *Service Auth* از hostname محافظت می‌کند)، روی sshd در `localhost:22` می‌نشیند و مانند بالا به `kg-ci-gate` گره خورده است. پورت ۲۲ نیازی به باز بودن روی اینترنت ندارد. سه قفل پشت‌سرهم: توکن Access، کلید SSH، forced command.

راه‌اندازی آن چهار گام در داشبورد Cloudflare و یک دستور است، به‌عنوان root: ‏`bash /opt/KGKG/ops/deploy/setup_ci_access.sh --tunnel <hostname>` (`ops/deploy/README.md` هر دو را دارد، و سه خطی که آن را از `origin/work` پیش از آنکه در انتشار زنده باشد اجرا می‌کنند). کلید اختصاصی `/root/.ssh/kgkg-github-ci` را می‌سازد، با `restrict` به `kg-ci-gate` گره می‌زند، کانکتور را نصب می‌کند، سپس از طریق Cloudflare دقیقاً مثل CI به همین ماشین وارد می‌شود، با کلید میزبان pin‌شده، و بررسی می‌کند Access درخواست بدون توکن را رد می‌کند. رازها را با `gh` می‌گذارد یا برای paste چاپ می‌کند. اجرای دوباره امن است؛ `--rotate` کلید را جایگزین می‌کند. بدون `--tunnel` به‌جای آن SSH مستقیم به نشانی عمومی را راه می‌اندازد (پورت ۲۲ باز، ورود با گذرواژه خاموش). روی runner، `ops/deploy/ci_ssh.sh` رازها را اعتبارسنجی می‌کند و برای هر شکست راه‌حل را نام می‌برد (توکن Access اشتباه یا منقضی، سیاستی که Service Auth نیست، کانکتور خاموش، کلید اشتباه، کلید میزبان کهنه، کلیدی که می‌توانست promote کند)؛ `ops/deploy/test_ci_ssh.sh` آن را تست می‌کند. تا ۲۰۲۶‑۱۰‑۲۹ هیچ‌یک از این رازها هرگز تنظیم نشده بود، پس job با نام `stage` هرگز به سرور نرسیده بود.

`.github/workflows/deploy.yml` پیش‌تر با سبز شدن CI خودکار promote می‌کرد و فقط وجود بازبین در یک environment گیت‌هاب جلویش را می‌گرفت. در ۲۰۲۶‑۱۰‑۲۷ از `work` حذف شد. این workflow از نوع `workflow_run` است و GitHub آن‌ها را از **شاخهٔ پیش‌فرض** (`main`) اجرا می‌کند، پس تا وقتی آن حذف در `main` ادغام نشود پس از هر اجرای CI روی `work` همچنان فعال می‌شود.

### داده staging

‏`ops/deploy/sanitize_staging_db.py` نسخه را پیش از سرو هر چیز بازنویسی می‌کند: جدول‌های اعتبارنامه خالی، هش گذرواژه‌ها با نشانگر غیرقابل‌استفاده جایگزین، شماره‌های تلفن با جعلی‌های قطعی و هم‌قالب جایگزین، ایمیل‌ها به `.invalid` اشاره داده می‌شوند، IPهای ممیزی تا `/24` ماسک. تعداد ردیف‌ها، کلیدهای خارجی، اعطاها و داده خودرو حفظ می‌شود — staging باید نماینده بماند. چت پشتیبانی (#79): ‏`contact_phone` و `contact_email` مثل بقیه ماسک می‌شوند، `contact_name` به `Staging Visitor` تبدیل می‌شود، متن پیام‌ها به `[sanitized message, N chars]`، referrer به origin بریده می‌شود، هش توکن بازدیدکننده غیرقابل‌استفاده می‌شود؛ `source_page` (مسیر خودمان) حفظ می‌شود. مقدارهای خالی خالی می‌مانند.

در حالت بسته شکست می‌خورد: staging (`deploy.sh`) و پشتهٔ QA (`qa/stack.sh`) `--strict-audit` را می‌دهند، پس جدولی که ستون شناسایی‌کننده‌ای را دارد که اسکریپت مدیریت نمی‌کند به‌جای چاپ هشدار build را شکست می‌دهد (آن را به `MASK_COLUMNS` اضافه کنید). پس از بازنویسی، هر ستون ماسک‌شده دوباره بررسی می‌شود و هر مقدار بازمانده اجرا را شکست می‌دهد و فقط شمارش‌ها را چاپ می‌کند. ‏`api/test_sanitizer_coverage.py` در CI مدل‌های Django را می‌پیماید، پس ستون جدید تلفن/ایمیل پیش از رسیدن به یک نسخه شکست می‌خورد.

### سایر افعال دیپلوی

<div dir="ltr">

```bash
ops/deploy/deploy.sh --status           # what is live, and the previous release
ops/deploy/deploy.sh --rollback         # back to the previous release
ops/deploy/deploy.sh --reload          # restart the live release, no gap
                                        # (picks up .env.prod changes)
ops/deploy/deploy.sh --staging <ref>    # stage without promoting
```

</div>

لاگ‌ها: `/opt/KGKG_release/logs/`. پشتیبان‌های DB: `/opt/KGKG_release/db-backups/` (سه تای آخر). وضعیت انتشار: `/opt/KGKG_release/state.env`. هر promote برچسب `deploy-<ts>` هم می‌زند و push می‌کند.

## ۱۱٫۴ pipeline پردازش داده (اداره‌شده توسط ادمین)

پنل ادمین ← «پردازش داده‌ها» (`/api/admin/pipeline/`). یک دکمه هر گام در انتظار را اجرا می‌کند: همگام‌سازی کاتالوگ ← ingest/embed/graph مربوط به RAG ← diag هر خودرو ← تازه‌سازی ممیزی، با پیشرفت زندهٔ هر مرحله، ETA بر پایهٔ توان مشاهده‌شده، زمان‌بندی/ازسرگیری/لغو، و یک خلبان خودکار (`PipelineSettings.auto_enabled`) که وقتی بار ۱ دقیقه‌ای به‌ازای هر هسته < آستانه (پیش‌فرض ۰٫۵۵) است پردازش داده جدید را شروع می‌کند.

تضمین‌ها: worker جداشده (از دیپلوی/بستن مرورگر جان سالم به در می‌برد؛ سرو در CPU/IO بر آن مقدم است)، هر مرحله افزایشی و امن در برابر kill (embed در پنجره‌ها commit می‌کند؛ `vec_blobs` همیشه یک پیشوند پیوسته است)، تک‌پرواز (claim اتمی پایگاه داده + اسکن /proc در برابر buildهای اجراشده از شل)، ازسرگیری watchdog (heartbeat + زنده‌بودن pid، تلاش‌های محدود)، پیشرفت از روی مصنوعات محاسبه می‌شود (پس از خرابی راستگو است).

**افزودن یک خودرو از ابتدا تا انتها:** ‏`<car>.db` را در `Database_warehouse/` + پوشهٔ تصاویر را در `static_warehouse/<car>/` بیندازید (دسترسی خواندن www-data را مطمئن شوید) ← pipeline آن را برمی‌دارد (حالت خودکار) یا ادمین شروع را می‌زند ← تمام. ‏`sync_car_catalog` به‌تنهایی اگر فقط پیش از رسیدن ایندکس مرور لازم دارید ردیف را ثبت می‌کند.

## ۱۱٫۵ پایش، هشدار، کیفیت داده

### چه چیزی چه چیزی را می‌پاید

| لایه | کجا | پوشش |
|---|---|---|
| میزبان و کانتینرها | Prometheus + node-exporter + cAdvisor | CPU، حافظه، دیسک، NIC، وضعیت هر کانتینر و ری‌استارت‌ها |
| uptime و TLS | blackbox-exporter، هر ۶۰ ثانیه | سایت، نقطهٔ پایانی سلامت API و دو upstream پولی (Metis، ارائه‌دهندهٔ پیامک)؛ انقضای TLS |
| برنامه | ‏`GET /api/metrics/` (`api/metrics_exposition.py`)، job با نام `kgkg_app` | درخواست‌ها، 4xx/5xx و تأخیر میانگین/بدترین به تفکیک گروه route، هشدارهای باز به تفکیک شدت، اندازهٔ ایندکس RAG و DB، نتایج کیفیت داده، jobهای pipeline، sha انتشار زنده |
| لاگ‌ها | Alloy ← Loki | بک‌اند، nginx و journal، قابل جست‌وجو در Grafana |
| خطاها | GlitchTip (سازگار با Sentry)، `127.0.0.1:8010` | استثناهای Django و Next با stack trace |
| کسب‌وکار | ‏`ops/observability/bizsnap.py` ← sqlite ← Grafana | ثبت‌نام، خرید، استفاده |
| هشدار | ‏`manage.py check_alerts`، هر ۵ دقیقه | دیسک، حافظه، زنده‌بودن DB، 5xx و تأخیر هر نقطهٔ پایانی، brute force ورود، شکست احراز ادمین، شکست پیامک، تنزل و هزینهٔ AI، رگرسیون کیفیت داده، ری‌استارت کانتینر، شکست probe، انقضای TLS ← ردیف‌های `SystemAlert` بدون تکرار + **پیامک** به `KG_ALERT_PHONES` |
| خود هشدار | ‏`ops/observability/watchdog.py`، هر ۵ دقیقه | اینکه موتور اصلاً هنوز در حال اجراست |

موتور هشدار برای قواعد زیرساخت Prometheus را می‌خواند (`api/alert_rules.py`، `_infra`)، و عمداً از یک آستانه هوشمندتر است: probe باید `KG_ALERT_PROBE_DOWN_MIN` دقیقه شکست بخورد تا page بدهد، از کار افتادن تقریباً همهٔ probeها شبکهٔ خود سرور تلقی می‌شود نه قطعی سرویس، و شکست مسیر عمومی وقتی بک‌اند روی loopback پاسخ می‌دهد هشدار دربارهٔ DNS است، نه page دربارهٔ بک‌اند. آن تمایز در ۲۰۲۶‑۱۰‑۲۲ آموخته شد. آستانه‌ها با env قابل تنظیم‌اند (`KG_ALERT_*`) تا بدون دیپلوی جابه‌جا شوند.

### watchdog

تا ۲۰۲۶‑۱۰‑۲۷ هیچ چیز موتور را نمی‌پایید: اگر `kgkg-alerts.timer` متوقف می‌شد یا سرویسش در هر اجرا شکست می‌خورد، نتیجه سکوت بود، و سکوت چیزی است که سیستم سالم هم شبیه آن است.

‏`ops/observability/watchdog.py` (`kgkg-watchdog.timer`) مسیر page را بررسی می‌کند — timer فعال، آخرین مرور اخیر و با کد خروج ۰، پاسخ‌دادن Prometheus — به‌علاوهٔ سرویس‌ها (سلامت بک‌اند، کانتینرهای تولید، دیسک). **فقط** وقتی مسیر page شکسته است page می‌دهد و وضعیت سرویس را در همان پیام حمل می‌کند، چون اگر موتور از کار افتاده باشد تنها واقعیت‌هایی که کسی خواهد گرفت همین‌هاست. تا وقتی موتور سالم است ساکت می‌ماند و هر هشدار را به موتور می‌سپارد.

با برنامه چیزی به اشتراک نمی‌گذارد: فقط کتابخانهٔ استاندارد، بدون Django، بدون virtualenv، بدون پایگاه داده. اعتبارنامه از `.env.prod` می‌آید. پیام‌ها از لینک پاک‌سازی می‌شوند چون ارائه‌دهندهٔ پیامک متنی را که لینک دارد رد می‌کند. هر بررسی همچنین در `/var/lib/node-exporter-textfile/` نوشته و scrape می‌شود، پس Grafana وضعیت را پیوسته بدون افزودن نویز نشان می‌دهد.

### داشبوردها

‏`https://kgtechvault.com/grafana/` (نیازمند تیکت ادمین)، provision شده از `ops/observability/provisioning/dashboards/json/`:

- **KGKG — Service health & delivery** — آیا کسی می‌پاید، چه چیزی زنده است، ترافیک و خطا به تفکیک گروه route، نسبت خطای guard‌شده، تأخیر، سلامت scrape
- **KGKG — Server & containers** — منابع میزبان و کانتینر
- **KGKG — Logs overview** — Loki
- **KGKG — Business** — عکس فوری bizsnap

«پایش سیستم» ادمین نمای درون‌محصول می‌ماند، و «سلامت داده‌ها» ممیزی کیفیت داده را اجرا می‌کند (`manage.py audit_vehicles [--fix]`): کامل‌بودن، تکراری‌ها بر اساس اثر انگشت محتوا، backlog کاتالوگ/استاتیک/RAG/diag، یکپارچگی. حالت fix تکراری‌ها را ادغام و قرنطینه می‌کند — هرگز حذف نمی‌کند.

نگهداشت: Prometheus ‏۳۰ روز؛ رویدادها حدود ۲۰ هزار ردیف؛ ردیف‌های بازدیدکننده حدود ۹۰ روز؛ تاریخچهٔ هشدار توسط `check_alerts` هرس می‌شود.

## ۱۱٫۶ پشتیبان و بازیابی

**یک پشتیبان ساعتی خارج از میزبان هست و در ۲۰۲۶‑۱۰‑۲۷ راستی‌آزمایی شد.**

یک سرور داخلی شرکت (`81.12.110.58`) هر ساعت یک‌بار از طریق کلید forced-command (`/usr/local/bin/kg-sync-gate`، که فقط فرستندهٔ rsync و اسکریپت snapshot را می‌پذیرد — بدون شل) وصل می‌شود و:

۱. ‏`/root/kgkg_snapshot.py` را اجرا می‌کند که `/root/backup_snapshot/` را از وضعیتی که از ZIPهای منبع قابل بازسازی نیست می‌سازد — `db.sqlite3`، `terms.db`، `translation.db` (هر سه از **API پشتیبان آنلاین** SQLite، چون در حالت WAL اجرا می‌شوند و کپی بایتی در میانهٔ تراکنش پاره است)، به‌علاوهٔ خروجی اصطلاحات، مجموعه‌های طلایی ارزیابی، پیکربندی nginx و منبع بک‌اند/فرانت‌اند؛
۲. آن snapshot را می‌کشد (حدود ۶۵۰ مگابایت که `db.sqlite3` حدود ۶۰۰ مگابایت آن است)؛
۳. ‏`/root/downloads/` (حدود ۱۳ گیگابایت ZIP منبع) و `/var/log/nginx/` را می‌کشد.

رازها عمداً کنار گذاشته شده‌اند: بدون `.env.prod`، بدون کلید مبدأ Cloudflare. این برای نسخه‌ای که از میزبان بیرون می‌رود تصمیم درستی است، و یعنی بازسازی bare-metal آن مقادیر را از هر جا که نگه داشته می‌شوند لازم دارد — به طراحی در هیچ پشتیبانی نیستند.

آنچه این پوشش می‌دهد و آنچه نه. راستی‌آزمایی ۲۰۲۶‑۱۰‑۲۷ پایگاه داده برنامه و پایگاه‌های جانبی کوچک را پوشش داد. اثبات **نکرد** که محتوای خودرو قابل بازیابی است. محتوای دفترچه ۲۲۲ خودرو فقط در پایگاه PostgreSQL با نام `kgkg_vec` (حدود ۵۸ گیگابایت) است: `cardb_pg.adopt()` فایل SQLite یک خودرو را پس از بارگذاری حذف می‌کند، `pg_dump` زمان دیپلوی فقط پایگاه `kgkg` را پوشش می‌دهد، و هیچ پشتیبانی از `kgkg_vec` در snapshot ساعتی یافت نشد (مشاهده ۲۰۲۶‑۱۱‑۰۳، نشست‌ها؛ دوباره راستی‌آزمایی کنید). ۱۵ کاتالوگ فقط‌قطعات و تصاویر استاتیک روی همان دیسک‌اند و نسخه‌ای یافت نشد. ZIPهای منبع هر ساعت خارج از میزبان کپی می‌شوند، اما اینکه هر خودرو از آن‌ها قابل بازسازی است و چقدر طول می‌کشد **اثبات نشده**، پس این بخش هیچ ادعایی نمی‌کند که انبار بازسازی‌پذیر است. ایندکس RAG (`_rag/`) از مخزن‌های محتوا مشتق است و تنها بخشی است که دورریختنی شمرده می‌شود. ← [23-data-layer.md](23-data-layer.md) و ریسک R1 در [27-open-risks-and-decisions.md](27-open-risks-and-decisions.md).

همچنین **[U]**: شرح snapshot بالا از `db.sqlite3` نام می‌برد، پایگاه تولید پیشین (منجمد در ۲۰۲۶‑۱۰‑۲۹). اینکه snapshot ساعتی اکنون کدام پایگاه‌های PostgreSQL را شامل می‌شود دوباره بررسی نشد؛ یک نشست گزارش داد فقط `kgkg` (۱۳۳ مگابایت) dump می‌شود.

علاوه بر آن، ارائه‌دهندهٔ هاستینگ هر ماه (پنجم) پشتیبان کامل سرور می‌گیرد. این سناریوی از دست رفتن کل میزبان را محدود می‌کند؛ snapshot ساعتی چیزی است که از دست رفتن روزمره را به یک ساعت محدود می‌کند.

نسخه‌های محلی روی همان دیسک هم هست و سریع‌ترین راه بازگشت از دیپلوی بد است، نه از فاجعه: `/opt/KGKG_release/db-backups/` (سه تای آخر، پیش از هر promote گرفته می‌شوند) و `db.sqlite3.bak_*` تاریخ‌دار کنار پایگاه.

### راستی‌آزمایی (گاهی انجام دهید — پشتیبانی که کسی بازیابی نمی‌کند یک حدس است)

<div dir="ltr">

```bash
# integrity + row counts of the snapshot against live, read-only
python3 -I /root/verify_restore.py
```

</div>

اجرای ۲۰۲۶‑۱۰‑۲۷: ‏`quick_check ok`، و `api_portaluser`، `api_company`، `api_companycaraccess`، `api_usercaraccess`، `api_activitylog`، `api_chatlog` و `api_systemalert` همگی دقیقاً با پایگاه زنده مطابق بودند، و فقط `api_trafficstat` به اندازهٔ ۷ ردیف عقب بود — رانش مورد انتظار برای snapshot ساعتی.

### آنچه از این میزبان تضمین **نمی‌شود**

- **نگهداشت در سمت دیگر.** اگر سرور داخلی به‌جای نگه‌داشتن نسخه‌ها آینه کند، خرابی اینجا ظرف یک ساعت منتشر می‌شود و نسخهٔ خوب از بین می‌رود. پشتیبان ماهانهٔ ارائه‌دهنده آن‌گاه تنها نقطهٔ بازیابی قدیمی‌تر است. ارزش تأیید روی آن سرور را دارد، نه اینجا.
- **اینکه کشیدن هنوز انجام می‌شود.** ‏`kgkg_watchdog_check{check="backup_snapshot"}` این را پوشش می‌دهد: `/root/backup_snapshot/SNAPSHOT_AT` را می‌خواند و وقتی snapshot قدیمی‌تر از `KG_WATCHDOG_SNAPSHOT_MAX_H` (پیش‌فرض ۶ ساعت) باشد ۰ می‌شود.

## ۱۱٫۷ قطعه‌دستورهای رانبوک عملیاتی

<div dir="ltr">

```bash
# what is live, what was staged
ops/deploy/deploy.sh --status
kgkg-promote --status

# status (the serving pair are containers, not systemd units)
docker ps --filter label=kgkg.env=prod
docker logs --tail 100 <the kgkg-backend container>   # the journalctl -t kgkg-backend tag belongs to the retired unit
systemctl status nginx kgkg-hostjobs

# is the alerting alive? (dry run never sends an SMS)
python3 -I /opt/KGKG/ops/observability/watchdog.py --dry-run
systemctl list-timers 'kgkg-*' --no-pager

# the smoke suite, read-only, safe against production
KG_SMOKE_NGINX=http://127.0.0.1 ops/deploy/smoke.sh \
  http://127.0.0.1:8000 http://127.0.0.1:3000

# the metrics Prometheus sees
curl -s -H "Authorization: Bearer $(cat /opt/observability/metrics_token)" \
  http://127.0.0.1:8081/kg-metrics | head -40

# django shell with prod env
cd /opt/KGKG/KG_backend && set -a && . ./.env.prod && set +a && .venv/bin/python manage.py shell

# tests (staging copy, never prod DB)
KG_RL_DISABLE=1 .venv/bin/python manage.py test api

# pipeline status from CLI
curl -s -H "Authorization: Bearer $KG_ADMIN_TOKEN" http://127.0.0.1:8000/api/admin/pipeline/ | python3 -m json.tool

# who is logged in / recent activity
.venv/bin/python manage.py shell -c "from api.models import ActivityLog; [print(a.user.username, a.action, a.created_at) for a in ActivityLog.objects.all()[:20]]"
```

</div>

### تله‌های عملیاتی شناخته‌شده (وقت واقعی خرج کرده‌اند — رعایتشان کنید)

۱. فایل‌های `*.md` به‌طور سراسری gitignore شده‌اند ← برای اسناد `git add -f`.
۲. عنوان/مسیر گره‌ها می‌تواند `/` داشته باشد که در ستون‌های `path` به‌صورت U+2044 کد می‌شود.
۳. اتصال‌های pool مربوط به پایگاه خودرو هرگز نباید توسط viewها بسته شوند.
۴. شمارش `vec_blobs` به `vec_blobs_rowids` نیاز دارد.
۵. Staging از :8110/:3107 استفاده می‌کند. ‏:8100 پروژهٔ دیگری روی این میزبان است — مال ما نیست.
۶. TLS زنده است (گواهی‌های مبدأ Cloudflare)؛ ufw پورت ۸۰/۴۴۳ را فقط از بازه‌های Cloudflare می‌پذیرد، پس انتظار نداشته باشید با IP به سایت برسید.
۷. فونت‌های WeasyPrint: فقط TTFهای کامل Vazirmatn همراه درست رندر می‌شوند.
۸. ‏`NEXT_PUBLIC_API_BASE` هنگام build ثابت می‌شود — پس از تغییر env دوباره build کنید.
۹. ردیف ProcessingJob بی‌کار `paused` (#1) تاریخی است — job شمارهٔ ۲ backfill ناوگان را کامل کرد؛ #1 را کورکورانه ازسرنگیرید.
۱۰. پشتیبان‌های پیکربندی nginx در `/etc/nginx/config-backups/` می‌روند، هرگز در `sites-enabled/` — nginx همه‌چیز آنجا را include می‌کند و reload شکست می‌خورد.
۱۱. اسکن gitleaks در حالت git وقتی نمی‌تواند مخزن را بخواند با کد ۰ خارج می‌شود، پس CI فایل‌سیستم را اسکن و تأیید می‌کند گزارشی نوشته شده. «ساده»اش نکنید و به حالت قبل برنگردانید.
۱۲. ‏`torch` به `setuptools<82` قفل می‌کند که دو advisory را که عمداً حمل می‌کنیم محدود می‌کند (`ops/security/pip-audit-ignore.txt`). ارتقای torch به پنجرهٔ برنامه‌ریزی‌شدهٔ embed دوباره نیاز دارد، نه ارتقای قفل.
۱۳. بدنهٔ پیامک قراردادی دارد که ارائه‌دهنده بی‌صدا اعمال می‌کند: بدنهٔ فارسی بدون خط لغو انتهایی رد می‌شود (Value 11)، و هر چیز شبیه لینک یا @domain رد می‌شود (Value 14) — عدد نقطه‌دار مثل IP یا درصد هم حساب می‌شود. از همان پاکت `api/alert_rules.deliver` / `sms_body()` در `ops/observability/watchdog.py` استفاده کنید و Value برگشتی را بررسی کنید: شناسهٔ رکورد بلند یعنی ارسال شد، هر چیز دیگر یعنی کسی page نشد.

</div>
