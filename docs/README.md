# KGtechvault — مستندات پروژه

پلتفرم مرور و جست‌وجوی **دفترچه‌های فنی/تعمیراتی خودرو** (Repair / Service Manuals).
داده‌ها از آرشیوهای HTML آفلاین (فایل‌های `LEMON *.zip`) استخراج، به ساختار درختی
تبدیل، و از طریق یک API به یک رابط وب مدرن سرو می‌شوند. یک دستیار هوش مصنوعی
**per-car** هم تعبیه شده: کاربر اول خودرو را انتخاب می‌کند، سپس می‌تواند کد خطا
(DTC) یا علامتِ فارسی را برای **تشخیص قاعده‌محور عیب** بدهد، یا سؤال تعمیری/مشخصات
بپرسد که از **RAG عمومی** پاسخ می‌گیرد. در هر دو حالت Metis فقط جمله‌بندی فارسی
را انجام می‌دهد؛ دانش از ایندکس‌های محلی می‌آید.

```
ZIP خام  ──parser──▶  دیتابیس‌های SQLite (هر خودرو یکی)  ──Django API──▶  Next.js UI ──▶ کاربر
                                                                      └─▶ دستیار هوش مصنوعی per-car
                                                                            (موتور تشخیص DTC/علامت
                                                                             + RAG عمومی + Metis)
```

## فهرست مستندات

| سند | موضوع |
|-----|-------|
| [architecture.md](architecture.md) | معماری کلی، اجزا و جریان داده |
| [data-pipeline.md](data-pipeline.md) | پارسر HTML، استخراج zip و ساخت دیتابیس‌ها |
| [backend.md](backend.md) | بک‌اند Django، مدل داده، منطق view |
| [api-reference.md](api-reference.md) | مرجع کامل endpointهای API |
| [frontend.md](frontend.md) | فرانت‌اند Next.js، صفحات و کامپوننت‌ها |
| [assistant.md](assistant.md) | دستیار هوش مصنوعی، پراکسی Metis، و **لایه‌های پیشرفتهٔ RAG (نسخهٔ ۲)** |
| [setup-and-run.md](setup-and-run.md) | نصب، پیش‌نیازها و اجرای پروژه |
| [data-model.md](data-model.md) | شِمای دیتابیس‌ها (main_db و nodes) |
| [roadmap.md](roadmap.md) | **ممیزی کامل معماری + نقشهٔ راه** (کارهای باقی‌مانده، حل‌شدنی با کد یا نه) |

## ساختار پوشه‌ها (سطح بالا)

```
khadamat/
├── htmlparser_logical.py     # پارسر اصلی: zip → دیتابیس درختی
├── parser_gui.py             # رابط گرافیکی دسکتاپ برای پارسر (Tkinter)
├── parser_gui_config.json    # مسیرهای آخرین استفاده‌شده‌ی GUI
├── diagnose.py               # بررسی محیط/پیش‌نیازها
├── check_prereqs.sh / .bat   # نصب پیش‌نیازهای بک‌اند و فرانت‌اند
├── run_server.sh / .bat      # اجرای همزمان بک‌اند + فرانت‌اند
├── Cars_database/            # فایل‌های ورودی LEMON *.zip و دیتابیس‌های خام
│
├── run_rag_build.sh          # ساخت ایندکس RAG عمومی (مرحله‌ی ۱)
├── run_diag_build.sh         # ساخت sidecarهای موتور تشخیص DTC/علامت (بعد از RAG)
├── run_eval.sh               # ارزیابی آفلاینِ کیفیت بازیابی (صفر-LLM؛ نگاه کنید به roadmap/assistant)
├── Book1.csv                 # واژه‌نامه‌ی قطعات انگلیسی↔فارسی (ورودی glossary.py)
│
├── KG_backend/               # سرویس Django
│   ├── manage.py
│   ├── db.sqlite3            # دیتابیس اصلی (فهرست خودروها = جدول main_db)
│   ├── api/                  # اپ اصلی
│   │   ├── models.py / views.py / urls.py
│   │   ├── rag/               # RAG عمومی + گراف + موتور تشخیص (نگاه کنید به assistant.md)
│   │   └── management/commands/   # build_rag, build_diag
│   ├── Database_warehouse/   # یک دیتابیس SQLite به ازای هر خودرو + _rag/ (ایندکس RAG و sidecarهای تشخیصی)
│   └── static_warehouse/     # تصاویر/SVG هر خودرو (از طریق /media سرو می‌شود)
│
└── kg_frontend/              # اپ Next.js (App Router)
    ├── src/app/              # صفحات (مسیر پویا brand/year/model/...، assistant/، api/chat/)
    ├── src/components/       # کامپوننت‌های UI (AssistantChat, SearchBox, ...)
    └── src/utils/api.jsx     # کلاینت ارتباط با بک‌اند
```

> توجه: این مستندات فقط توصیفی‌اند و هیچ بخشی از زیرساخت یا کد را تغییر نمی‌دهند.
