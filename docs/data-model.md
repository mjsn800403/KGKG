# مدل داده

دو نوع دیتابیس SQLite در پروژه وجود دارد:

1. **دیتابیس اصلی** — `KG_backend/db.sqlite3` (شامل جدول `main_db` = فهرست خودروها)
2. **دیتابیس هر خودرو** — `KG_backend/Database_warehouse/<car_name>.db` (شامل جدول `nodes` = درخت دفترچه)

---

## ۱) جدول `main_db` (مدل Django: `Car`)

فهرست تمام خودروهای onboard‌شده. هر رکورد به فایل دیتابیس مخصوص آن خودرو اشاره می‌کند.

| ستون | نوع | توضیح |
|------|-----|-------|
| `id` | INTEGER PK | شناسه‌ی خودکار |
| `brand_name` | TEXT | نام برند (مثل `Toyota`, `Lexus`) |
| `car_name` | TEXT | نام مدل/خودرو (مثل `NX 350h`) |
| `year` | INTEGER | سال مدل |
| `db_address` | TEXT | مسیر نسبی دیتابیس خودرو، مثل `./Database_warehouse/NX 350h.db` |

> مدل Django در `KG_backend/api/models.py` با `db_table = 'main_db'` به این جدول
> map شده است.

نمونه:
```
Toyota | Corolla Cross Hybrid S | 2025 | ./Database_warehouse/Corolla Cross Hybrid S.db
Lexus  | NX 350h                | 2025 | ./Database_warehouse/NX 350h.db
```

---

## ۲) جدول `nodes` (درخت دفترچه‌ی هر خودرو)

هر سطر یک گره در درخت ناوبری دفترچه است. درخت با `parent_id` به‌صورت
خود-ارجاع (self-referential) ساخته می‌شود.

| ستون | نوع | توضیح |
|------|-----|-------|
| `id` | TEXT PK | `sha1(path)` |
| `parent_id` | TEXT | `sha1(parent_path)`؛ در ریشه `NULL` |
| `path` | TEXT | مسیر منطقی مطلق بر اساس breadcrumb |
| `title` | TEXT | عنوان نمایشی گره |
| `node_type` | TEXT | نقش گره: `root` / `folder` / `leaf` |
| `file_type` | TEXT | `root_path` / `intermediate_path` / `end_path` |
| `href` | TEXT | لینک اصلی مقصد (در صورت وجود) |
| `source_file` | TEXT | مسیر مطلق فایل HTMLی که این سطر از آن پارس شده |
| `sort_order` | INTEGER | ترتیب میان هم‌نیاها |
| `depth` | INTEGER | عمق در درخت (ریشه `depth=1`) |
| `root_order` | INTEGER | ترتیب میان گره‌های ریشه (در غیر این صورت `NULL`) |
| `content` | TEXT | HTML داخلیِ `div.main` برای صفحات برگ (`end_path`) |
| `updated_at` | TEXT | زمان آخرین به‌روزرسانی |

ایندکس‌ها:
```sql
CREATE INDEX idx_nodes_parent ON nodes(parent_id, sort_order);
CREATE INDEX idx_nodes_path   ON nodes(path);
CREATE INDEX idx_nodes_root   ON nodes(root_order);
```

### مفاهیم مهم

- **گره برگ (leaf):** گره‌ای که `content` آن `NULL` نیست؛ خود محتوای صفحه را
  دارد و فرزندی ندارد. در API به‌جای واکشی فرزندان، خودِ گره برگردانده می‌شود.
- **گره ریشه (root):** `node_type='root'` و `depth=1`. نقطه‌ی شروع مرور درخت.
- **ارجاع تصاویر در `content`:** محتوا به دو شکل به تصاویر اشاره می‌کند:
  - `<img src="../images/VA899634.svg">`
  - `<object data="/api/Image/SVGImage/VA899634">`
  هر دو در زمان سرو شدن به مسیر `/media/<car_name>/...` بازنویسی می‌شوند
  (تابع `rewrite_image_urls` در view).
- **صفحات یتیم (orphan):** برخی صفحات روی دیسک وجود دارند ولی به‌عنوان گره ثبت
  نشده‌اند (مثلاً مقصد یک cross-link). این‌ها با پارامتر `page=` مستقیم از پوشه‌ی
  منبع خودرو خوانده می‌شوند.

### آمار نمونه (خودروی `NX 350h`)

```
root   : 1904
folder : 17332
leaf   : 47599
```

---

## ۳) ایندکس RAG (`Database_warehouse/_rag/index.rag.db`)

دیتابیس سوم، جدا از دو مورد بالا و کاملاً اختیاری/قابل‌حذف: ایندکس محلی
دستیار هوش مصنوعی، ساخته‌شده با `python manage.py build_rag`. محتوای صفحات
این‌جا به‌صورت **حذف‌تکرارشده** (content-addressed) نگه داشته می‌شود — برخلاف
جدول `nodes` که هر صفحه را به ازای هر خودرو جدا ذخیره می‌کند.

| جدول | نقش |
|------|-----|
| `blobs` | هر سطر یک محتوای یکتا (یک‌بار به ازای هر hash، نه به ازای هر خودرو) |
| `occurrences` | هر محل ظهور یک blob (کدام خودرو/گره/breadcrumb) |
| `vec_blobs` | وکتورهای امبدینگ int8 (یکی به ازای هر blob؛ `rowid == blob_id`) |
| `blobs_fts` | ایندکس FTS5 برای جست‌وجوی کلیدواژه‌ای روی متن کامل صفحه |
| `edges` | گراف ارتباطی blob-to-blob (`semantic` / `crosslink` / `labor_time`) |
| `cars` | فهرست خودروهای واقعاً ایندکس‌شده + brand/model/variant/year |
| `meta` | متادیتای ساخت (مدل امبدینگ، ابعاد، زمان آخرین build) |

جزئیات کامل ساخت/سرو در [assistant.md](assistant.md).
