<!-- i18n-source: 23-data-layer.md sha256:79cd24f1dc4a -->
<div dir="rtl" lang="fa">

# ۲۳ — لایهٔ داده: چه چیزی کجا ذخیره می‌شود

این نقشهٔ معتبر ذخیره‌سازی است. اسناد ۰۱، ۰۲، ۰۳ و ADR 0001 طراحی اولیه («یک SQLite فقط‌خواندنی برای هر خودرو») را شرح می‌دهند؛ تولید از آن زمان بیشتر محتوای دفترچه را به PostgreSQL برده است. ADR شمارهٔ `0007` این تغییر را ثبت می‌کند. وقتی این سند با اسناد قدیمی‌تر اختلاف دارد، این سند و کد معتبرند.

## ۲۳٫۱ چهار مخزن [C مگر برچسب دیگر]

| مخزن | موتور | چه نگه می‌دارد | پیکربندی با | کد |
|---|---|---|---|---|
| پایگاه پرتال `kgkg` | PostgreSQL 16 روی میزبان (`KG_DB_ENGINE=postgres`؛ در توسعه SQLite با نام `db.sqlite3`) | حساب‌ها، شرکت‌ها، اعطاها، نشست‌ها، لاگ‌ها، rollupها، درخواست‌ها، چت پشتیبانی، پایگاه دانش، پرچم‌ها | `KG_PG_NAME/USER/PASSWORD/HOST/PORT`، `KG_PG_CONN_MAX_AGE` | `KG_backend/settings.py`، `api/models.py` |
| محتوای خودرو، خودروهای دارای دفترچه | پایگاه PostgreSQL با نام `kgkg_vec`، یک schema با نام `car_<md5(نام فایل)>` برای هر خودرو، جدول رجیستری `public.car_dbs(filename, schema, nodes, loaded_at)` | درخت دفترچه (`nodes`، HTML، hrefها، مسیرها) با دوقلوهای ذخیره‌شدهٔ lowercase با پسوند `_lc` برای جست‌وجوی LIKE | `KG_CARDB_PG` (مقدار `*` = هر خودروی بارگذاری‌شده؛ یا نام فایل‌های جداشده با `|`)، `KG_CARDB_PG_DSN` (پیش‌فرض DSN مربوط به PG در RAG) | `api/cardb_pg.py` (کلاس `PgCarConn` سطح کوچک sqlite3 مورد استفادهٔ viewها را پشتیبانی می‌کند)، `api/cardb.py` |
| محتوای خودرو، خودروهای فقط‌قطعات | یک فایل SQLite برای هر خودرو زیر `Database_warehouse/_parts/` | درخت کاتالوگ قطعات | مسیرهای `KG_PARTS_*` در `api/parts.py` | `api/parts.py`، `api/partsingest.py` |
| ایندکس RAG | به‌صورت پیش‌فرض `_rag/index.rag.db` (SQLite + FTS5 + `sqlite-vec`)؛ بردارها/FTS می‌توانند در `kgkg_vec` آینه شوند (`blob_vec` با pgvector HNSW) | chunkها، embeddingهای int8[1024]، گراف، قواعد عیب‌یابی | `RAG_VEC_BACKEND`، `RAG_FTS_BACKEND` (پیش‌فرض `sqlite`)، `RAG_PGVEC_DSN/DB`، `RAG_PGVEC_EF_SEARCH` | `api/rag/config.py`، `ops/rag/pgvec_load.py`، `ops/rag/pgfts_load.py` |

فایل‌های دیگر: `terms.db` (اصطلاحات، سند ۱۴)، `feedback.db` (بازخورد دستیار)، رسانهٔ استاتیک زیر `static_warehouse` که از طریق nginx با subrequest احراز هویت سرو می‌شود (`api/mediaauth.py`).

## ۲۳٫۲ وضعیت تولید در ۲۰۲۶‑۱۱‑۰۳ [D: نشست ea4f3d3e، بررسی‌های فقط‌خواندنی؛ پیش از اتکا دوباره راستی‌آزمایی کنید]

- ۲۳۷ خودرو: **۲۲۲ خودروی دارای دفترچه فقط در PostgreSQL ‏`kgkg_vec` وجود دارند** (حدود ۵۸ گیگابایت)، **۱۵ خودروی فقط‌قطعات** کاتالوگ SQLite معتبر در `_parts` دارند، **۰ خودرو هر دو دارد**.
- `cardb_pg.adopt()` یک خودرو را بارگذاری می‌کند، گره‌ها را از طریق اتصال سرو دوباره می‌شمارد و سپس **فایل SQLite را حذف می‌کند** (و `-wal`/`-shm`). مرحلهٔ pipeline با نام `pgcar` (`api/pipeline.py`) آن را اجرا می‌کند. پس برای آن خودروها نسخهٔ SQLite برای بازگشت نیست.
- پشتیبان زمان دیپلوی (`pg_backup` در `deploy.sh`) فقط پایگاه `kgkg` را dump می‌کند. `kgkg_vec` در آن نیست، در snapshot ساعتی خارج از میزبان نیست و در `portal.dump` نیست [D]. `archive_mode` در PostgreSQL خاموش بود [D]. ← ریسک R1 در `27-open-risks-and-decisions.md`.
- سند ۱۱ بخش ۱۱٫۶ انبار را «مشتق (قابل بازسازی از ZIPهای منبع)» می‌خواند. این فقط وقتی درست است که ZIPها موجود و بازسازی شدنی باشد؛ اینکه ZIP چند خودرو از ۲۲۲ تا روی دیسک است **[U]** است (رقم «۲۶ از ۲۲۲» قبلی از تطبیق نام سست آمده و نامعتبر است).

## ۲۳٫۳ رفتارهایی که مردم را غافلگیر کرد [C]

- `has_manual` / `has_parts` روی کارت ناوگان از `cardb.ready_path` / `parts_db_ready` می‌آیند. پیش از PR #71 بررسی قطعات رجیستری PostgreSQL را بر اساس basename می‌پذیرفت، پس ۲۲۲ از ۲۳۷ خودرو chip قطعات نشان می‌دادند. آمادگی و اتصال قطعات اکنون فقط‌فایل SQLite است (`pg=False`)؛ chip فقط وقتی نشان داده می‌شود که `has_parts` باشد و `has_manual` نباشد (`kg_frontend/src/lib/vehicleContent.js`).
- ممکن است یک خودرو از PostgreSQL سرو شود در حالی که فایل SQLite کهنه با همان نام وجود دارد: وقتی نام فایل در `KG_CARDB_PG` باشد یا خودرو در `public.car_dbs` باشد PostgreSQL برنده است (۶۰ ثانیه کش، `_LOADED_TTL_S`).
- SQL نوشته‌شده برای SQLite در لحظه ترجمه می‌شود (`?`←`%s`، `printf('%08d',x)`←`lpad`، `title|content|href|path LIKE ?`← دوقلوی `_lc`، سایر `LIKE`←`ILIKE`). پرس‌وجوهای جدید در viewها باید درون همین زیرمجموعهٔ ترجمه‌شده بمانند یا `cardb_pg.py` و تستش (`test_cardb_pg.py`) را گسترش دهند.
- Staging (`deploy.sh --staging`) فقط `kgkg` را کلون می‌کند، اما بک‌اندش از محیط تولید استفاده می‌کند، پس همان `kgkg_vec` را می‌خواند و انبار را read-write mount می‌کند [D ‏۲۰۲۶‑۱۱‑۰۳]. `smoke_fleet.py` اکنون پرچم‌های has_manual/has_parts را در برابر نقاط پایانی assert می‌کند. staging را قادر به خواندن داده خودرو تولید بدانید.

## ۲۳٫۴ ابزارها [C]

| ابزار | هدف |
|---|---|
| `ops/cardb/pg_car_load.py "<car>.db"` | کپی یک خودروی SQLite به schema آن؛ فایل را **حذف نمی‌کند** |
| `ops/cardb/car_parity.py "<car>.db"` | تطابق بایت‌به‌بایت `car_view` بین SQLite و PostgreSQL در یک تراکنش rollbackشونده |
| `manage.py copy_sqlite_to_postgres` | کپی پایگاه پرتال به PostgreSQL (کمک‌ابزار cut-over، `ops/deploy/cutover_postgres.sh`) |
| `ops/rag/pgvec_load.py`، `pgfts_load.py`، `pgvec_bench.py` | آینه‌کردن/benchmark بردارهای RAG و FTS در PostgreSQL |

## ۲۳٫۵ پیش از لمس این لایه چه کنید

۱. `connect()` و `ready_path()` در `api/cardb.py` و `PgCarConn` در `api/cardb_pg.py` را بخوانید.
۲. `test_cardb_pg.py`، `tests_parts.py` و `test_vehiclefilter.py` را اجرا کنید.
۳. برای هر چیزی که داده خودرو را حذف، جابه‌جا یا دوباره بارگذاری می‌کند: بایستید و از مالک بپرسید. پشتیبان‌های `kgkg_vec` راستی‌آزمایی نشده‌اند (R1).

</div>
