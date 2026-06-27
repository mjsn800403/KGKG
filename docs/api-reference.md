# مرجع API

پایه (توسعه): `http://127.0.0.1:8000`

تمام پاسخ‌ها JSON هستند. CORS برای همه‌ی originها باز است.

---

## `GET /`
فهرست یکتای نام برندهای موجود.

**پاسخ:** آرایه‌ای از رشته‌ها
```json
["Lexus", "Toyota"]
```

---

## `GET /<brand>/`
فهرست خودروهای یک برند (بدون توجه به بزرگی/کوچکی حروف، `iexact`).

**پاسخ:** آرایه‌ای از اشیاء خودرو
```json
[
  {"brand_name":"Toyota","car_name":"Land Cruiser Base","year":2025,"db_address":"./Database_warehouse/Land Cruiser Base.db"}
]
```

---

## `GET /<brand>/<year>/`
فهرست خودروهای یک برند در یک سال مشخص.

**پاسخ:** مشابه بالا، فیلترشده بر اساس `year`.

---

## `GET /<brand>/<year>/<model>/`
نقطه‌ی اصلی کار با درخت دفترچه. رفتار بر اساس query param تغییر می‌کند.

### الف) بدون پارامتر — گره‌های ریشه
گره‌های `node_type='root'` و `depth=1` (به‌جز artifactهای لینک مرده مثل
`href='404.html'`)، مرتب بر اساس `sort_order`.

**پاسخ:** آرایه‌ای از گره‌ها (ستون‌های `id, parent_id, path, title, node_type,
file_type, href, sort_order, depth, content`).

### ب) `?seg=A&seg=B&...` — پیمایش درخت
درخت گام‌به‌گام بر اساس تطبیق `(parent_id, title)` طی می‌شود (نه با مقایسه‌ی
رشته‌ی `path`، چون عنوان می‌تواند شامل «/» باشد). هر `seg` یک سطح است.

- اگر گره‌ی مقصد **برگ** باشد (`content` غیر null) → خودِ گره برگردانده می‌شود.
- در غیر این صورت → فرزندان گره‌ی مقصد برگردانده می‌شوند.
- مسیر یافت‌نشده → `404` با `{"error":"Path not found: <model>/A/B"}`.

> چرا query param و نه path؟ چون عنوان گره ممکن است شامل «/» باشد و سرور WSGI
> مقدار `%2F` در path را به «/» واقعی decode می‌کند و از جداکننده‌ی واقعی مسیر
> قابل‌تشخیص نیست.

### ج) `?q=<query>&limit=<n>` — جست‌وجو
جست‌وجوی شبه full-text روی `title` و `content` (LIKE، ASCII case-insensitive).
نتایجِ تطبیق با عنوان بالاتر از تطبیق صرفاً با محتوا رتبه می‌گیرند.
`limit` پیش‌فرض 30 و بین 1 تا 50 محدود می‌شود.

**پاسخ:** آرایه‌ای سبک برای ناوبری
```json
[
  {"title":"...","path":"...","node_type":"leaf","is_leaf":true,"segments":["A","B","C"]}
]
```
`segments` زنجیره‌ی عنوان‌ها از ریشه تا گره است (برای ساخت URL در فرانت‌اند).

### د) `?href=<filename>` — تبدیل لینک داخلی
محتوای دفترچه به سایر صفحات با نام فایل اصلی لینک می‌دهد
(مثل `pages/40738.html`). این endpoint نام فایل را به یک گره resolve کرده و
زنجیره‌ی عنوان‌ها را برمی‌گرداند.

> فقط در دیتابیس **همان خودرو** جست‌وجو می‌شود؛ نام‌فایل‌هایی مثل `5.html`
> شناسه‌های ترتیبی مستقل هر crawl هستند و سراسری یکتا نیستند. لینک‌هایی که به
> یک variant onboard‌نشده اشاره می‌کنند به‌درستی `404` می‌گیرند.

**پاسخ:**
```json
{"brand":"Toyota","year":2025,"model":"Land Cruiser Base","segments":["A","B"]}
```
یافت‌نشده → `404`.

### ه) `?page=<filename>` — صفحه‌ی یتیم
رندر مستقیم HTML یک صفحه که به‌عنوان گره ثبت نشده (مقصد cross-link یتیم)، از
پوشه‌ی منبع همان خودرو.

**پاسخ:**
```json
{"title":"...","content":"<...HTML...>"}
```
یافت‌نشده → `404` با `{"error":"Page not found: <file>"}`.

---

## `GET /media/<car_name>/<file>`
تصاویر/SVG هر خودرو (فقط در حالت `DEBUG`). ارجاع تصاویر داخل `content` به این
مسیر بازنویسی می‌شود.

---

## `POST /api/assist/` یا `GET /api/assist/?q=...`
بازیابی محلی RAG + گراف ارتباطی (بدون LLM، فقط جست‌وجوی ترکیبی وکتور+کلیدواژه
روی ایندکس `Database_warehouse/_rag/index.rag.db`). جزئیات معماری در
[assistant.md](assistant.md).

**بدنه‌ی POST:**
```json
{"query": "روغن ترمز", "brand": "Toyota", "model": "bZ4X", "car": "bZ4X XLE, AWD"}
```
معادل GET: `?q=...&brand=...&model=...&car=...` (`brand`/`model`/`car` اختیاری؛
استفاده می‌شوند تا نتیجه‌ای که در همان خودرو/مدل/برند رخ می‌دهد بالاتر رتبه بگیرد).

**پاسخ:**
```json
{
  "query": "...", "scope": {"brand": "...", "model": "...", "car_stem": "..."},
  "count": 8, "kind": "semantic", "grounded": true, "top_similarity": 0.72,
  "confidence_band": {"band": "medium", "label_fa": "نسبتاً مطمئن"},
  "adaptive": {"easy": false, "k": 8},
  "hits": [
    {
      "blob_id": 123, "car_stem": "...", "brand": "...", "model": "...",
      "variant": "...", "year": 2025, "title": "...", "title_path": "A › B › C",
      "system_tags": "...", "segments": ["B", "C"], "app_url": "/Toyota/2025/.../B/C",
      "score": 0.041, "similarity": 0.81, "text": "...",
      "matched_via": "vehicle", "confidence_band": "medium", "confidence_label": "نسبتاً مطمئن",
      "explain": {"rrf": 0.7, "sim": 0.81, "bm25": 0.6, "centrality": 0.5,
                  "boosts": {"vehicle": 1.5, "boilerplate": 1.0, "feedback": 1.0},
                  "final": 0.89, "matched_via": "vehicle"},
      "related": [{"title": "...", "relation": "labor_time", "app_url": "...", "snippet": "..."}],
      "cross_vehicle": [{"car_stem": "...", "model": "...", "scope": "same_model", "app_url": "..."}]
    }
  ]
}
```

> **فیلدهای نسخهٔ ۲** (لایه‌های پیشرفته — نگاه کنید به [assistant.md](assistant.md)):
> `kind` نوع پرسش، `grounded` آیا پاسخ پایهٔ معتبر دارد (پرسش out-of-domain با کفِ
> `GROUND_SIM_FLOOR` رد و `grounded:false` می‌شود)، `confidence_band` باند اطمینان،
> `top_similarity`، `adaptive` (عمق تطبیقی)، و per-hit: `matched_via` (نحوهٔ تطبیق:
> `exact_code`/`keyword`/`semantic`/`vehicle`/`expert_verified`)، `confidence_band`،
> و `explain` (تجزیهٔ سیگنال‌ها برای پنل «چرا این پاسخ؟»).

خطاها:
- `400` اگر `query` خالی باشد.
- `503` اگر ایندکس RAG هنوز ساخته نشده باشد: `{"error":"RAG index not built yet. Run: python manage.py build_rag"}`.
- `500` سایر خطاها (مثل عدم‌تطابق مدل امبدینگ بین ساخت و سرو).

---

## `POST /api/diagnose/` یا `GET /api/diagnose/?q=...&car=...`
موتور قاعده‌محور تشخیص (بدون LLM در منطق): کد خطا (DTC) یا علامتِ فارسی را به
کاندیداهای عیب، مراحل تشخیص و رویه‌ی تعمیر نگاشت می‌کند. روی sidecar هر خودرو
کار می‌کند (`Database_warehouse/_rag/diag/<car>.diag.db`، ساخته‌شده با
`python manage.py build_diag`). جزئیات معماری در [assistant.md](assistant.md).

**بدنه‌ی POST:**
```json
{"query": "P0301", "brand": "Toyota", "model": "bZ4X", "car": "bZ4X XLE, AWD"}
```
یا برای علامت: `{"query": "موتور لرزش دارد و چراغ چک روشن است", "car": "..."}`

**پاسخ (کد DTC):**
```json
{
  "query": "P0301", "intent": "dtc", "car_stem": "...", "known": true,
  "candidates": [
    {
      "code": "P0301", "name": "...", "inheritance_path": "Engine › Ignition › ...",
      "trigger": "...", "description": "...", "app_url": "/...",
      "steps": [{"aspect": "Description", "app_url": "/..."}],
      "procedure": {"title": "...", "app_url": "/..."},
      "labor_time": [{"title": "...", "app_url": "/..."}],
      "sibling_dtcs": ["P0302", "..."],
      "cross_vehicle": [{"model": "...", "variant": "...", "app_url": "/..."}],
      "confidence": 1.0
    }
  ],
  "symptoms": []
}
```

**پاسخ (علامت):** همان شکل بالا با `intent: "symptom"`، چند `candidates`
(هرکدام با `confidence` کمتر از ۱) به‌علاوه `procedures` (رویه‌های تشخیص
کارخانه‌ای مرتبط) و `symptoms` (علائم نزدیک از جدول کارخانه).

اگر سؤال در واقع یک کار تعمیری باشد (نه عیب)، `intent: "repair"` با
`candidates: []` برمی‌گردد — سیگنال به کلاینت برای fallback به `/api/assist/`.

خطاها:
- `400` اگر `query` خالی باشد.
- `503` اگر sidecar تشخیصیِ این خودرو ساخته نشده باشد:
  `{"error":"Diagnostic index not built yet. Run: python manage.py build_diag"}`.
- `500` سایر خطاها.

---

## `POST /api/assist/feedback/`
ثبت اینکه کاربر کدام نتیجه را باز کرده — سیگنال رتبه‌بندی برای بهبود آینده.
Best-effort: همیشه `{"ok": true}` برمی‌گرداند، حتی اگر لاگ‌کردن داخلی شکست بخورد.

**بدنه:**
```json
{"query": "روغن ترمز", "blob_id": 123, "app_url": "/Toyota/2025/.../B/C"}
```
فقط `POST` پذیرفته می‌شود (`405` برای سایر متدها).

---

## `POST /api/feedback/rate/` — رأی 👍/👎 (نسخهٔ ۲، HITL)
ثبت یک verdict صریح. به بوستِ محافظت‌شدهٔ رتبه‌بندی (`feedback.blob_boost_map`) تبدیل می‌شود.
Best-effort؛ همیشه `{"ok": true}`.

**بدنه:**
```json
{"query": "...", "verdict": -1, "mode": "assist", "top_blobs": [123,456],
 "blob_id": 123, "reason": "irrelevant", "comment": "اختیاری",
 "brand": "Toyota", "model": "bZ4X", "car": "bZ4X XLE, FWD"}
```
`verdict`: `+1` (مثبت) یا `-1` (منفی). `reason` ∈ `wrong|irrelevant|incomplete`.

---

## `POST /api/feedback/pin/` — پاسخِ «تأییدشدهٔ کارشناس» (نسخهٔ ۲)
یک منبع را برای یک الگوی پرسش پین می‌کند؛ `pattern_query` embed و ذخیره می‌شود تا با
پرسش‌های آینده تطبیق داده شود. اگر تطبیق قوی باشد، آن منبع در صدر با
`matched_via='expert_verified'` ظاهر می‌شود.

> ⚠️ این endpoint **هنوز بدون auth** است (نگاه کنید به [roadmap.md](roadmap.md) بخش امنیت).

**بدنه:**
```json
{"pattern_query": "تعویض روغن ترمز", "app_url": "/Toyota/2025/.../B/C",
 "blob_id": 123, "title": "...", "note": "...", "by": "expert"}
```
**پاسخ:** `{"ok": true}`.

---

## `GET /api/feedback/recent/?limit=50` — صف بازبینی (نسخهٔ ۲)
آخرین رأی‌های منفی (برای صفحهٔ `/admin-review`).

**پاسخ:**
```json
{"count": 3, "items": [{"ts": "...", "query": "...", "reason": "irrelevant",
   "comment": "...", "mode": "assist", "model": "...", "blob_id": 123}]}
```

---

## `GET /api/eval/report/` — گزارش ارزیابی آفلاین (نسخهٔ ۲، فقط‌خواندنی)
آخرین run هارنس ارزیابی + روند. هیچ هزینهٔ زمان‌پرسش ندارد (هارنس آفلاین فایل را می‌نویسد).

**پاسخ:**
```json
{"runs": 2, "latest": {"ts": "...", "aggregates": {"hit": 1.0, "mrr": 1.0,
   "ndcg": 1.0, "recall": 1.0, "precision": 0.25, "refusal_accuracy": 1.0},
   "calibration": {"medium": {"n": 2, "hit_rate": 1.0}},
   "latency_ms": {"p50": 267, "p90": 9800, "p99": 9800}}, "trend": [...]}
```

---

## کدهای وضعیت
| کد | معنی |
|----|------|
| 200 | موفق |
| 404 | خودرو/مسیر/گره/صفحه یافت نشد |
| 400 | URL نامعتبر |
| 500 | خطای داخلی (متن خطا در `error`) |
