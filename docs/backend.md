# بک‌اند (Django)

مسیر: `KG_backend/`

سرویس Django که داده‌ی دفترچه‌ها را به‌صورت JSON و تصاویر را از طریق `/media/`
سرو می‌کند. کل منطق در یک view واحد (`car_view`) متمرکز است.

## ساختار

```
KG_backend/
├── manage.py
├── db.sqlite3                 # دیتابیس اصلی (جدول main_db)
├── KG_backend/                # پکیج پروژه
│   ├── settings.py
│   ├── urls.py                # admin/ + include('api.urls') + سرو media در DEBUG
│   ├── wsgi.py / asgi.py
├── api/                       # اپ اصلی
│   ├── models.py             # مدل Car (جدول main_db)
│   ├── views.py             # brands_list_view + car_view + assist_view + diagnose_view + assist_feedback_view
│   ├── urls.py              # مسیرهای API (api/assist, api/diagnose قبل از <brand>)
│   ├── rag/                 # لایه‌ی RAG محلی + گراف ارتباطی + موتور تشخیص (نگاه کنید به assistant.md)
│   ├── management/commands/build_rag.py   # دستور ساخت/به‌روزرسانی ایندکس RAG
│   ├── management/commands/build_diag.py  # دستور ساخت sidecarهای تشخیصی (بعد از build_rag)
│   └── admin.py / apps.py / tests.py
├── Database_warehouse/        # دیتابیس هر خودرو (*.db)
│   └── _rag/                  # ایندکس RAG (index.rag.db) + feedback.db — قابل حذف کامل
└── static_warehouse/          # تصاویر هر خودرو (سرو از /media/)
```

## تنظیمات کلیدی (`settings.py`)

- `DEBUG = True` — حالت توسعه. (برای production باید غیرفعال شود.)
- `CORS_ALLOW_ALL_ORIGINS = True` — اجازه‌ی دسترسی فرانت‌اند از origin دیگر.
  از طریق `corsheaders` و middleware آن.
- `DATABASES['default']` → `BASE_DIR / 'db.sqlite3'` (دیتابیس اصلی).
- `MEDIA_URL = '/media/'`، `MEDIA_ROOT = BASE_DIR / 'static_warehouse'`.
- در حالت DEBUG، فایل‌های media مستقیماً توسط Django سرو می‌شوند (`urls.py`).

> ⚠️ نکته‌ی امنیتی: `SECRET_KEY` به‌صورت hard-code در settings قرار دارد و
> `DEBUG=True` است. این تنظیمات فقط برای محیط توسعه مناسب‌اند.

## مدل داده

تنها مدل ORM، `Car` است (نگاه کنید به [data-model.md](data-model.md)).
درخت گره‌های هر خودرو در ORM مدل نشده و viewها با `sqlite3` خام به فایل
دیتابیس خودرو وصل می‌شوند.

## viewها (`api/views.py`)

### `brands_list_view(request)`
`GET /` — فهرست یکتای نام برندها از روی جدول `main_db`.

### `assist_view(request)` / `diagnose_view(request)` / `assist_feedback_view(request)`
`/api/assist/`، `/api/diagnose/` و `/api/assist/feedback/` — لایه‌ی نازک روی
`api/rag/service.py` (بازیابی RAG عمومی)، `api/rag/diag.py` (موتور قاعده‌محور
DTC/symptom) و `api/rag/feedback.py`. منطق بازیابی/رتبه‌بندی/تشخیص واقعی داخل
`api/rag/` است؛ این viewها فقط ورودی HTTP را به آن لایه پاس می‌دهند.

> ⚠️ نکته‌ی ترتیب: `path('api/diagnose/', ...)` و `path('api/assist/', ...)` در
> `urls.py` **قبل از** الگوهای `<brand_name>/` ثبت شده‌اند، وگرنه `car_view`
> رشته‌ی `api` را به‌اشتباه به‌عنوان نام برند می‌گرفت.

جزئیات کامل در [assistant.md](assistant.md) و [api-reference.md](api-reference.md).

### `car_view(request, brand_name, year, model_name)`
view چندمنظوره که بسته به پارامترها رفتار متفاوتی دارد. جزئیات کامل در
[api-reference.md](api-reference.md). خلاصه‌ی شاخه‌ها:

| شرط | رفتار |
|-----|-------|
| فقط `brand` | خودروهای آن برند از `main_db` |
| `brand` + `year` | خودروهای آن برند و سال |
| `brand`+`year`+`model`، بدون پارامتر | گره‌های ریشه‌ی خودرو |
| `?seg=A&seg=B...` | پیمایش درخت گام‌به‌گام بر اساس عنوان |
| `?q=...` | جست‌وجو در عنوان و محتوای درخت خودرو |
| `?href=...` | تبدیل لینک داخلی (نام فایل) به مسیر گره |
| `?page=...` | خواندن مستقیم HTML یک صفحه‌ی یتیم از دیسک |

### توابع کمکی مهم

- `get_car_db(db_address)` — اتصال به دیتابیس خودرو (مسیر نسبت به پوشه‌ی
  `db.sqlite3` حل می‌شود).
- `rewrite_image_urls(content, car_name)` — بازنویسی ارجاع تصاویر به
  `/media/<car_name>/...` (هم `src="../images/..."` و هم
  `data="/api/Image/SVGImage/..."`).
- `node_to_dict(row, car_name)` — تبدیل سطر دیتابیس به dict با محتوای بازنویسی‌شده.
- `_car_source_dir(cur)` — یافتن ریشه‌ی crawl اصلی خودرو از روی `source_file`.
- `read_page_content(cur, car_name, filename)` — رندر HTML صفحه‌ی یتیم (بدون گره)
  از پوشه‌ی منبع همان خودرو (scope‌شده تا نام فایل‌های مشترک مثل `5.html` با
  خودروی دیگر تداخل نکنند).

## مدیریت خطا

- `Car.DoesNotExist` → 404 با `{'error': 'Car not found'}`
- `FileNotFoundError` (دیتابیس خودرو موجود نیست) → 404
- سایر استثناها → 500 با متن خطا
- مسیر/گره/href یافت‌نشده → 404 با پیام مشخص
