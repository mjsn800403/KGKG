# خط لوله‌ی داده (Data Pipeline)

ابزار: `htmlparser_logical.py` (+ رابط گرافیکی `parser_gui.py`)

این مرحله، آرشیوهای HTML آفلاین دفترچه‌ها را به دیتابیس‌های قابل‌سرو تبدیل می‌کند.

## اجرا

```bash
python htmlparser_logical.py "path/to/KG_backend"
```

ورودی: پوشه‌ی بک‌اند (همان که `db.sqlite3` دارد). فایل‌های `LEMON *.zip` در
پوشه‌ی جاری پردازش می‌شوند.

## مراحل پردازش

طبق توضیح ابتدای فایل، اجرای کامل این کارها را انجام می‌دهد:

1. **استخراج** تمام فایل‌های `LEMON *.zip` در پوشه‌ی جاری (به‌صورت موازی).
2. **پارس** هر پوشه‌ی HTML استخراج‌شده به یک دیتابیس درختی (موازی).
3. **کپی** دیتابیس‌ها به `Database_warehouse/` (با حذف پیشوند/سال از نام).
4. **کپی** پوشه‌های تصاویر به `static_warehouse/` (با نام متناظر).
5. **به‌روزرسانی** `db.sqlite3` بک‌اند با اطلاعات خودرو (درج در `main_db`).

## منطق پارس

- **PARSER = `html5lib`** اجباری است؛ `html.parser`/`lxml` تگ‌های `<li>` بازِ
  دفترچه‌ها را اشتباه تو در تو می‌کنند.
- پارسر **breadcrumb-driven** و **link-crawled** است: از `index.html` شروع
  می‌کند، لینک‌ها را کرال می‌کند و ساختار درخت را از breadcrumbها استنتاج
  می‌کند.
- فایل‌ها بر اساس **basename** پیدا می‌شوند (layout-agnostic)، نه مسیر دقیق.
- محتوای صفحات برگ از `div.main` استخراج و در ستون `content` ذخیره می‌شود.
- `id` هر گره = `sha1(path)` و `parent_id` = `sha1(parent_path)`.

خروجی شِما در [data-model.md](data-model.md) توضیح داده شده است.

## کرال قابل‌ازسرگیری (Resumable Crawl)

- هر `CHECKPOINT_EVERY = 250` صفحه، وضعیت frontier (مجموعه‌ی visited و queue)
  به‌صورت atomic ذخیره می‌شود. در صورت قطع، حداکثر همین تعداد صفحه دوباره
  پردازش می‌شود.
- استثنای `CrawlPaused` خطا نیست؛ یعنی frontier checkpoint شده و اجرای بعدی از
  همان نقطه ادامه می‌دهد.
- `cancel_event` (از سمت GUI) باعث pause تمیز می‌شود؛ zipهای جدید بعد از Stop
  شروع نمی‌شوند و خودروی نیمه‌کاره در اجرای بعدی ادامه می‌یابد.

## دفترچه‌ی ثبت (Processing Ledger)

- کلاس `ProcessingLedger` وضعیت هر zip را در سطح بک‌اند ثبت می‌کند
  (`mark_start` / `mark_failed` / `is_completed`).
- zipهای کاملاً تمام‌شده در اجرای مجدد skip می‌شوند؛ بقیه از سر گرفته می‌شوند.
- نوشتن در ledger با `ledger_lock` بین threadها سریال می‌شود.

## اجرای موازی

پردازش zipها با `ThreadPoolExecutor` موازی انجام می‌شود (تعداد worker قابل
تنظیم؛ در GUI فیلد `workers`).

---

## رابط گرافیکی پارسر (`parser_gui.py`)

رابط دسکتاپ مبتنی بر **Tkinter** برای کسانی که نمی‌خواهند با ترمینال کار کنند:

- انتخاب «پوشه‌ی بک‌اند» (دارای `db.sqlite3`) و «پوشه‌ی zipها».
- دکمه‌ی Start/Stop و نمایش زنده‌ی پیشرفت (با پشتیبانی pause/resume).
- آخرین مسیرها در `parser_gui_config.json` کنار برنامه ذخیره می‌شوند.

اجرا از سورس:
```bash
python parser_gui.py
```
ساخت فایل اجرایی: طبق `ParserGUI.spec` (PyInstaller).

### `parser_gui_config.json`
```json
{
  "backend": ".../KG_backend",
  "zips": ".../Cars_database",
  "workers": ""
}
```
