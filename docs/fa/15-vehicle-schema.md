<!-- i18n-source: 15-vehicle-schema.md sha256:70c8a0158a76 -->
<div dir="rtl" lang="fa">

# ۱۵ — داده ساختاریافتهٔ خودرو (schema.org) و گسترش pipeline ورود محتوا

> ساخته‌شده در ۲۰۲۶‑۰۷‑۱۸. دو سیستم مرتبط را که با هم افزوده شدند پوشش می‌دهد: نیمهٔ جلویی **parse** در pipeline پردازش (inbox ZIP + خزش‌های TIS؛ دانلودکنندهٔ منبع اصلی و مرحلهٔ `download` آن در ۲۰۲۶‑۰۹‑۱۹ حذف شدند)، و لایهٔ **مشخصات خودروی schema.org** که روی داده ورودی ساخته شده.

## ۱. pipeline کامل (۶ مرحله)

هر ProcessingJob اکنون اجرا می‌کند (مراحل خالی خودکار رد می‌شوند، پس jobی که ZIP/خزش TIS در صف ندارد دقیقاً مثل pipeline قدیمی ۴ مرحله‌ای رفتار می‌کند):

| # | مرحله | چه می‌کند | کد |
|---|---|---|---|
| ۱ | `parse` | `ZipPackage`های در انتظار را اجرا می‌کند — پوشهٔ خودروی TIS از `tis_parser.process_vehicle`، یک ZIP از `htmlparser_logical.process_single_zip` ← `Database_warehouse/<stem>.db` + `static_warehouse/<stem>/` + upsert کاتالوگ؛ پس از آن درخت استخراج‌شده + پایگاه واسط خزش را حذف می‌کند (ZIPها می‌مانند)؛ محافظ دیسک زیر ۲۰ گیگابایت آزاد متوقف می‌کند (`KG_PIPELINE_MIN_FREE_GB`) | `stage_parse`، `ingest.parse_zip_package` |
| ۲ | `catalog` | `sync_car_catalog` (پشتوانهٔ اعتبارسنجی؛ parse از قبل upsert کرده) | بدون تغییر |
| ۳ | `schema` | ردیف‌های `VehicleSpec` را برای خودروهای کهنه/جاافتاده می‌سازد/تازه می‌کند | `stage_schema`، `api/vehicleschema.py` |
| ۴ | `rag` | ingest + embed + graph | بدون تغییر |
| ۵ | `diag` | sidecarهای عیب‌یابی | بدون تغییر |
| ۶ | `audit` | گزارش کیفیت داده | بدون تغییر |

`pending_work()` مقادیر `need_download`، `need_parse`، `need_schema` را گرفت؛ همه به `has_work` می‌روند، پس `pipeline_tick` برای دانلود/ZIPهای در صف هم job را خودکار شروع می‌کند. چون download/parse در میانهٔ job برای مراحل بعدی کار می‌سازند، worker پس از آن‌ها `replan_pending_stages()` را صدا می‌زند — مرحله‌ای که هنگام شروع job با ۰ آیتم برنامه‌ریزی شده بود دوباره برنامه‌ریزی می‌شود نه اینکه به‌اشتباه خودکار رد شود.

## ۲. inbox ZIP و صف

* ریشه‌های inbox: `/root/downloads` + `/root/Downloads` (env با نام `KG_ZIP_INBOX`، جداشده با دونقطه؛ ریشهٔ اول دانلودهای جدید را می‌گیرد).
* `manage.py scan_zips [--normalize] [--dry-run]` — `*.zip` را کشف می‌کند، `"<year> <brand> <model>/"` را از پوشهٔ سطح‌بالای داخلی هر ZIP می‌خواند (بدون نیاز به استخراج)، فایل‌های legacy فقط-مدل را به `KGTV <year> <brand> <model>.zip` تغییر نام می‌دهد، ردیف‌های `ZipPackage` را ثبت می‌کند.
* **محافظ تکرار**: ZIPی که stem هدفش از قبل `.db` انبار دارد، یا stemش قبلاً توسط بستهٔ دیگری در صف/انجام‌شده پوشش داده شده، `skipped_duplicate` می‌شود — دانلود دوبارهٔ خودروهای واردشده هرگز نمی‌تواند خودرویی را بازنویسی یا تکرار کند. ادمین می‌تواند `skip_zip` / `requeue_zip` کند.
* دفتر `processing_status` خود parser (درون db.sqlite3) رکورد داخلی parser می‌ماند؛ `ZipPackage` صف رو به pipeline است.

## ۳. stemهای چندسال

stem انبار == `car_name` کاتالوگ == `car_stem` در RAG (ناوردایی، سند ۰۳ بخش ۳٫۵). ناوگان ۲۰۲۵ نام ساده می‌گیرد؛ **هر سال مدل دیگر پسوند `" (YYYY)"`** می‌گیرد: `Corolla Cross LE, FWD (2023)`. در `htmlparser_logical.warehouse_stem(car_name, year)` پیاده شده (DEFAULT_STEM_YEAR=2025) و این‌ها آن را می‌فهمند:

* `api/rag/config.py` — `split_stem_year()`، `display_name()` (پسوند را برای برچسب UI حذف می‌کند؛ سال در ستون کاتالوگ است)، `car_meta()` آگاه از پسوند.
* `api/dataquality.py` — سال مدل معقول (۱۹۸۰ تا ۲۱۰۰) در پسوند `"(N)"` شمارندهٔ کپی **نیست** (پس خودروهای ۲۰۲۳ هرگز آپلود تکراری خودروی ۲۰۲۵ علامت نمی‌خورند).
* فهرست‌های عمومی `display_name` را کنار `car_name` برمی‌گردانند؛ URLها stem کامل را نگه می‌دارند (`/Toyota/2023/Corolla%20Cross%20LE%2C%20FWD%20(2023)/`).

همچنین: `dataquality.is_electrified/is_pure_ev` اکنون پیشرانه‌های کل مدل را می‌شناسند (Prius/Sienna/Venza/Crown/Mirai/RAV4 Prime…؛ Mirai بدون احتراق شمرده می‌شود)، پس انتظارات بخش برای ناوگان گسترش‌یافته درست می‌ماند.

## ۴. VehicleSpec (schema.org/Car)

یک ردیف برای هر خودروی کاتالوگ: `data` (دیکشنری `Car` از schema.org، آمادهٔ JSON-LD)، `provenance` (`{field: {source: catalog|stem|manual|curated|derived, detail}}`)، `sections_used`، `builder_version`.

**سیاست سخت‌گیرانهٔ null-بگذار** — نبود کلید = نامعلوم، هرگز حدس نمی‌شود. لایه‌های پرشده:

* catalog/stem: نام، برند، سازنده، مدل، vehicleModelDate/modelDate، vehicleConfiguration (trim)، fuelType، driveWheelConfiguration، vehicleEngine (حجم موتور + کد موتور VIN)، vehicleTransmission («Standard Trans» ⇐ دستی).
* manual (پارس‌شده از دفترچه تعمیر خود خودرو — `Quick Lookups/Fluids`، با بازگشت به `Common Specs & Procedures`، به‌علاوهٔ `Tire Fitment`): ظرفیت/نوع سیالات به‌صورت PropertyValue در `additionalProperty`، مبرد، ردیف ATF ⇐ vehicleTransmission=Automatic، ردیف Fuel-Tank ⇐ fuelCapacity، اندازهٔ لاستیک.
* curated (`CURATED_MODEL_FACTS`، بازبینی‌شده با دست، دارای برچسب provenance): bodyType، numberOfDoors، fuelType کل مدل (Prius=هیبرید، Mirai=هیدروژن، Prime=PHEV…).
* **هرگز پر نمی‌شود** (منبعی در ناوگان نیست): enginePower، گشتاور اسمی، وزن، ابعاد، فاصلهٔ محور، تعداد صندلی، شتاب، آلایندگی، VIN.

ساخت: `manage.py build_vehicle_schema [--stems ...] [--force]` یا مرحلهٔ `schema` در pipeline (کهنگی = ردیف جاافتاده، `builder_version` قدیمی‌تر، یا پایگاه خودرو جدیدتر از `built_at`).

## ۵. کجا ظاهر می‌شود

* **API**: ‏`/​<brand>/<year>/<car>/?spec=1` (دروازه‌بندی‌شده با اعطا؛ data + jsonld + provenance)؛ فهرست‌های عمومی برند/سال `display_name` + `spec` دارند (`public_jsonld` فقط‌هویت — بدون داده سرویس برگرفته از دفترچه).
* **صفحات عمومی**: `[brand]/[year]/page.jsx` یک ItemList با نوع `application/ld+json` از مشخصات هویتی منتشر می‌کند.
* **چت‌بات**: `/api/assist/` برای خودروی pin‌شده `vehicle_specs` (بلوک متنی فشردهٔ حداکثر ۱۵ خطی) ضمیمه می‌کند؛ route چت آن را *درون* زمینهٔ پایه‌دارسازی پیش‌آیند می‌کند تا بازنویس بتواند به پرسش مشخصات پاسخ دهد و همچنان فقط‌زمینه بماند.
* **ادمین**: بخش «مشخصات خودروها» (`/api/admin/vehicle-specs/`) — پوشش ناوگان، شمارش هر فیلد، نمایشگر مشخصات + provenance هر خودرو. بخش pipeline فرم بررسی منبع («بررسی منبع» فهرست dry-run، «افزودن به صف دانلود»)، جدول صف ZIP و ردیف‌های درخواست دانلود را گرفت.

## ۶. افزوده‌های API ادمین (`/api/admin/pipeline/` با POST)

`tis_start` · `tis_stop` · `tis_chrome` (خزندهٔ TIS، ← `api/tis_crawler.py`) · `scan_zips {normalize?, dry_run?}` (inbox ZIP + ریشه‌های TIS) · `skip_zip/requeue_zip {zip_id}`. بار GET دارای `tis`، `zip_queue{counts,rows}` و فیلدهای صف در `pending`/`settings` است.

**خزش‌های TIS در صف (۲۰۲۶‑۰۹‑۱۹).** `scan_zips` ریشه‌های TIS را هم می‌پیماید (`KG_TIS_INBOX`، پیش‌فرض `/root/downloads/tis`، به‌علاوهٔ `downloads_tis/` خزندهٔ روی سرور) و هر پوشهٔ `<Model>_<Year>/` را که صفحه دارد به‌عنوان `ZipPackage` ثبت می‌کند که `path` آن همان پوشه است (`zip_name` برابر `TIS <year> Toyota <model>`). پوشه‌های بدون صفحه، یا در حال نوشتن توسط خزندهٔ در حال اجرا، کنار گذاشته می‌شوند. خزشی که جای دیگر ساخته شده همراه `_assets/` همسایه‌اش کپی می‌شود. `tis_parser.py` همان پایگاه `nodes` را می‌سازد (دسته ← انتشار ← درخت sidebar مربوط به TIS، به ترتیب TIS)، تصاویر را از طریق مخزن مشترک parser مربوط به ZIP منتشر می‌کند (شکل‌ها/PDFهای EWD پیشوند هش محتوا می‌گیرند — نام‌هایشان بین خودروها تکرار می‌شود) و پیوندهای متقابل را به `pages/<DocID>.html` بازنویسی می‌کند و `href` برگ‌ها را مطابق آن.

## ۶b. موازی‌سازی parse و کلید حداکثر توان

خزش HTML از **html5lib** استفاده می‌کند (Python خالص، محدود به GIL — lxml پرهیز شده چون `<li>`های بسته‌نشدهٔ دفترچه‌ها را غلط تودرتو می‌کند). thread pool نمی‌تواند بیش از یک هسته برای آن استفاده کند، پس مرحلهٔ parse **هر ZIP را در یک subprocess** با `ProcessPoolExecutor` و روش شروع **spawn** اجرا می‌کند (`api/parse_worker.py`؛ spawn نه fork چون worker چند‌threaded است). هر subprocess در `worker_init` جنگو را بالا می‌آورد، یک ZIP در صف را parse می‌کند، یک دیکشنری نتیجهٔ کوچک برمی‌گرداند. ایمن در برابر لغو/خرابی: `systemctl stop` کل cgroup را SIGTERM می‌کند؛ فرزندان می‌میرند و نقاط بازرسی افزایشی خزش parser هر ZIP را قابل ازسرگیری نگه می‌دارد، و هر ZIP که در حالت `parsing` مانده باشد در شروع اجرای بعد دوباره در صف می‌رود.

**کلید حداکثر توان** (`PipelineSettings.max_power`، migration 0014؛ کلید ادمین «حداکثر توان پردازش» در پنل pipeline):

| حالت | فرایندهای parse | thread‌های OMP در embed | اولویت (systemd) |
|------|----------------|-------------------|--------------------|
| عادی (پیش‌فرض) | `cores // 2` (۸ از ۱۶) | ۱۲ | Nice 15، IO idle، CPUWeight 25 |
| **حداکثر** | `cores - 1` (۱۵ از ۱۶) | `cores - 1` | Nice 0، IO best-effort، CPUWeight 100 |

`pipeline.power_plan(max_power)` بودجه را محاسبه و `launch_worker` اعمال می‌کند (env به نام‌های `KG_PARSE_WORKERS`/`OMP_NUM_THREADS` + ویژگی‌های Nice/IO/CPUWeight در systemd). env صریح `KG_PARSE_WORKERS` هنوز غلبه دارد. جابه‌جایی کلید هنگام اجرای یک job اقدام ادمین `apply_power` را صدا می‌زند که job فعال را cancel←resume می‌کند (قابل ازسرگیری، چیزی از دست نمی‌رود) تا بودجهٔ جدید فوراً اعمال شود. اندازه‌گیری‌شده: عادی ≈ ۱ هستهٔ مؤثر (سریالی قدیمی) ← حداکثر ≈ ۱۴ هسته (حدود ۹۵٪ بهره‌برداری جعبه، بار حدود ۱۳/۱۶)؛ سایت پاسخگو ماند (حدود ۳ میلی‌ثانیه) چون درخواست‌های وب کوچک‌اند و زمان‌بند آن‌ها را حتی در برابر parse با Nice 0 فوراً سرویس می‌دهد.

## ۷. تله‌ها

* دانلودکنندهٔ منبع اصلی دیگر همراه برنامه نیست (در ۲۰۲۶‑۰۹‑۱۹ از برنامه خارج شد)؛ ZIPها همچنان از inbox وارد می‌شوند.
* ردیف‌های ProcessingJob قدیمی پیش از مراحل جدید ساخته شده‌اند — `Runner.stage()` برای کلیدهای ناشناخته None برمی‌گرداند و `run_stage` بی‌اثر است، پس ازسرگیری job قدیمی هرگز خراب نمی‌شود.
* پاک‌سازی مرحلهٔ parse درخت استخراج‌شده **و** `.db` واسط خزش کنار ZIPها را حذف می‌کند — اجراهای دستی قدیمی حدود ۵۷ گیگابایت باقی‌مانده از این دست گذاشته بودند.
* مرحلهٔ schema عمداً **پیش از** rag اجرا می‌شود: مشخصات در چند دقیقه آماده‌اند در حالی که embedding روی backlog بزرگ می‌تواند روزها طول بکشد.

</div>
