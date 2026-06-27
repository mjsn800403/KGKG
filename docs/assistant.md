# دستیار هوش مصنوعی

دستیار گفت‌وگویی **دو بخش دانش + یک جمله‌بند**:
1. **بازیابی عمومی (RAG)**: کاملاً محلی و آفلاین — لایه‌ی RAG + گراف ارتباطی
   (`KG_backend/api/rag/`) که مستقیماً از دیتابیس‌های خودرو ساخته شده. برای
   سؤال‌های تعمیری/مشخصات («روغن ترمز رو چطور عوض کنم؟»).
2. **موتور قاعده‌محور تشخیص عیب (Diagnostic engine)**: deterministic، بدون LLM
   در منطق؛ کد خطا (DTC) یا علامتِ فارسی را به فهرستِ کاندیداهای عیب، مراحل
   تشخیص مرتب‌شده و رویه‌ی تعمیر نگاشت می‌کند. برای سؤال‌های «چرا فلان اتفاق
   می‌افتد / این کد چیست».
3. **جمله‌بندی فارسی**: سرویس **Metis** (`api.metisai.ir`) فقط همان داده‌ی
   بازیابی‌شده (از RAG یا موتور تشخیص) را به فارسیِ روان تبدیل می‌کند؛ خودش
   منبع دانش نیست و حق ندارد چیزی بیرون از زمینه‌ی داده‌شده بسازد (طبق پرامپت
   سخت‌گیرانه‌ی سرور).

## معماری (مسیر دوگانه)

دستیار اکنون **per-car** است (نه یک صفحه‌ی سراسری): کاربر اول خودرو را انتخاب
می‌کند (`/assistant`)، سپس وارد دستیارِ همان خودرو می‌شود
(`/[brand]/[year]/[model]/assistant`). هر پیام در `route.js` این مسیر را طی
می‌کند:

```
کاربر ─▶ AssistantChat (کلاینت، scoped به یک خودرو)
       ─▶ POST /api/chat (Route Handler سمت سرور Next.js)
            ├─▶ اگر car/model مشخص است: اول POST Django /api/diagnose/
            │     (موتور قاعده‌محور DTC/symptom؛ deterministic)
            │     • قابل‌استفاده بود (diagUsable) → buildDiagnosisContext/Prompt
            │     • نبود/خطا داد → ادامه به مسیر RAG
            └─▶ در غیر این صورت یا fallback: POST Django /api/assist/
                  (بازیابی عمومی RAG، صفر هزینه‌ی شبکه‌ی خارجی)
                  • buildContext/buildPrompt
            ─▶ Metis session/message  (فقط جمله‌بندی فارسی روی هرکدام که انتخاب شد)
       ◀─ { sessionId, reply, sources, grounded, mode: "diagnose"|"assist" }
```

نکته‌ی کلیدی: **کلید API Metis فقط روی سرور است** و هرگز وارد باندل مرورگر
نمی‌شود. کلاینت فقط `{ message, sessionId?, userId? }` می‌فرستد.

## لایه‌ی RAG محلی (`KG_backend/api/rag/`)

ایندکس یکپارچه و **حذف‌تکرارشده** (content-addressed): محتوای یکسان میان
خودروها فقط یک‌بار ذخیره و امبد می‌شود («blob»)؛ محل‌های ظهور آن (هر خودرو/گره)
در جدول `occurrences` نگه داشته می‌شود. همه‌چیز در یک فایل واحد است:
`KG_backend/Database_warehouse/_rag/index.rag.db` (پاک‌کردن این پوشه کل سیستم
RAG را برمی‌گرداند؛ به دیتابیس‌های اصلی خودرو دست نمی‌زند — فقط read-only باز
می‌شوند).

ماژول‌ها:
| فایل | نقش |
|------|-----|
| `config.py` | تنظیمات مرکزی: مدل امبدینگ، آستانه‌های گراف، کش، CAR_REGISTRY |
| `store.py` | اتصال به دیتابیس‌ها (اصلی‌ها read-only، ایندکس RAG خواندنی/نوشتنی) + شِمای جداول |
| `ingest.py` | مرحله ۱: اسکن خودروها، حذف تکرار با hash، چانک‌بندی، نوشتن FTS |
| `embed.py` | مرحله ۲: امبد کردن هر blob (یک وکتور به ازای هر صفحه) |
| `graph.py` | مرحله ۳: ساخت گراف ارتباطی (`semantic` / `crosslink` / `labor_time`) |
| `retrieve.py` | مرحله ۴ (زمان پرسش): بازیابی ترکیبی (وکتور + کلیدواژه) + گسترش گراف |
| `service.py` | لایه‌ی سرو: کش پاسخ، قفل thread برای MPS، rerank اختیاری، لاگ |
| `glossary.py` | واژه‌نامه‌ی فارسی→انگلیسی برای غنی‌سازی پرسش‌های فارسی |
| `feedback.py` | لاگ پرسش‌ها + کلیک‌ها در یک دیتابیس کناری (`feedback.db`) |
| `diag.py` | زمان‌پرسش: ترجمه/غنی‌سازی پرسش فارسی، تشخیص intent (`dtc`/`symptom`/`repair`)، lookup دقیق DTC یا fuzzy-match علامت، ساخت زنجیره‌ی تشخیص |
| `diag_build.py` | ساخت sidecar تشخیصی هر خودرو از روی درخت `nodes` همان خودرو (جدول‌های `dtc`, `dtc_step`, `symptom`, `symptom_link` + ایندکس وکتور/FTS) |

### مدل امبدینگ

پیش‌فرض **`bge-m3`** (چندزبانه، ۱۰۲۴ بعدی)، انتخاب‌پذیر با متغیر محیطی
`RAG_EMBED_MODEL` (مقادیر دیگر: `e5-base`، `minilm` — هر سه آفلاین پس از
دانلود اول کار می‌کنند؛ مقدار باید هنگام ساخت و سرو **یکسان** باشد، وگرنه
`/api/assist/` خطای عدم‌تطابق مدل می‌دهد).

روی Apple Silicon (MPS): مدل با `float16` بار می‌شود (`RAG_EMBED_FP16=1`،
پیش‌فرض فعال) و `max_seq_length` به `256` محدود می‌شود (`config.MAX_SEQ_LEN`) —
چون buffer توجه bge-m3 برای حداکثر طول توالی مدل (۸۱۹۲) تخصیص می‌یابد که روی
حافظه‌ی محدودِ مک باعث abort می‌شود؛ محدودکردن به ۲۵۶ این buffer را به چند MB
می‌رساند. هر صفحه با یک وکتور (نه به ازای هر چانک) امبد می‌شود.

### ساخت ایندکس: `python manage.py build_rag`

دستور مدیریتی Django (`KG_backend/api/management/commands/build_rag.py`):

| گزینه | کاربرد |
|-------|--------|
| (بدون گزینه) | ساخت کامل/ازسرگیری (resumable) |
| `--rebuild` | پاک‌کردن `index.rag.db` و شروع از صفر |
| `--add` | فقط خودروهای جدید روی دیسک که هنوز در ایندکس نیستند را اضافه می‌کند (افزایشی، O(صفحات جدید)) |
| `--pilot <نام>` | فقط خودروهای یک مدل (مثل `bZ4X`) — برای اعتبارسنجی سریع |
| `--skip-embed` | فقط ingest/حذف‌تکرار، بدون امبدینگ |
| `--graph-only` | فقط بازسازی گراف ارتباطی (به وکتورهای موجود نیاز دارد) |
| `--labor-only` | فقط بازسازی یال‌های `labor_time` (سریع، بدون امبد مجدد) |
| `--batch-size N` | اندازه‌ی batch امبدینگ (پیش‌فرض ۱۶) |

پیش از و پس از هر اجرا، چک‌سام دیتابیس‌های اصلی خودرو گرفته می‌شود تا اثبات
شود دست‌نخورده مانده‌اند.

### اسکریپت کاربرپسند: `run_rag_build.sh`

اسکریپت bash در ریشه‌ی پروژه که `build_rag` را با تنظیمات آفلاینِ پایدار اجرا
می‌کند (برای کاربر غیرفنی، بدون نیاز به دستورات دستی):
- `RAG_EMBED_MODEL` پیش‌فرض `bge-m3`؛ `HF_HUB_OFFLINE=1` و
  `TRANSFORMERS_OFFLINE=1` تنظیم می‌شوند تا هیچ دانلودی تلاش نشود.
- اگر `index.rag.db` وجود نداشته باشد یا `RAG_REBUILD=1` ست شده باشد، با
  `--rebuild` اجرا می‌شود؛ در غیر این صورت ادامه (resume) می‌دهد.
- خروجی هم‌زمان روی صفحه و در یک فایل لاگ زیر
  `Database_warehouse/_rag/build_YYYYMMDD_HHMMSS.log` نوشته می‌شود.
- جزئیات کامل و قدم‌به‌قدم برای کاربر غیرفنی در [RAG_GUIDE_FA.md](../RAG_GUIDE_FA.md).

## API بازیابی عمومی: `/api/assist/`

`KG_backend/api/views.py` → `assist_view` / `assist_feedback_view`
(جزئیات کامل در [api-reference.md](api-reference.md)). نکات کلیدی:
- اگر ایندکس هنوز ساخته نشده باشد، `503` با پیام
  `RAG index not built yet. Run: python manage.py build_rag` برمی‌گردد.
- پاسخ شامل `hits` (هر کدام با `app_url` واقعی درون‌برنامه، `text`،
  `related` از گراف، و `cross_vehicle` برای «همین رویه در خودروهای دیگر») است.

## موتور قاعده‌محور تشخیص: `/api/diagnose/`

`KG_backend/api/views.py` → `diagnose_view` (در `urls.py` **قبل از** الگوهای
`<brand>` ثبت شده تا `/api/...` به‌اشتباه برند تفسیر نشود). منطق واقعی در
`api/rag/diag.py` (زمان پرسش) روی sidecar هر خودرو (`api/rag/diag_build.py`، ساخته
با `python manage.py build_diag`، نگاه کنید به [پایین](#ساخت-sidecar-تشخیصی-python-managepy-build_diag)):

- **ورودی DTC** (مثل `P0301`): lookup مستقیم در جدول `dtc` همان خودرو → کاندیدای
  تکی با `inheritance_path` (system › subsystem › component)، `trigger` (جملهٔ
  «کِی این کد ثبت می‌شود»)، زنجیرهٔ مراحل تشخیص (`steps`: Description → Symptom/
  Circuit Tests → Procedure)، `procedure` + `labor_time` (از یال‌های
  `labor_time` ایندکس یکپارچه)، `sibling_dtcs` (کدهای هم‌گروه) و `cross_vehicle`
  (همین کد در خودروی دیگر). کد ناشناخته → `known: false` و پیام صریح.
- **ورودی علامتِ فارسی**: ابتدا `_looks_like_repair()` چک می‌کند سؤال در واقع
  یک کار تعمیری (`چطور/تعویض/گشتاور/...`) است یا نه — اگر بود، `intent: 'repair'`
  برمی‌گردد تا پراکسی سراغ RAG عمومی برود. در غیر این صورت پرسش با
  `glossary.expand()` غنی می‌شود، embed می‌شود، و به‌صورت ترکیبی (وکتور + FTS)
  با علائم/DTCهای جدول `Problem Symptoms Table` همان خودرو match می‌شود. رتبه‌بندی
  سه‌سطحی: لینک مستقیم جدول علائم کارخانه (وزن بالا) > تطبیق معنایی مطمئن > هم‌خانوادگی
  زیرسیستم (fill-only). خروجی: `candidates` (هرکدام با `confidence`)، `procedures`،
  `symptoms`.
- پاسخ شامل `intent` (`'dtc'` | `'symptom'` | `'repair'` | `'unknown'`) است؛
  پراکسی Next.js بر اساس همین فیلد مسیر بعدی را تعیین می‌کند.
- ایندکس تشخیصی ساخته‌نشده/خودرو ناشناس → `503` با پیام
  `Diagnostic index not built yet. Run: python manage.py build_diag`.

### ساخت sidecar تشخیصی: `python manage.py build_diag`

دستور مدیریتی (`KG_backend/api/management/commands/build_diag.py`)، **باید بعد
از `build_rag` اجرا شود** (همان مدل embedding bge-m3 و یال‌های ایندکس یکپارچه
را دوباره استفاده می‌کند):

| گزینه | کاربرد |
|-------|--------|
| (بدون گزینه) | ساخت sidecar همه‌ی خودروهای روی دیسک |
| `--car "<نام>"` | فقط یک خودرو (تکرارپذیر برای چند خودرو) |
| `--rebuild` | پاک‌کردن sidecar هر خودرو قبل از ساخت |
| `--pilot <نام>` | فقط خودروهای یک مدل |

خروجی در `Database_warehouse/_rag/diag/<car_stem>.diag.db` — کاملاً قابل‌حذف
(در این صورت موتور تشخیص خاموش می‌شود و دستیار فقط با RAG عمومی پاسخ می‌دهد).
چک‌سام دیتابیس‌های اصلی پیش/پس از ساخت گرفته می‌شود تا اثبات شود فقط read-only
خوانده شده‌اند.

اسکریپت کاربرپسند: `./run_diag_build.sh` (همان الگوی `run_rag_build.sh` —
تنظیمات آفلاین، لاگ در همان پوشه، پیش‌فرض `--rebuild` اگر آرگومان نداشته باشد).
**باید بعد از `./run_rag_build.sh` اجرا شود.**

## پراکسی سمت سرور (`kg_frontend/src/app/api/chat/route.js`)

برای هر پیام (`message, sessionId, userId, brand, model, car`):

1. اگر `car` یا `model` مشخص باشد، اول `POST {BACKEND_URL}/api/diagnose/`
   فراخوانی می‌شود. تابع `diagUsable(d)` تشخیص می‌دهد نتیجه «قابل‌استفاده» است
   (برای `intent==='dtc'` همیشه؛ برای `'symptom'` فقط اگر `candidates`/`procedures`
   داشته باشد).
2. اگر قابل‌استفاده بود → `mode = 'diagnose'`؛ `buildDiagnosisContext(d)` یک
   بلوکِ متنیِ **کوچک‌نگه‌داشته‌شده** (برای جلوگیری از قطع اتصال Metis روی پرامپت
   بزرگ) از کاندیداها/رویه‌ها/علائم می‌سازد و `buildDiagnosisPrompt()` پرامپتی
   می‌دهد که منطق شرطی «اگر علامت X بود → کد محتمل Y → اول این تست → بعد رویه»
   را به فارسی بسازد.
3. در غیر این صورت (یا اگر `/api/diagnose/` خطا داد) → `mode = 'assist'`؛
   `POST {BACKEND_URL}/api/assist/` با `{ query: message, brand, model, car }`،
   سپس `buildContext()` (بلوک شماره‌گذاری‌شده‌ی عنوان/مسیر/لینک/متن/زمان‌کار
   مرتبط/صفحات مرتبط/«همین رویه در خودروهای دیگر») و `buildPrompt()`.
4. هر دو پرامپت Metis را موظف می‌کنند **فقط** از همان داده پاسخ دهد، لینک هر
   منبع را با قالب `[BUTTON](title="...", href="...")` بدهد، و اگر زمینه‌ای
   پیدا نشد صادقانه بگوید در داده‌ها نیست.
5. جریان دو مرحله‌ای Metis:
   ```
   POST session                  { botId, user:{id,name} }          -> { id, ... }
   POST session/{id}/message     { message:{type:"USER", content} }  -> { content, ... }
   ```

پاسخ endpoint به کلاینت:
```json
{ "sessionId": "<id>", "reply": "<متن پاسخ>", "sources": [...], "grounded": true, "mode": "diagnose" }
```

مدیریت خطا:
- نبودِ `METIS_API_KEY`/`METIS_BOT_ID` → `500`
- پیام خالی → `400` («پیام خالی است.»)
- خطای بازیابی از `/api/assist/` (مثلاً ایندکس ساخته نشده) → `502`
  («بازیابی از دیتابیس ناموفق بود. مطمئن شو ایندکس ساخته شده (build_rag / build_diag).»)
- خطای `/api/diagnose/` به‌صورت silent به مسیر RAG عمومی fallback می‌کند (فقط در
  کنسول لاگ می‌شود).
- خطای Metis → `502` («ارتباط با دستیار ناموفق بود.»)

## متغیرهای محیطی (`kg_frontend/.env.local`)

```
METIS_API_KEY=...     # کلید سرویس Metis (محرمانه — فقط سمت سرور)
METIS_BOT_ID=...      # شناسه‌ی بات
BACKEND_URL=...       # آدرس بک‌اند Django؛ پیش‌فرض http://127.0.0.1:8000
```

> ⚠️ این مقادیر اعتبارنامه‌ی واقعی‌اند و نباید در مخزن عمومی منتشر شوند. در
> صورت لو رفتن باید چرخش (rotate) داده شوند.

## کلاینت چت (`src/components/AssistantChat.jsx`)

- props: `{ brand, year, model, car }` — دستیار اکنون **scoped به یک خودرو** است؛
  `carName = car || model` به همراه هر پیام به `/api/chat` فرستاده می‌شود.
- یک شناسه‌ی کاربری پایدار (`kg_assistant_uid`) در `localStorage` می‌سازد و آن
  را به‌عنوان `userId` می‌فرستد تا session با ریلود مرورگر از دست نرود.
- `sessionId` را بین پیام‌ها نگه می‌دارد.
- پیام خوش‌آمدِ اولیه اگر `carName` موجود باشد، کاربر را به وارد کردن علامت
  فارسی **یا** کد DTC (مثل `P0301`) تشویق می‌کند.
- متن پاسخ بات را رندر می‌کند و دو نوع لینک را به عنصر قابل‌کلیک تبدیل می‌کند:
  - `[label](href)` — لینک معمولی
  - `[BUTTON](title="..", href="..")` — دکمه
- لینک‌های داخلی (شروع با «/») با `next/link` درون‌برنامه باز می‌شوند؛
  لینک‌های خارجی در تب جدید.

## صفحات دستیار (per-car)

دستیار دیگر یک صفحه‌ی سراسری نیست؛ دو صفحه دارد:
- `src/app/assistant/page.jsx` — **انتخاب‌گرِ خودرو**: همه‌ی خودروها را به‌صورت
  کارت می‌چیند، هر کارت به `/<brand>/<year>/<model>/assistant` لینک می‌شود.
- `src/app/[brand]/[year]/[model]/assistant/page.jsx` — دستیار scoped به همان
  خودرو؛ `AssistantChat` را با `car=model` رندر می‌کند و یک `SearchBox` همان
  خودرو هم در topbar دارد (جست‌وجوی سریع موازی با چت).

لینک ورودی به انتخاب‌گر در `Sidebar.jsx` («دستیار هوشمند») اضافه شده.

---

# نسخهٔ ۲ — لایه‌های پیشرفتهٔ RAG (۱۴۰۵/۰۴، 2026-06-25)

پنج لایه روی همان معماری اضافه شد؛ همگی **فقط زمان‌پرسش** (بدون rebuild ایندکس) و
**افزایشی/برگشت‌پذیر** (فقط در sidecar `feedback.db` می‌نویسند). تصمیم‌های پایه:
**بدون مدل دوم** (دقت از fusion وزن‌دار + BM25 + امتیاز کالیبره + بازخورد)، **ارزیابی
صفر-LLM**، **حلقهٔ بازخورد بسته با محافظ**.

### A) هستهٔ امتیازدهی (`scoring.py` — standalone، بدون Django، یونیت‌تست‌شده)
- `classify_query(query, eng_terms)` → نوع پرسش (`code`/`lexical`/`semantic`/`mixed`)
  و **وزن هر مسیر** (کد→کلیدواژه غالب، جملهٔ فارسی→معنایی غالب).
- `calibrate(signals)` → یک امتیاز نهاییِ قابل‌توضیح از ترکیب RRF + شباهت + BM25 +
  centrality گراف + بوست خودرو/penalty boilerplate/بوست بازخورد، به‌همراه `explain`.
- `confidence_band(...)` → باند `high|medium|low` با برچسب فارسی.
- `feedback_multiplier(...)` → فرمول بوستِ محافظت‌شده (clamp، حداقل تعداد).
- تست‌ها: `api/rag/test_scoring.py`، `api/rag/test_evalmetrics.py`
  (هم standalone از همان پوشه، هم `manage.py test`).

### B) بازیابی ترکیبیِ بهتر (`retrieve.py`)
- **RRF وزن‌دارِ تطبیقی** + گنجاندن نمرهٔ `bm25()` + **centrality** گراف + امتیاز کالیبره.
- **کف grounding**: اگر بهترین تطبیق ضعیف‌تر از `config.GROUND_SIM_FLOOR` (=۰٫۵۵) باشد،
  پرسش out-of-domain تلقی و **رد** می‌شود (`grounded=false`, باند `low`) به‌جای پاسخ
  گمراه‌کننده. (اندازه‌گیری: پرسش واقعی ≥۰٫۶۴، بی‌ربط ≤۰٫۴۹؛ پرسش کد از طریق BM25 عبور می‌کند.)
- پارامتر `qvec=` می‌پذیرد تا لایهٔ سرویس یک‌بار embed کند.

### C) بهینه‌سازی پویا (`service.py`)
- **عمق تطبیقی**: پرسش آسان (برندهٔ واضح + شباهت قوی) → hit و گسترش گراف کمتر = سبک‌تر.
- **کش معنایی پاسخ**: پارافریزِ تقریباً یکسان (cosine ≥ `SEM_CACHE_SIM`=۰٫۹۵، همان scope)
  از کش سرو می‌شود (~۷۴ms به‌جای ~۱۰s سرد). آستانه **عمداً بالا**: «روغن ترمز» vs
  «روغن موتور» شباهت ≈۰٫۸۱ — کش فقط برندهٔ تأخیر است، هرگز ادغام معنایی نیست.
- تله‌متری latency در `feedback.log_query`.

### D) حلقهٔ بستهٔ HITL (`feedback.py`)
- جداول `ratings` (👍/👎 + دلیل + متن) و `overrides` (پاسخ «تأییدشدهٔ کارشناس»).
- `blob_boost_map()`: رأی‌ها/کلیک‌ها → بوست هر blob با **محافظ** (clamp ۰٫۸۵–۱٫۲،
  حداقل ۳ سیگنال، نیمه‌عمر ۴۵ روزه)؛ در `calibrate` ضرب می‌شود.
- `pinned_match(qvec)`: اگر pattern یک override با qvec پرسش هم‌خوان باشد، آن منبع در
  صدر با `matched_via='expert_verified'` تزریق می‌شود (اصلاح دائمیِ کارشناس).

### E) شفافیت/تفسیرپذیری (high-stakes)
- بک‌اند حالا در هر hit `explain`/`matched_via`/`confidence_band` و در کل پاسخ
  `grounded`/`confidence_band`/`top_similarity` می‌دهد.
- فرانت‌اند: `EvidencePanel.jsx` (فهرست منابع + نوار اطمینان + برچسب نحوهٔ تطبیق +
  badge grounded/mode + هشدار «بدون پایه در داده‌ها» + «چرا این پاسخ؟»)؛
  `FeedbackBar.jsx` (👍/👎 + دلیل)؛ صفحهٔ `/admin-review` (صف بازبینی منفی‌ها).
- `route.js` حالا `grounded`/`mode`/`confidence`/`topBlobs` را عبور می‌دهد (قبلاً دور ریخته می‌شد).

### F) ارزیابی آفلاین صفر-LLM (`eval_rag` + `run_eval.sh`)
- `evalmetrics.py` (Hit@k/MRR/nDCG/recall/precision/calibration/percentile، یونیت‌تست‌شده)
  و `evalreport.py` (نوشتن/خواندن run تحت `_rag/eval/runs/`).
- `python manage.py eval_rag --bootstrap` gold set را از لاگ کلیک می‌سازد؛
  `eval_rag` امتیاز می‌دهد و **refusal-correctness** و **calibration** و latency گزارش می‌کند.

> ثابت‌های کالیبراسیون (`GROUND_SIM_FLOOR=0.55`, `SEM_CACHE_SIM=0.95`) عمدی و
> اندازه‌گیری‌شده‌اند. کارهای باقی‌مانده و اولویت‌ها در [roadmap.md](roadmap.md).
