<!-- i18n-source: 14-terminology.md sha256:0f8b08efc12c -->
<div dir="rtl" lang="fa">

# ۱۴ — مخزن اصطلاحات دوزبانه

تنها منبع حقیقت برای اصطلاحات انگلیسی↔فارسی: `Database_warehouse/_rag/terms.db` (ماژول `api/rag/terms.py`). دو مصنوع زمان اجرا از آن **تولید** می‌شوند و بدون ری‌استارت داغ بارگذاری می‌شوند:

| مصنوع | مصرف‌کننده | جهت | بارگذاری مجدد |
|---|---|---|---|
| `Book1.csv` (ریشهٔ پروژه) | گسترش پرسش در `api/rag/glossary.py` | فارسی←انگلیسی | بررسی mtime برای هر پرسش |
| `_rag/terms_en_fa.json` | route چت از طریق `src/lib/faTerms.js` (`TERMS_JSON_PATH`) | انگلیسی←فارسی برای نمایش | بررسی mtime، حداکثر ۶۰ ثانیه |

**هرگز مصنوعات را دستی ویرایش نکنید** — مخزن را تغییر دهید، سپس `manage.py build_terms --export`.

## ۱۴٫۱ شمای جدول

`terms(en, fa, en_norm, fa_norm, domain, source, confidence, status, use_query, use_display, notes, timestamps, UNIQUE(en_norm, fa_norm))`

- `fa` ZWNJ (نیم‌فاصلهٔ حرفه‌ای) را نگه می‌دارد؛ `fa_norm` از `glossary._norm_fa` استفاده می‌کند تا نرمال‌سازی سمت مخزن و سمت پرسش هرگز واگرا نشوند.
- رتبه‌های `source`: curated = بازبینی‌شده (۳) > imported (۲) > generated (۱)؛ upsert با رتبهٔ پایین‌تر هرگز ردیف رتبهٔ بالاتر را تنزل نمی‌دهد.
- یک اصطلاح EN می‌تواند چند ردیف FA نگه دارد (همه برای فارسی←انگلیسی ارزشمندند)؛ خروجی نمایش بهترین FA را به ازای هر EN برمی‌گزیند (رتبه ← اطمینان ← کوتاه‌ترین)، فقط نخستین جایگزین پس از «،» را درون‌خطی می‌کند و نگاشت‌های بیش‌ازحد اختصاصی EN تک‌کلمه ← FA سه‌کلمه یا بیشتر را حذف می‌کند.
- `gen_queue` صف کار ترجمهٔ ماشینی است (ماشین وضعیت: queued ← accepted / review / failed) — کاملاً قابل ازسرگیری.

## ۱۴٫۲ دستورات (`manage.py build_terms`)

- `--import-legacy` — راه‌اندازی **یک‌باره** از `Book1.csv` + `translation.sql` اصلی (روی مخزن غیرخالی بدون `--force` امتناع می‌کند؛ وارد کردن دوباره مصنوعات تولیدشده ردیف‌ها را «curated» برچسب می‌زد). پاک‌سازی: مصنوع سرستون حذف، فاصله‌های دوتایی فشرده، «ي/ك» عربی در حالت ذخیره یکسان، پیشوندهای نویز «standard part…» در EN و «قطعه استاندارد…» در FA حذف، واژگان خدمات curated کاشته می‌شود (فقط نمایش، `use_query=0`).
- `--export` — بازتولید هر دو مصنوع (جایگزینی اتمی + `Book1.csv.bak.YYYYMMDD` تاریخ‌دار).
- `--report` — گزارش واژگان/پوشش/هزینه (فقط‌خواندنی؛ `_rag/terms_report.txt` را می‌نویسد).
- `--mine --top N` — N اصطلاح EN ترجمه‌نشدهٔ پرتکرارتر از عنوان blobها، `comp_readable`، segmentهای breadcrumb و نام‌های diag را در `gen_queue` صف می‌کند.
- `--fa-gaps` — پرسش‌های فارسی کاربران (feedback.db) که `glossary.expand()` کم گسترش می‌دهد ← `_rag/fa_gaps_report.csv` (بذر curation / تولید آیندهٔ گونه‌های علامت).
- `--import-review file.csv` — ردیف‌های `en,fa[,domain]` بازبینی‌شده توسط انسان را وارد می‌کند (source=reviewed، confidence 1.0)، سپس برای انتشار `--export`.

## ۱۴٫۳ ترجمهٔ ماشینی (`manage.py translate_terms`)

مبتنی بر Metis، دارای دروازهٔ QA؛ **هرگز جفت راستی‌آزمایی‌نشده منتشر نمی‌کند**:

۱. ۲ نمونهٔ مستقل (نشست‌های جدای Metis)، با few-shot لنگرشده روی جفت‌های curated؛ JSON سخت‌گیرانه، تا ۲ بار پرسش مجدد.
۲. اختلاف ← نمونهٔ سوم، اکثریت ۲ از ۳ (توافق ۰٫۶۶) یا بازبینی انسانی.
۳. ترجمهٔ معکوس فارسی←انگلیسی، با شباهت کسینوسی bge-m3 نسبت به EN اصلی امتیازدهی می‌شود (`--backtrans-min`، پیش‌فرض ۰٫۸۲).
۴. گذراندن هر دو ← `terms` فعال (confidence = 0.5·توافق + 0.5·شباهت)؛ وگرنه `pending_review` + `_rag/terms_review.csv`.

پرچم‌ها: `--limit N`، `--budget M` (سقف سخت پیام Metis)، `--batch-size`، `--dry-run`، `--env-file` (اعتبارنامهٔ Metis از `kg_frontend/.env.production` خوانده می‌شود؛ تکرار نمی‌شود). عملیات: lockfile با pid (`_rag/locks/`)، بین دسته‌ها وقتی job پردازش فعال است کنار می‌کشد، لاگ کامل فراخوانی‌ها در `_rag/logs/translate_terms.log`. هزینه ≈ ۰٫۱۲ تا ۰٫۱۵ پیام برای هر اصطلاح.

روال: `--report` ← `--mine --top N` ← `translate_terms --dry-run` ← آزمایشی `--limit 300` ← بازبینی `terms_review.csv` (+ تأیید نمونه‌های پذیرفته‌شده) ← اجراهای مقیاس‌یافته زیر `--budget` ← هر اجرا با `build_terms --export` پایان می‌یابد.

## ۱۴٫۴ منشأ داده‌های legacy

`/opt/KGKG/translation.sql` یک export کهنه از `Book1.csv` بود (۱٬۶۲۵ جفتش زیرمجموعهٔ دقیق است) — پس از `--import-legacy` بازنشسته شد؛ فقط برای تاریخچه روی دیسک مانده است. `Book1.csv` دستی اصلی با نام `Book1.csv.bak.20260718` حفظ شده است.

</div>
