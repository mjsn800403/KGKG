<!-- i18n-source: 04-backend-reference.md sha256:6d1e84ee06c9 -->
<div dir="rtl" lang="fa">

# ۰۴ — مرجع بک‌اند (`KG_backend/api`)

یک اپ Django همه‌چیز را در خود دارد. ماژول‌ها، آنچه مالک آن‌اند و آنچه پیش از ویرایش باید دانست.

## سرو و احراز هویت

### `views.py` — کاتالوگ عمومی + محتوای دفترچهٔ گیت‌شده + نقاط پایانی RAG
- `brands_list_view` (GET `/`) — فهرست عمومی برندها (صفحهٔ فروش لازمش دارد)، کش ۶۰ ثانیه.
- `car_view` — اسب کاری محتوا برای `/brand/`، `/brand/year/`، `/brand/year/model/?seg=…`. حالت‌ها: brand←سال‌ها، year←مدل‌ها، model←پیمایش درخت گره‌ها. تعیین سال *مسامحه‌گر* است (دقیق ← بازگشت به brand+name) چون پیوندهای قدیمی دستیار ممکن است `'unknown'` داشته باشند. مسیر گره‌ها به‌صورت پارامترهای تکراری `?seg=` می‌آیند (عنوان‌ها ممکن است `/` داشته باشند). از pool مربوط به `cardb` استفاده می‌کند — **هرگز اتصال‌های pool را نبندید**.
- `assist_view`، `diagnose_view`، `search_view` — RAG/عیب‌یابی/جست‌وجوی معنایی، همه با `_guard_car_content` محافظت می‌شوند (ورود + گیت هر خودرو + عبور فهرست مجاز `allowed_cars`).
- `_guard_car_content` / `_resolve_car` / `_user_allowed_stems` — کمک‌های مجوزدهی محتوا (سند ۰۶ بخش ۶٫۴).
- `purchase_request_view` — POST عمومی با اعتبارسنجی + محدودیت نرخ.
- بازخورد: `feedback_rate_view` (👍/👎)، `feedback_pin_view` (pinهای کارشناسی)، `feedback_recent_view` (فید بازبینی ادمین)، `assist_feedback_view` (لاگ کلیک)، `eval_report_view` (نتایج ابزار ارزیابی آفلاین).
- `rewrite_image_urls`، `read_page_content`، `node_to_dict` — دست‌کاری HTML محتوا.

### `portal.py` — احراز هویت پرتال و ادمین، API CRUD ادمین
- `portal_user(request)` — تعیین‌کنندهٔ نشست: هدر Bearer **یا** کوکی `kg_portal_token` (مسیر SSR)؛ active/locked/انقضا را روی کاربر و شرکت بررسی می‌کند.
- `login_view` — نام کاربری یا ایمیل؛ برابرسازی زمان در برابر شمارش کاربران؛ فعالیت/رویداد ورود منتشر می‌کند. `logout_view`، `me_view`، `fleet_view` (خودروهای اعطاشده + روی دیسک)، `activity_view` (گیرندهٔ beacon فعالیت؛ دسته را از segmentها استخراج می‌کند).
- ادمین: `admin_login_view` (PlatformAdmin + AdminAuthToken)، `admin_overview_view`، `admin_packages_view`، `admin_requests_view` (+status)، `admin_cars_view`، `admin_companies_view` (+جزئیات: ساخت/به‌روزرسانی شرکت‌ها)، `admin_company_access_view` (دامنهٔ خرید؛ اعطاهای کاربر را هنگام تغییر دامنه هرس می‌کند)، `admin_users_view` (+جزئیات +دسترسی)، `admin_activity_view`، `admin_analytics_view` (تحلیل بین‌شرکتی). به‌روزرسانی کاربر توسط ادمین `enforce_org_consistency` را اجرا می‌کند.
- `_user_dict` شکل بارِ کاربر است که بین login/me/team مشترک است — پیش از تغییر آن را grep کنید.

### `admin_auth.py` / `portal_auth.py` — decoratorها
- `require_admin_token` — مقدار env با نام `KG_ADMIN_TOKEN` **یا** نشست `AdminAuthToken` (حالت DEBUG وقتی توکنی پیکربندی نشده باز است).
- `require_manager` / `require_analytics` — دروازه‌های توکن پرتال + قابلیت.
- `user_can_view_company_stream` — قاعدهٔ مخاطب SSE شرکت (مدیریت یا تحلیل).

### `access.py` — ستون فقرات RBAC (معنا در سند ۰۶)
نقش‌ها/سطوح، بسته‌ها، مقداردهی اولیهٔ قابلیت‌ها، کمک‌های legacy رتبه/دامنه (وقتی کاربر صندلی ندارد هنوز استفاده می‌شود)، دسترسی مبتنی بر صندلی از طریق `orggraph`، `manageable_user_ids` / `subtree_user_ids` / `manager_can_target`، `find_valid_supervisor` / `enforce_org_consistency`، نویسنده‌های اعطا `apply_user_access` / `apply_managed_access` / `manager_grantable_cars`، واجدیت AI (`user_ai_eligible`)، تعیین اسناد هر خودرو (`user_car_documents`)، طبقه‌بندی دستهٔ محتوا + `resolve_category`.

### `team.py` — پذیرش دعوت، تحلیل تیم، گزارش PDF
CRUD اعضا/نقش‌ها که اینجا بود (`team_members_view`، `team_roles_view`، `team_org_view` …) هنگامی **حذف شد** که بوم گراف سازمانی جایگزینش شد (`orggraph_api.py`، `api/org/*`؛ ← [06](../06-permissions-rbac.md) بخش ۶٫۶). آنچه مانده: پذیرش دعوت (`invite_view`: GET اعتبارسنجی می‌کند، POST گذرواژه را تنظیم، فعال و خودکار وارد می‌کند)، تحلیل استفادهٔ شرکت (`build_team_analytics`، `team_analytics_view`) و PDF فارسی (`team_report_pdf_view`). `_emit_team` (منتشرکنندهٔ قدیمی همگام‌سازی زندهٔ `team.*`) هنوز تعریف است اما در این نسخه فراخواننده ندارد **[C]**. **قاعدهٔ مرزی:** شناسه‌های فرم به‌صورت رشته می‌رسند؛ پیش از مقایسه با مجموعه‌های عدد صحیح با `_as_id` تبدیل کنید (دستهٔ باگ ۲۰۲۶‑۰۷‑۱۴).

### `orggraph_api.py` / `orggraph.py` — بوم گراف سازمانی
`api/org/graph|nodes|nodes/<id>|nodes/<id>/permission|nodes/<id>/create-user` (نوشتن فقط برای ریشه با `require_root`؛ هر عضو شرکت می‌تواند بخواند) و `api/admin/org/reassign-root/`. `orggraph.py` `NodePermission` یک صندلی را به وضعیت اعمال واقعی کامپایل می‌کند (`sync_node_to_user`)، یال والد بوم را روی `reports_to` آینه می‌کند، تصمیم می‌گیرد چه کسی صفحهٔ تیم را می‌بیند (`user_can_view_team`) و گراف شرکت‌های جدید را می‌کارد. معنا: [06](../06-permissions-rbac.md) بخش ۶٫۶.

### `ratelimit.py` — محدودکنندهٔ پنجرهٔ لغزان با مخزن مشترک
`@rate_limited(name, limit, window)`؛ برای هر IP از طریق `X-Real-IP`/آخرین hop در XFF وقتی `KG_TRUST_PROXY=1` (nginx تنظیم می‌کند). شمارنده‌ها در یک فایل SQLite (`KG_RL_STORE`، پیش‌فرض `/tmp/kg_ratelimit.sqlite3`) هستند که همهٔ worker‌های gunicorn در یک کانتینر مشترکاً استفاده می‌کنند، پس سقف در تعداد worker ضرب نمی‌شود؛ اگر فایل قابل استفاده نباشد محدودکننده به پنجرهٔ درون‌فرایندی برمی‌گردد (آن‌گاه ≈ worker × مقدار اسمی) و هرگز روی خطای خودش مسدود نمی‌کند. فایل محلی کانتینر و موقت است (با دیپلوی صفر می‌شود). برای تست `KG_RL_DISABLE=1`. قواعد با env به نام `KG_RL_<NAME>` قابل override‌اند. محدودکنندهٔ *poll* هر thread در چت پشتیبانی عمداً درون‌فرایندی است (← [35](35-support-system.md))؛ بقیهٔ محدودیت‌های آن از همین مخزن مشترک استفاده می‌کنند.

## بی‌درنگ و درخواست‌ها

### `events.py` — ستون فقرات SSE (سند ۰۹)
`emit`/`emit_company`/`emit_user` (INSERT با بهترین تلاش)، `stream_view` (SSE؛ احراز هویت ادمین یا پرتال؛ محدودسازی مخاطب؛ ازسرگیری Last-Event-ID؛ دنبال‌کردن ۱ ثانیه/heartbeat ‏۱۵ ثانیه/بازیافت ۳۰۰ ثانیه)، `recent_view` (همتای REST)، `snapshot_pending`، `detect_and_emit` (تفاوت اثر انگشت ← `data.detected`/`processing.pending`)، برش سرشکن‌شده تا حدود ۲۰ هزار ردیف.

### `requests_api.py` — چرخهٔ عمر CompanyRequest
فهرست/ساخت توسط مدیر (`company_requests_view`)، جزئیات/لغو؛ صندوق ادمین (`admin_company_requests_view`) و اقدام‌ها (گذار وضعیت، یادداشت، اولویت) — هر گذار برای هر دو مخاطب منتشر می‌شود. `_sanitize_payload` بار ساختاریافته را برای هر نوع فهرست مجاز می‌کند.

## تحلیل و پیشنهاد

### `recommend.py` (سند ۱۰)
`recommend_for_user` — ادامه بده / مرتبط (همسایگان گراف RAG، محدود به خودروهای مالک) / حوزه‌های تمرکز (تمایل دسته) / محبوب در شرکت / کاوش. `insights_for_manager` — بهره‌برداری صندلی، اعضای بی‌کار/برتر، پوشش دسته + شکاف‌ها. نقاط پایانی `recommendations_view`، `manager_insights_view`.

### `reporting.py` — گزارش PDF تیم با WeasyPrint به فارسی/RTL
تبدیل تاریخ جلالی (حسابی)، ارقام فارسی، SVGهای donut/روند. **تلهٔ فونت:** از TTFهای کامل رسمی Vazirmatn Regular/Bold در `reporting_assets/fonts/` استفاده می‌کند — فونت‌های subset/مشتق از woff2 حروف لاتین و `ل` را خراب می‌کنند؛ جایگزین نکنید. `<text>` در SVG در WeasyPrint bidi نمی‌گیرد — برچسب‌های مرکز، پوشش HTML هستند.

## عملیات

### `monitoring.py` (سند ۱۱)
`RequestMetricsMiddleware` (اول زنجیره؛ تجمیع درون‌حافظه ← flush دسته‌ای دوره‌ای به TrafficStat/VisitorSeen؛ زیر اجراکنندهٔ تست ساکت)، `system_snapshot` (وضعیت disk/mem/load/db/rag)، `evaluate_alerts` (هشدارهای disk/mem/زنده‌بودن db/نرخ 5xx/تأخیر/DQ؛ dedupe با کلید؛ رفع خودکار؛ `KG_ALERT_*` قابل تنظیم با env)، `prune_old_data`.

### `dataquality.py` (سند ۱۱)
ممیزی ناوگان: کامل‌بودن بخش‌های استاندارد (`&`/`and` و U+2044 را نرمال می‌کند)، نیازمندی‌های آگاه از پیشرانه (EV/هیبرید از روی stem)، اثر انگشت محتوا (مسیر ریشهٔ عمق ۰ خود درخت را حذف می‌کند — نسخه‌های کپی با نام "(1)" ریشهٔ اصلی را درون خود دارند)، ادغام تکراری‌ها (اعطاها + فعالیت دوباره اشاره داده می‌شود؛ فایل‌ها ← `_quarantine/`، هرگز حذف نمی‌شوند)، backlog هر خودرو. `run_audit_to_db` / `run_audit_async` برای پنل ادمین.

### `pipeline.py` (سند ۱۱)
`pending_work` (چه چیزی نیاز به پردازش دارد)، `start_job`/`resume_job`/`cancel_job` (claim اتمی تک‌پرواز + اسکن /proc در برابر buildهای اجراشده از شل)، `launch_worker` (واحد گذرای systemd-run، Nice 15/CPUWeight 25/IO idle؛ بازگشت به فرایند جداشدهٔ ساده)، `tick` (watchdog: heartbeat+زنده‌بودن pid ← راه‌اندازی مجدد، تلاش‌های محدود؛ زمان‌بند؛ شروع خودکار زیر آستانهٔ بار)، `job_dict` (بار پنل).

### `adminops.py`
`health_view` (زنده‌بودن عمومی)، `admin_data_quality_view` (GET گزارش / POST تازه‌سازی|رفع ← thread پس‌زمینه)، `admin_system_view`، `admin_traffic_view`، `admin_pipeline_view` (GET وضعیت / POST شروع|زمان‌بندی|ازسرگیری|لغو|تنظیمات)، `admin_processing_snapshot_view`، `admin_dashboard_view` (تجمیع KPI برای داشبورد زنده).

### `cardb.py`
pool با LRU برای هر thread (پیش‌فرض ۸ برای هر thread) از اتصال‌های فقط‌خواندنی پایگاه خودرو؛ بازگشایی با تغییر mtime/size؛ `breadcrumbs` با CTE بازگشتی؛ `ready_path` با TTL (۳۰ ثانیه) + ابطال کش. **viewها هرگز نباید اتصال‌های pool را `.close()` کنند.**

## زیرسیستم RAG (`api/rag/`، سند ۰۸)

`config.py` (مسیرها، رجیستری، `car_meta` با بازگشت به کاتالوگ)، `ingest.py` (استخراج blob/occurrence)، `embed.py` (bge-m3، commit پنجره‌ای)، `store.py` (دسترسی به ایندکس، جدول‌های vec)، `graph.py` (یال‌های semantic/crosslink/labor)، `retrieve.py` (بازیابی ترکیبی + گیت‌های دامنه + ساخت app-URL — همه‌جا `_enc(safe='')`)، `scoring.py`، `glossary.py` (گسترش قطعات EN↔FA از Book1.csv)، `service.py` (کش‌های TTL، قفل embed، allowed_cars در کلید کش)، `diag_build.py`/`diag.py` (ساخت/پرس‌وجوی sidecar)، `feedback.py` (امتیاز/pin/کلیک)، `evalmetrics.py`/`evalreport.py` (ابزار ارزیابی آفلاین).

## دستورات مدیریتی (`api/management/commands/`)

| دستور | هدف |
|---|---|
| `audit_vehicles [--fix] [--json]` | ممیزی کیفیت داده (fix = اصلاح + قرنطینه) |
| `sync_car_catalog [--dry-run]` | ثبت پایگاه‌های انبار جدید به‌عنوان ردیف کاتالوگ |
| `build_rag [--add]` | ساخت/گسترش ایندکس RAG (`--add` = فقط خودروهای جاافتاده؛ اگر نباشد بی‌اثر) |
| `build_diag` | ساخت sidecarهای عیب‌یابی هر خودرو |
| `optimize_index` | نگهداری ایندکس (FTS/vacuum) |
| `eval_rag` | ابزار ارزیابی بازیابی آفلاین |
| `check_alerts` | مرور هشدار + نگهداشت داده (timer سیستمی، ۵ دقیقه) |
| `process_outbox [--limit N]` | ارسال اعلان‌های سررسیدشدهٔ صندوق خروجی (پیامک/ایمیل) با تلاش مجدد؛ تا وقتی `KG_NOTIFY_*` برابر `off` است بی‌اثر. واحد و timer (هر دقیقه) در `ops/outbox/` هستند؛ نصب و فعال‌بودن روی میزبان **[U]** است |
| `purge_support_chat [--apply]` | threadهای پشتیبانی فراتر از دوره‌های نگهداشت پیشنهادی را گزارش می‌دهد. تا `KG_SUPPORT_RETENTION_ENABLED=1` و `--apply` نباشد چیزی حذف نمی‌کند (سیاستی هنوز تأیید نشده) |
| `pipeline_tick` | یک گذر watchdog/زمان‌بند/خلبان خودکار pipeline (timer، ۵ دقیقه) |
| `run_pipeline --job <id>` | ورودی worker مربوط به pipeline (spawn می‌شود؛ دستی اجرا نمی‌شود) |
| `realtime_tick` | آشکارساز تغییر ← رویدادها (kgkg-detect.timer، ۳۰ ثانیه) |
| `backfill_team` | یک‌بار: کاربر نقش بالا را در هر شرکت به مدیر ارتقا داد (تاریخی، از مدل مبتنی بر رتبه) |

## تست‌ها

در `origin/work` نسخهٔ `07f3ab5` تعداد ۱۱۰ ماژول تست زیر `KG_backend/` هست (`api/tests.py`، `api/test_*.py`، `api/rag/test_*.py`، `api/support_chat/test_*.py`، `api/notifications/test_*.py`)؛ نقشهٔ کامل، دستورات، کف پوشش و رفتار CI در [32-testing-and-qa.md](32-testing-and-qa.md) است. (این بخش زمانی «حدود ۱۹۳ تست سبز در ۲۰۲۶‑۰۷‑۱۴» نقل می‌کرد؛ آن عدد تاریخی است.) اجرای سریع:

<div dir="ltr">

```bash
cd /opt/KGKG/KG_backend
set -a; . ./.env.prod; set +a           # needs DJANGO_SECRET_KEY
KG_RL_DISABLE=1 .venv/bin/python manage.py test api
```

</div>

flake شناخته‌شده: یک تست محدودیت نرخ به ترتیب تست حساس است (سطل مشترک درون‌فرایندی)؛ `TeamManagementTests.setUp` به همین دلیل `ratelimit._HITS` را پاک می‌کند — کلاس‌های تست جدیدی که نقاط پایانی محدودشده را صدا می‌زنند باید همین کار را بکنند.

## ۴٫x ماژول‌ها و دستوراتی که پس از نوشتن این مرجع افزوده شدند (۲۰۲۶‑۱۱‑۰۴)

یک خط برای هرکدام، از docstring ماژول‌ها و دستورات؛ کد مرجع معتبر است. فهرست کامل و تولیدشدهٔ هر ماژول، مدل، دستور و متغیر env در `docs/generated/inventory.md` است.

### ماژول‌ها (`KG_backend/api/`)

| ماژول | نقش |
|---|---|
| `cardb_pg.py` | یک خودرو را از schema مخصوص خودش در PostgreSQL از طریق اتصال سازگار با sqlite3 سرو می‌کند؛ ← [23](../23-data-layer.md) |
| `assist_lookup.py` | جست‌وجوهای ساختاریافته در کنار RAG: شمارهٔ قطعه (کاتالوگ قطعات) و «کدام ابزار مخصوص برای کار X» از جدول‌ها پاسخ داده می‌شود، نه از متن |
| `contentguard.py` | سقف ساعتی خواندن صفحه و رسانه برای هر کاربر برای جلوگیری از کپی انبوه؛ آستانه‌ها `KG_CG_PAGE_WARN/BLOCK`، `KG_CG_MEDIA_WARN/BLOCK`؛ ← [26](../26-auth-and-sessions.md) |
| `shield.py` | بارهای سند رمزگذاری‌شده و درخواست‌های امضاشدهٔ یک‌بارمصرف (`KG_SHIELD=1` + `KG_SHIELD_SECRET`)؛ ← [26](../26-auth-and-sessions.md) |
| `vncauth.py` | تیکت کوکی مخصوص ادمین که صفحهٔ مرورگر TIS را در `/kg-vnc/` می‌بندد (`auth_request` در nginx) |
| `nulguard.py` | متن درخواستی که NUL دارد را با ۴۰۰ رد می‌کند، چون متن PostgreSQL نمی‌تواند U+0000 را ذخیره کند (SQLite می‌توانست) |
| `safepath.py` | `safe_join` (تنها راه تبدیل نام‌های برآمده از درخواست به مسیر) و `split_year_suffix`؛ دسته‌های path-injection/ReDoS در CodeQL را می‌بندد |
| `frm.py` | مجموعه‌داده‌های دفترچه flat-rate (`Database_warehouse/_frm/<slug>.json`): جدول ساعت کار برای هر خانوادهٔ مدل |
| `labortimes.py`، `sst.py` | خروجی CSV برای هر خودرو از جدول‌های Labor Times و Special Service Tools |
| `orggraph.py` | مجوزهای تعیین‌شده توسط ریشه برای یک صندلی را به primitiveهای اعمال کامپایل می‌کند؛ بازتخصیص اضطراری ریشه؛ کاشت از نقش‌های سازمانی legacy |
| `partsouq_crawler.py`، `partsouq_build.py` | شروع/توقف/وضعیت ادمین برای خزش VIN در Partsouq (Chrome سرور را با خزندهٔ TIS روی CDP ‏127.0.0.1:9222 به اشتراک می‌گذارد) و ساخت پایگاه قطعات از یک خزش تمام‌شده |
| `support_metrics.py` | سنجه‌های میزکار پشتیبانی؛ هر عدد تعریفی در `audit-evidence/16-improvement-programme/METRIC_DEFINITIONS.md` و یک تست دارد |
| `support_chat/`، `notifications/` | ← [22](../22-support-chat.md) |

### دستورات مدیریتی (`manage.py <name>`)

| دستور | نقش |
|---|---|
| `backfill_last_login` | پرکردن `PortalUser.last_login_at` تهی از جدیدترین ردیف فعالیت `login` (`--dry-run` فقط می‌شمارد) |
| `check_coverage` | ممیزی پوشش موتور عیب‌یابی و بازیابی برای هر خودرو در برابر baseline ذخیره‌شده و هشدار هنگام رگرسیون؛ توسط `kgkg-coverage.timer` اجرا می‌شود (پوشش تست نیست) |
| `check_secret_age` | هشدار وقتی رازهای سرور از موعد چرخش گذشته‌اند (`--max-age-days` با پیش‌فرض ۹۰)؛ هرگز خودش نمی‌چرخاند |
| `copy_sqlite_to_postgres` | کپی یک‌باره داده پرتال از فایل قدیمی SQLite به PostgreSQL (`--verify-only`) |
| `seed_kb_faq` | انتشار مقالات FAQ میزکار پشتیبانی در پایگاه دانش (`--dry-run`) |
| `seed_qa_fixtures` | حساب‌های قطعی برای E2E/بار/DAST؛ فقط درون پشتهٔ ایزولهٔ QA اجرا می‌شود |
| `sync_org_reports` | پرکردن `PortalUser.reports_to` از روی بوم گراف سازمانی |
| `build_reranker_trainset`، `train_kg_reranker`، `train_query_adapter` | آموزش آفلاین cross-encoder سازگار با دامنه و adapter سمت پرسش در bge-m3 (سند ۱۷)؛ به torch و مدل نیاز دارند |

</div>
