# نصب و اجرا

## پیش‌نیازها

- **Python 3.12** (برای بک‌اند و پارسر)
- **Node.js** (برای فرانت‌اند Next.js 16)
- مرورگر

## ۱) نصب پیش‌نیازها (یک‌بار)

اسکریپت آماده، محیط مجازی بک‌اند و پکیج‌های فرانت‌اند را نصب می‌کند:

```bash
# macOS / Linux
chmod +x check_prereqs.sh && ./check_prereqs.sh

# Windows
check_prereqs.bat
```

نصب دستی (در صورت نیاز):

```bash
# بک‌اند
cd KG_backend
python -m venv .venv
.venv/bin/pip install -r requirements.txt      # Django, corsheaders, bs4, html5lib
                                                # + numpy, torch, sentence-transformers,
                                                #   sqlite-vec (برای لایه‌ی RAG دستیار)

# فرانت‌اند
cd ../kg_frontend
npm install
```

## ۲) اجرای پروژه (بک‌اند + فرانت‌اند با هم)

```bash
# macOS / Linux  — هر دو سرور را بالا می‌آورد و مرورگر را روی :3000 باز می‌کند
./run_server.sh

# Windows
run_server.bat
```

این اسکریپت:
- بک‌اند Django را روی `127.0.0.1:8000` اجرا می‌کند (`manage.py runserver`).
- فرانت‌اند را روی `localhost:3000` (`npm run dev`).
- تا آماده شدن فرانت‌اند صبر کرده و سپس مرورگر را باز می‌کند.
- با `Ctrl+C` هر دو سرور بسته می‌شوند.

### اجرای جداگانه

```bash
# بک‌اند
cd KG_backend && .venv/bin/python manage.py runserver

# فرانت‌اند
cd kg_frontend && npm run dev
```

## ۳) متغیرهای محیطی فرانت‌اند

فایل `kg_frontend/.env.local` باید شامل اعتبارنامه‌ی دستیار Metis باشد:
```
METIS_API_KEY=...
METIS_BOT_ID=...
BACKEND_URL=...        # اختیاری؛ پیش‌فرض http://127.0.0.1:8000
```
نگاه کنید به [assistant.md](assistant.md).

## ۴) ساخت ایندکس دستیار هوش مصنوعی (RAG) — یک‌بار، اختیاری ولی لازم برای کارکرد دستیار

دستیار بدون این مرحله با خطای `503` (ایندکس ساخته نشده) پاسخ می‌دهد. ساخت کامل
برای همه‌ی خودروها حدود ۱.۵ تا ۲.۵ ساعت طول می‌کشد (resumable — قطع شدن مشکلی
ندارد، دوباره اجرا کنید):
```bash
./run_rag_build.sh
```
برای کاربر غیرفنی، راهنمای فارسیِ قدم‌به‌قدم: [RAG_GUIDE_FA.md](../RAG_GUIDE_FA.md).
جزئیات فنی دستور `python manage.py build_rag` و گزینه‌هایش در [assistant.md](assistant.md).

سپس `./run_server.sh` همان مدل امبدینگ (`RAG_EMBED_MODEL`, پیش‌فرض `bge-m3`) را
به‌صورت آفلاین برای سرو کردن دستیار بار می‌کند.

## افزودن خودروی جدید (Onboarding)

۱. فایل‌های `LEMON *.zip` خودرو را در پوشه‌ی `Cars_database/` قرار دهید.
۲. پارسر را اجرا کنید:
```bash
python htmlparser_logical.py "KG_backend"
```
یا از رابط گرافیکی استفاده کنید:
```bash
python parser_gui.py
```
۳. پارسر به‌صورت خودکار دیتابیس را به `Database_warehouse/`، تصاویر را به
   `static_warehouse/`، و رکورد خودرو را به `db.sqlite3` اضافه می‌کند.

جزئیات کامل در [data-pipeline.md](data-pipeline.md).

## عیب‌یابی

- `diagnose.py` — بررسی محیط و پیش‌نیازها:
  ```bash
  python diagnose.py
  ```
- اگر `run_server.sh` خطای «not set up» داد، ابتدا `check_prereqs.sh` را اجرا کنید.
- اگر تصاویر نمایش داده نمی‌شوند: مطمئن شوید بک‌اند با `DEBUG=True` اجرا شده
  (سرو `/media/` فقط در DEBUG فعال است) و پوشه‌ی `static_warehouse/<car>/`
  پر شده است.
- اگر فرانت‌اند به بک‌اند وصل نمی‌شود: `API_BASE` در `src/utils/api.jsx` باید
  با آدرس بک‌اند هم‌خوان باشد (پیش‌فرض `http://127.0.0.1:8000`).

## نکات مربوط به production

تنظیمات فعلی برای **توسعه** است. پیش از استقرار واقعی:
- `DEBUG = False` و تنظیم `ALLOWED_HOSTS`.
- جابه‌جایی `SECRET_KEY` به متغیر محیطی (اکنون hard-code است).
- محدودسازی CORS (اکنون `CORS_ALLOW_ALL_ORIGINS = True`).
- سرو `/media/` و فایل‌های static توسط وب‌سرور (نه Django).
