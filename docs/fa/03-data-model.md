<!-- i18n-source: 03-data-model.md sha256:8baf274807dc -->
<div dir="rtl" lang="fa">

# ۰۳ — مدل داده

لایه‌های ذخیره‌سازی (نقشهٔ معتبر: [۲۳ — لایهٔ داده](../23-data-layer.md)):

- **پایگاه رابطه‌ای اصلی**: پایگاه PostgreSQL 16 با نام `kgkg` در تولید (ORM جنگو، `KG_DB_ENGINE=postgres`)؛ SQLite با نام `db.sqlite3` پیش‌فرض توسعه و فایل منجمد تولید قبلی است؛
- **مخزن‌های محتوای هر خودرو**: محتوای دفترچهٔ خودروهای بارگذاری‌شده در schemaهای PostgreSQL پایگاه `kgkg_vec` (رجیستری `public.car_dbs`)، خودروهای فقط‌قطعات به‌صورت فایل‌های SQLite فقط‌خواندنی زیر `_parts/`؛
- **لایهٔ مشتق RAG**: `_rag/index.rag.db` (SQLite + `sqlite-vec`)، قابل بازسازی از مخزن‌های محتوا؛ ممکن است در `kgkg_vec` (pgvector) آینه شود.

محتوای خودرو در اصل یک فایل SQLite تغییرناپذیر برای هر خودرو بود (ADR-0001)؛ بخش‌های زیر که `db_address` یا «پایگاه انبار» می‌گویند به همان نام فایل اشاره دارند که هنوز کلید یافتن schema آن خودرو در PostgreSQL است.

## ۳٫۱ پایگاه اصلی — مدل‌های Django (`api/models.py`)

### کاتالوگ و فروش

**`Car`** (جدول `main_db` — نام قدیمی؛ بی‌دلیل تغییرش ندهید)
`brand_name`، `car_name`، `year`، `db_address` (مسیر نسبی پایگاه انبار).
یک ردیف برای هر خودروی قابل سرو. `car_name` همزمان `car_stem` در RAG است؛ برابری stem/name در مجوزدهی محتوا استفاده می‌شود (`views._user_allowed_stems`).

**`PurchaseRequest`** — فرم سرنخ عمومی از `/purchase`: خودرو (برند/مدل/سال)، `documents` درخواستی (فهرست JSON از شناسهٔ بسته‌ها)، تماس شخص حقوقی (شرکت، تلفن ثابت، موبایل، reg_no)، اندازه (`employees_count`، `seats_count`، ردیف‌های JSON با نام `seat_plan` به شکل `{role, department, count, note}`)، افزونه‌ها (`wants_demo`، `wants_ai_assistant`)، `status` گردش‌کار (new/reviewing/approved/rejected) + `handled`.

### کنترل دسترسی (معنا در سند ۰۶)

**`Company`** — شخص حقوقی: `name` (یکتا)، `department_label` (برچسب نقش‌ها را سفارشی می‌کند)، فیلدهای تماس، `seats_count`، `is_demo`، `ai_assistant_enabled` (دروازهٔ AI در سطح شرکت)، `active`، `note`.

**`CompanyCarAccess`** — آنچه شرکت خریده: `(company, car)` یکتا + `documents` (زیرمجموعهٔ JSON از شناسهٔ بسته‌ها؛ **فهرست خالی = همهٔ لایه‌ها**).

**`OrgRole`**: *حذف شد* (migration با نام `0016_remove_portaluser_org_role_delete_orgrole`). موقعیت تعریف‌شده توسط شرکت با `rank` و `manage_scope` بود. جانشین‌ها: `CompanyRole` (*برچسب* نقش قابل انتخاب برای هر شرکت، یکتا `(company, value)`، چهار نقش داخلی در اولین استفاده کاشته می‌شود) و مدل‌های گراف سازمانی `OrgGraph` / `OrgNode` / `NodePermission` / `NodeInvite` (بخش ۳٫۶، [06](../06-permissions-rbac.md) بخش ۶٫۶).

**`PortalUser`** — صندلی شرکت: `username` (یکتا)، `email` (یکتا، شناسهٔ ورود جایگزین)، `phone`، `personnel_code`، `password_hash`، `display_name`، فیلد `role` (برچسب)، `reports_to` خودارجاعی (آینهٔ یال والد بوم، ← بخش ۶٫۶)، پرچم‌های قابلیت (`can_manage_team`، `can_view_analytics`، `ai_assistant_enabled`)، `otp_enabled`، ترجیحات اعلان (`notify_manual_update`، `notify_new_device`)، `onboarding_dismissed_at`، `browse_mode`، `active`، `locked`، چرخهٔ دعوت (`invite_status` با مقادیر active/invited/disabled، `password_set`، `invited_by`)، `access_expires_at`، `last_login_at`. (کلید خارجی `org_role` در طراحی اولیه با `OrgRole` حذف شد.) فهرست کامل فیلدها: [generated/schema.md](../generated/schema.md).

**`UserCarAccess`** — اعطای سطح کاربر: `(user, car)` یکتا، `documents` (زیرمجموعهٔ دامنهٔ شرکت)، `admin_granted` (از محدودیت‌های خرید عبور می‌کند؛ از تغییر دامنهٔ شرکت جان سالم به در می‌برد).

### توکن‌های احراز هویت

**`AuthToken`** — توکن bearer مات ۶۴ هگزا برای هر ورود پرتال (نشست مبتنی بر پایگاه داده؛ چند توکن برای هر کاربر مجاز است). **`AdminAuthToken`** — همان برای ادمین‌های پلتفرم.
**`PlatformAdmin`** — ابرکاربر فروشنده (فضای نام جدا از کاربران پرتال).
**`InviteToken`** — یک‌بارمصرف، TTL برابر ۷ روز، هش sha256 در حالت ذخیره؛ `issue()` توکن خام را دقیقاً یک‌بار برمی‌گرداند (در URL دعوت جاسازی می‌شود)؛ صدور جدید دعوت‌های استفاده‌نشدهٔ قبلی را باطل می‌کند.

### تله‌متری و تحلیل

**`ActivityLog`** — یک ردیف برای هر اقدام کاربر: `action` (login/view_car/view_node/search/assist…)، `detail`، `category` (حوزهٔ فنی استاندارد)، کلید خارجی `car`، `node_title`، `app_url` (لینک عمیق برای پیشنهادها). ایندکس‌ها: (user, created_at)، (category, created_at)، (created_at).

**`TrafficStat`** — تجمیع ساعتی هر گروه نقطهٔ پایانی (درخواست‌ها، 4xx، 5xx، تأخیر کل/بیشینه)، نوشته‌شده توسط flush دسته‌ای متریک. **`VisitorSeen`** — (روز، هش نمک‌دار IP) برای بازدیدکنندگان یکتای روزانهٔ دقیق؛ پس از حدود ۹۰ روز حذف می‌شود.

### عملیات

**`DataQualityRun`** — یک مرور ممیزی: status، `summary` (شمارنده‌های تجمیعی)، `vehicles` (جزئیات هر خودرو)، `actions` (اصلاحات انجام‌شده/توصیه‌شده).

**`ProcessingJob`** — یک اجرای pipeline: ماشین وضعیت (pending/scheduled/running/paused/stalled/done/failed/canceled)، `trigger` (manual/auto/schedule)، هویت worker (`pid`، `unit_name`)، `attempts`، `stages` (وضعیت JSON هر مرحله)، `progress` (JSON: overall_pct/stage/eta_s/rate)، `log_tail`، heartbeat. حالت‌های قابل‌ازسرگیری: paused/stalled/failed. فعال (اشغال‌کنندهٔ slot): pending/running.

**`PipelineSettings`** — singleton (id=1): `auto_enabled`، `load_threshold` (دروازهٔ load1/cores برای شروع خودکار)، `auto_resume`، توان عملیاتی مشاهده‌شده (`embed_rate_pps`، `diag_secs_per_car`) برای تخمین صادقانهٔ ETA.

**`SystemAlert`** — هشدارهای عملیاتی بدون تکرار با کلید شرط (`disk_high`، `error_rate:assist`…)، شدت info/warning/critical، رفع خودکار، اولین/آخرین مشاهده.

### بی‌درنگ و درخواست‌ها

**`Event`** — لاگ رویداد فقط‌افزودنی؛ ستون فقرات SSE. `type` (نقطه‌دار، مثلاً `request.updated`)، `audience` (admin/company/user/all)، `company_id`/`user_id` به‌صورت عدد ساده (رویدادها از ردیف‌هایی که توصیف می‌کنند بیشتر عمر می‌کنند)، `payload` به‌صورت JSON. `id` مکان‌نمای ازسرگیری است. تا حدود ۲۰ هزار ردیف برش می‌خورد (سرشکن‌شده).

**`SystemState`** — مخزن کوچک کلید←JSON برای singletonهای مشترک بین workerها (مثلاً اثر انگشت کار در انتظار که آشکارساز تغییر با آن مقایسه می‌کند).

**`CompanyRequest`** — درخواست ثبت‌شده توسط مدیر برای فروشنده: `kind` (vehicle_access / seats / ai_assistant / documents / support / other)، `subject`، `body`، `payload` ساختاریافته، `status` (pending/in_progress/completed/rejected)، `priority`، `admin_note`، `handled_by`. هر گذار رویداد برای هر دو مخاطب شرکت و ادمین منتشر می‌کند.

## ۳٫۲ تاریخچهٔ migrationها

| # | چه چیزی اضافه کرد |
|---|---|
| 0001–0004 | کاتالوگ خودرو، PurchaseRequest، Company، اندازهٔ کارکنان/صندلی |
| 0005 | بسته‌های RBAC + PlatformAdmin/AdminAuthToken |
| 0006 | `seat_plan` روی PurchaseRequest |
| 0007 | مدیریت تیم: ایمیل/تلفن/قابلیت‌ها/دعوت‌های PortalUser، InviteToken، دستهٔ/خودرو/node_title در ActivityLog |
| 0008 | DataQualityRun، SystemAlert، TrafficStat، VisitorSeen |
| 0009 | PipelineSettings، ProcessingJob |
| 0010 | OrgRole (+ کاشت) |
| 0011 | CompanyRequest، Event، SystemState |
| 0012 | ActivityLog.app_url |
| 0013-0014 | صف بستهٔ دانلود/ZIP، `max_power` در pipeline |
| 0015-0016 | مدل‌های گراف سازمانی (`OrgGraph`، `OrgNode`، `NodePermission`، `NodeInvite`)؛ `OrgRole` و `PortalUser.org_role` حذف شدند |
| 0017-0018 | هش‌شدن توکن‌های نشست در حالت ذخیره؛ `PortalUser.browse_mode` |
| 0019-0022، 0025-0028 | عامل دوم پیامکی (`OtpChallenge`، `OtpEvent`، purpose، OTP ادمین)، `otp_enabled`، ترجیحات اعلان، `RetiredDevice` |
| 0023-0024 | `CompanyRole`؛ `Company.plan` |
| 0029-0033 | `ChatLog` (+ مصرف، رفتار)، `AuditLog`، `SearchLog` |
| 0034-0039 | `FeatureFlag`؛ رشتهٔ میزکار/SLA/CSAT؛ پایگاه دانش؛ رد onboarding؛ ایندکس فعالیت؛ موضوع/خودرو/خوانده‌شدن میزکار |
| 0040 | `NotificationOutbox` |
| 0041 | هستهٔ چت پشتیبانی (`SupportThread`، `SupportMessage`، `SupportRating`، `SupportPresence`) |

فهرست بالا از نام فایل‌های migration خوانده شده است (۴۱ فایل در `origin/work` نسخهٔ `07f3ab5`)؛ شرح هر مورد از نام و docstring مدل‌ها استنباط شده، نه از خواندن تک‌تک migrationها **[C، استنباطی]**.

## ۳٫۳ پایگاه انبار هر خودرو (`Database_warehouse/<car_stem>.db`)

توسط `htmlparser_logical.py` تولید و توسط کد سرو فقط‌خواندنی باز می‌شود. شمای آن:

<div dir="ltr">

```sql
CREATE TABLE nodes (
  id          TEXT PRIMARY KEY,   -- sha1(path)
  parent_id   TEXT,               -- sha1(parent path); NULL at root
  path        TEXT NOT NULL,      -- absolute breadcrumb logical path
                                  -- NOTE: literal '/' inside a TITLE is encoded as U+2044 (⁄)
  title       TEXT NOT NULL,
  node_type   TEXT,               -- 'root' | 'folder' | 'leaf'
  file_type   TEXT,               -- 'root_path' | 'intermediate_path' | 'end_path'
  href        TEXT,               -- original link target, if any
  source_file TEXT,               -- html file this row was parsed from
  sort_order  INTEGER DEFAULT 0,
  depth       INTEGER DEFAULT 0,
  root_order  INTEGER,            -- ordering among root nodes
  content     TEXT,               -- raw div.main inner HTML for end_path rows
  updated_at  TEXT
);
CREATE TABLE crawl_state (k TEXT PRIMARY KEY, v TEXT);  -- 'snapshot' | 'status' JSON
```

</div>

نکات کلیدی:
- بخش‌های دفترچه زیر ریشهٔ عمق ۰ با نام **"Repair and Diagnosis"** هستند؛ عنوان‌های عمق ۲ حوزه‌های فنی‌اند که به دسته‌های استاندارد نگاشت می‌شوند (`access.CONTENT_CATEGORIES`).
- HTML محتوا تصاویر را به‌صورت نسبی `images/...` یا `/api/Image/SVGImage/...` ارجاع می‌دهد؛ `views.rewrite_image_urls` آن‌ها را به `/kg-api/media/<car>/…` بازنویسی می‌کند.
- **تله‌ی U+2044:** ستون `path` نویسهٔ `/` درون عنوان‌ها را به `⁄` کد می‌کند. هر چیزی که مسیرها را بین سیستم‌ها مقایسه می‌کند باید آن را نرمال کند (کد کیفیت داده و RAG این کار را می‌کنند).
- خانواده‌های trim اغلب دفترچه‌های بایت‌به‌بایت یکسان دارند (مثلاً 4Runner TRD Pro ≡ Trailhunter) — مشروع است و در لایهٔ blob در RAG به‌رایگان حذف تکرار می‌شود.

## ۳٫۴ ایندکس RAG (`Database_warehouse/_rag/index.rag.db`)

آدرس‌دهی‌شده بر اساس محتوا و بدون تکرار (← docstring در `api/rag/config.py`):

| جدول | هدف |
|---|---|
| `blobs` | یک ردیف برای هر متن صفحهٔ پاک‌شدهٔ یکتا (کلید sha)؛ حذف تکرار در کل ناوگان (حدود ۷۲٪ برگ‌ها نسخهٔ دقیقاً تکراری‌اند) |
| `occurrences` | هر (car_stem، title_path، year، فرادادهٔ app-url) که یک blob در آن ظاهر می‌شود — *منبع حقیقت خودروی قابل سرو*؛ `occurrences.car_stem == Car.car_name` |
| `chunks` / `vec_blobs*` | ذخیره‌سازی embedding با sqlite-vec و int8 (bge-m3، ۱۰۲۴ بعد)؛ `vec_blobs_rowids` جدول قابل شمارش است (افزونهٔ vec0 روی اتصال‌های ساده بارگذاری نمی‌شود — rowidها را بشمارید، نه `vec_blobs` را) |
| `blobs_fts*` | ایندکس واژگانی FTS5 (بازیابی ترکیبی) |
| `edges` | گراف رابطه در سطح blob: `semantic` (kNN)، `crosslink` (hrefهای خود دفترچه)، `labor_time` (رویه ↔ صفحهٔ زمان کار) |
| `cars`، `meta` | عکس فوری رجیستری خودرو + فرادادهٔ ساخت (`graph_synced_vectors` تحویل embed←graph را برای ازسرگیری علامت می‌زند) |

sidecarهای diag: `_rag/diag/<car_stem>.diag.db` — زیردرخت‌های DTC، جدول‌های علامت، ردیف‌های زمان کار، URLهای از‌پیش‌ساخته. بازخورد: `_rag/feedback.db` — امتیازهای 👍/👎، pinهای کارشناسی، لاگ کلیک.

**قواعد بازسازی:** هر چیز زیر `_rag/` دورریختنی است. `build_rag --add` فقط *خودروهای جاافتاده* را وارد می‌کند — ازسرگیری ایندکس نیمه‌embed یعنی فراخوانی مستقیم `embed.embed_index` و سپس `store.drop_build_vec` **پیش از** `graph.build_all` (جدول float ناقص کهنه بی‌صدا یال‌ها را از بین می‌برد). pipeline این را درست رمز می‌کند؛ دستی تکرارش نکنید.

## ۳٫۵ ناوردایی‌های داده که ارزش حفاظت دارند

۱. `Car.car_name` ⇔ نام فایل انبار بدون پسوند ⇔ `occurrences.car_stem`. تغییر نام هر ضلع مجوز محتوا و پیوندهای دستیار را می‌شکند.
۲. `UserCarAccess.documents ⊆ CompanyCarAccess.documents` مگر `admin_granted`. با `access.apply_user_access` / `apply_managed_access` اعمال می‌شود — هرگز اعطاها را دور این‌ها ننویسید.
۳. ساختار سازمانی: حداکثر یک صندلی ریشه در هر گراف سازمانی (قید پایگاه داده)؛ هر صندلی حداکثر یک متصدی دارد؛ `reports_to` آینهٔ یال والد بوم است. (ناوردایی قدیمی `rank(reports_to) < rank(user)` متعلق به مدل حذف‌شدهٔ `OrgRole` بود؛ `access.enforce_org_consistency` برای مسیر legacy می‌ماند.)
۴. `documents` خالی روی اعطای **شرکت** یعنی «همهٔ لایه‌ها»، اما اعطاهای کاربر همیشه صریح ذخیره می‌شوند (هرگز خالی) تا برداشتن ناخواستهٔ سقف رخ ندهد.
۵. ترتیب `Event.id` قرارداد ازسرگیری SSE است — هرگز idها را دوباره استفاده/شماره‌گذاری نکنید.

## ۳٫۶ مدل‌هایی که بالا شرح داده نشده‌اند (افزوده‌شده در ۲۰۲۶‑۱۱‑۰۴ از docstring مدل‌ها)

این مدل‌ها در `api/models.py` و زیربسته‌هایش وجود داشتند اما در این سند نام برده نشده بودند. یک خط برای هرکدام؛ مرجع معتبر docstring در کد است. `docs/generated/inventory.md` هر مدل را فهرست می‌کند و CI مدل جدیدی را که هیچ سند مرجعی نام نبرده علامت می‌زند. migrationها: ۴۱ مورد روی `work` (آخرین `0041_support_chat_core`).

| مدل | هدف | سند مرتبط |
|---|---|---|
| `CompanyRole` | برچسب نقش سازمانی هر شرکت برای ویرایشگر کاربر ادمین؛ چهار نقش داخلی در اولین استفاده کاشته می‌شود | 06 |
| `OrgGraph`، `OrgNode`، `NodePermission`، `NodeInvite` | بوم ساختار سازمانی شرکت: یک سند برای هر شرکت، صندلی‌ها (خالی یا با متصدی)، مجموعهٔ مجوز تعیین‌شده توسط ریشه برای هر صندلی که به primitiveهای اعمال کامپایل می‌شود (`api/orggraph.py`)، دعوت وابسته به صندلی خالی (فقط sha256 توکن) | 06 |
| `OtpChallenge`، `AdminOtpChallenge`، `OtpEvent` | عامل دوم پیامکی بین گذرواژه و صدور توکن (مبتنی بر پایگاه داده چون gunicorn چند worker دارد؛ TTL دو دقیقه، ۵ تلاش) و لاگ غلتان ۲۴ ساعتهٔ ارسال/شکست برای سقف‌ها | 26 |
| `KnownDevice`، `RetiredDevice` | کوکی دستگاه چرخان `kg_dev` (هش‌شده ذخیره می‌شود)؛ دستگاه ناشناخته پیامک دستگاه جدید را فعال می‌کند؛ استفادهٔ دوبارهٔ شناسهٔ بازنشسته یعنی کوکی کپی شده | 26 |
| `NotificationLog` | یک پیامک ارسال‌شده به کاربر و دفتر dedupe (یک پیامک به‌روزرسانی دفترچه برای هر کاربر برای هر خودرو در روز) | 24 |
| `SearchLog` | یک جست‌وجوی دفترچه، شناسهٔ ساده بدون کلید خارجی تا تاریخچهٔ شکاف محتوا از حساب‌ها بیشتر عمر کند (`api/insights.py`) | 10 |
| `FeatureFlag` | سوئیچ A/B یا عرضهٔ تدریجی با bucket ثابت هش، pinهای `force_on` / `force_off` (`api/flags.py`)؛ آزمایش `RAG_MQ_TRANSLATE` با migration 0034 کاشته شد | 08 |
| `TicketMessage`، `TicketRead` | نوبت‌های یک تیکت میزکار درخواست (جایگزین فیلد واحد `admin_note`) و موقعیت خواندن هر بیننده که همهٔ نشان‌های نخوانده از آن محاسبه می‌شود | 10 |
| `KnowledgeArticle`، `KnowledgeRevision` | پایگاه دانش: مقالهٔ پایدار با مالک مشخص؛ ویرایش‌های فقط‌افزودنی (چه کسی، چرا) | 13 |
| `SupportThread`، `SupportMessage`، `SupportRating`، `SupportPresence` | چت پشتیبانی انسانی | 22 |
| مدل‌های صندوق خروجی اعلان (`api/notifications/models.py`، migration 0040) | پیامک/ایمیل در صف با سوئیچ‌های `suppressed` / dry-run / live | 11، 22 |

ذخیره‌سازی محتوای خودرو در [۲۳ — لایهٔ داده](../23-data-layer.md) شرح داده شده، نه اینجا.

</div>
