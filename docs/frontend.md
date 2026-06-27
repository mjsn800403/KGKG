# فرانت‌اند (Next.js)

مسیر: `kg_frontend/`

اپ **Next.js 16 (App Router)** با **React 19** و **Tailwind CSS 4**. رابط
فارسی و راست‌به‌چپ (`dir="rtl"`, `lang="fa"`)، تم تیره/روشن، و طراحی برند
«KGtechvault».

## اجرا

```bash
cd kg_frontend
npm install
npm run dev      # http://localhost:3000
```
اسکریپت‌ها: `dev`, `build`, `start`, `lint`.

## ساختار مسیرها (App Router)

```
src/app/
├── layout.tsx                 # چیدمان ریشه: فونت‌ها، BackgroundFX، microbar، Modal
├── page.tsx                   # لندینگ (هیرو، بررسی VIN)
├── globals.css                # استایل‌های سراسری + توکن‌های تم
├── login/page.tsx             # صفحه‌ی ورود
├── settings/page.tsx          # تنظیمات
├── browse/page.tsx            # مرور
├── assistant/page.jsx         # صفحه‌ی دستیار هوش مصنوعی
├── api/chat/route.js          # Route Handler سمت سرور (پراکسی Metis)
└── [brand]/
    ├── page.jsx                       # خودروهای یک برند
    └── [year]/
        ├── page.jsx                   # خودروهای برند/سال
        └── [model]/
            ├── page.jsx               # گره‌های ریشه‌ی خودرو
            ├── [...path]/page.jsx     # پیمایش درخت (catch-all)
            ├── search/page.jsx        # نتایج جست‌وجوی خودرو
            └── page/[file]/page.jsx   # نمایش صفحه‌ی یتیم (page=)
```

مسیرهای پویا ساختار `brand → year → model → path...` را آینه‌ی API می‌کنند.

## کلاینت API (`src/utils/api.jsx`)

تمام ارتباط با بک‌اند اینجاست. `API_BASE = 'http://127.0.0.1:8000'`.

| تابع | کاربرد |
|------|--------|
| `fetchAllBrands()` | `GET /` فهرست برندها |
| `fetchBrands(brand)` | خودروهای برند |
| `fetchYearData(brand, year)` | خودروهای برند/سال |
| `fetchNodes(brand, year, model, segments)` | پیمایش درخت (`?seg=`) |
| `resolveHref(brand, year, model, filename)` | تبدیل لینک داخلی (`?href=`) |
| `fetchRawPage(brand, year, model, filename)` | صفحه‌ی یتیم (`?page=`) |
| `searchNodes(brand, year, model, q, limit)` | جست‌وجو (`?q=`) |
| `buildNodeHref(brand, year, model, segments)` | ساخت URL درون‌برنامه از segmentها |
| `fetchModels(...)` | واکشی گره‌ها |

نکات مهم:
- **بازنویسی URL تصاویر:** پاسخ‌ها مسیر `/media/...` نسبی دارند؛
  `withAbsoluteMediaUrls()` آن‌ها را به URL مطلق نسبت به `API_BASE` تبدیل
  می‌کند (وگرنه مرورگر آن‌ها را نسبت به origin فرانت‌اند حل می‌کند).
- **segmentها به‌صورت `?seg=`:** نه در path آدرس، چون عنوان گره ممکن است شامل
  «/» باشد (همان دلیل سمت بک‌اند).

## کامپوننت‌ها (`src/components/`)

| کامپوننت | نقش |
|----------|-----|
| `DashboardShell` | پوسته‌ی داشبورد |
| `Sidebar` | نوار کناری ناوبری |
| `Breadcrumb` | مسیر breadcrumb |
| `NodeList` / `NodeItem` | فهرست و آیتم گره‌های درخت |
| `CardGrid` | شبکه‌ی کارت‌ها (برند/سال/مدل) |
| `ContentRenderer` | رندر امن HTML محتوای صفحه |
| `SearchBox` | جست‌وجوی هر خودرو با autocomplete (دیبونس، ناوبری با ↑/↓/Enter) |
| `FleetView` | نمای ناوگان |
| `AssistantChat` | چت دستیار؛ رندر لینک‌های `[label](href)` و `[BUTTON](title=..,href=..)` |
| `Modal` | دیالوگ سراسری (`showModal`) |
| `ThemeToggle` / `Switch` | تغییر تم تیره/روشن |
| `BackgroundFX` | افکت پس‌زمینه‌ی محیطی |

## تم و استایل

- تم پیش‌فرض تیره (`data-theme="dark"`)؛ قابل تغییر با `ThemeToggle`.
- فونت‌ها: Vazirmatn (فارسی)، Space Grotesk، IBM Plex Mono — از Google Fonts.
- `globals.css` توکن‌های رنگ/تایپوگرافی و استایل سراسری را تعریف می‌کند.

> دستیار هوش مصنوعی در [assistant.md](assistant.md) جداگانه توضیح داده شده است.
