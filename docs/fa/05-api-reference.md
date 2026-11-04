<!-- i18n-source: 05-api-reference.md sha256:1e94fbdda5b4 -->
<div dir="rtl" lang="fa">

# ۰۵ — مرجع API

همهٔ نقاط پایانی بک‌اند را Django روی `:8000` سرو می‌کند و به‌صورت عمومی زیر پیشوند nginx با نام `/kg-api/` در دسترس‌اند (مثلاً `POST https://kgtechvault.com/kg-api/api/auth/login/`؛ nginx TLS را پایان می‌دهد، ← [33-system-design.md](33-system-design.md)). مسیریابی: `api/urls.py`. همهٔ بدنه‌ها JSON است؛ همهٔ پاسخ‌ها JSON‌اند مگر خلافش ذکر شود.

> **فهرست کامل:** `docs/openapi.yaml` (OpenAPI 3.0.3) هر نقطهٔ پایانی مسیردهی‌شده را با متدها، احراز هویت و پارامترها مستند می‌کند و با تست اجباری می‌شود (`api/test_openapi_routes.py` اگر route بدون به‌روزرسانی آن فایل اضافه یا حذف شود شکست می‌خورد). [generated/routes.md](../generated/routes.md) همان فهرست در یک جدول است (مسیر، متدها، نوع احراز هویت، قاعدهٔ نرخ، خلاصه) که `ops/governance/gen_routes.py` تولید می‌کند و در CI بررسی می‌شود. **جدول‌های زیر یک نمای کلی گزیده‌اند و کامل نیستند**: routeهایی که حذف شده‌اند شامل گام‌های OTP و بازیابی (`api/auth/verify-otp|resend-otp|recover/*`، `api/admin/verify-otp`)، گراف سازمانی (`api/org/*`)، پرچم‌های ویژگی (`api/auth/flags`، `api/admin/flags*`)، سهمیهٔ استفاده (`api/auth/ai-usage`)، پایگاه دانش (`api/kb/*`، `api/admin/kb/*`)، لاگ چت و بازخورد (`api/auth/chat-log`، `api/auth/chat-feedback`)، onboarding و ترجیحات (`api/auth/onboarding`، `api/auth/me/prefs`)، کلید درخواست امضاشده (`api/shield/key`)، نقاط پایانی `auth_request` در nginx (`api/media-auth`، `api/vnc-auth`، `api/grafana-auth`)، متریک‌ها (`api/metrics`)، routeهای محتوای sst/parts/labor-times و routeهای چت پشتیبانی ([35-support-system.md](35-support-system.md)) است.

**انواع احراز هویت**

| نوع | چگونه |
|---|---|
| *public* (عمومی) | بدون احراز |
| *portal* | `Authorization: Bearer <AuthToken>` **یا** کوکی `kg_portal_token` (SSR) |
| *manager* | portal + `can_manage_team` (`@require_manager`) |
| *analytics* | portal + `can_view_analytics` یا `can_manage_team` (`@require_analytics`) |
| *admin* | `X-Admin-Token`/Bearer برابر مقدار env با نام `KG_ADMIN_TOKEN` **یا** توکن نشست `AdminAuthToken` (`@require_admin_token`) |

**محدودیت‌های نرخ** (`@rate_limited(name, N, window)` در `api/ratelimit.py`: پنجرهٔ لغزان به‌ازای IP کلاینت و به‌ازای هر فرایند worker، پس سقف مؤثر تا تعداد worker × N است؛ اگر خود محدودکننده خطا بدهد fail-open است). پیش‌فرض‌ها از decoratorها خوانده شده: login ‏۱۵/۶۰ ثانیه، verify_otp ‏۱۰/۶۰ ثانیه، resend_otp ‏۳/۶۰ ثانیه، recover_start ‏۵/۶۰ ثانیه، recover_reset ‏۱۰/۶۰ ثانیه، admin_login ‏۲۰/۶۰ ثانیه، admin_otp ‏۱۰/۶۰ ثانیه، activity ‏۱۲۰/۶۰ ثانیه، assist ‏۶۰/۶۰ ثانیه، diagnose ‏۶۰/۶۰ ثانیه، search ‏۹۰/۶۰ ثانیه، click ‏۱۲۰/۶۰ ثانیه، purchase ‏۱۰/۶۰ ثانیه، rate ‏۲۰/۶۰ ثانیه، pin ‏۳۰/۶۰ ثانیه، feedback ‏۳۰/۶۰ ثانیه، kb ‏۳۰۰/۶۰ ثانیه، parts ‏۶۰۰/۶۰ ثانیه. برای هر نقطهٔ پایانی با `KG_RL_<NAME>="N/seconds"` (مقدار `0/0` خاموش) override کنید یا همه را با `KG_RL_DISABLE=1` غیرفعال کنید. بدنهٔ ۴۲۹: `{error:'rate_limited', detail:<پیام فارسی>}` با هدر `Retry-After`. nginx منطقه‌های خودش را جلوتر اضافه می‌کند ([33](33-system-design.md) بخش ۳۳٫۲). نگاشت هر route: [generated/routes.md](../generated/routes.md).

**خطاهای رایج:** 401 ‏`{error:'unauthorized'}`؛ 403 ‏`{error:'forbidden', detail}` (detail فارسی برای دروازه‌های محتوا)؛ 400 خطای اعتبارسنجی `{error:<پیام فارسی>}`؛ 405 ‏`{error:'POST only'}`.

## ۵٫۱ سلامت و عمومی

| نقطه پایانی | متد | احراز | نکات |
|---|---|---|---|
| `/api/health/` | GET | public | زنده‌بودن: `{ok, uptime_s, db, time}` — برای پایشگرهای uptime |
| `/` | GET | public | فهرست برندهای متمایز (آرایه) — صفحهٔ فروش |
| `/api/purchase-request/` | POST | public | فرم سرنخ. بدنه: brand، model، year، documents[]، company، landline، mobile، reg_no، note?، employees_count?، seat_plan[] ‏({role, department, count, note} ← با `parse_seat_plan` اعتبارسنجی می‌شود)، wants_demo?، wants_ai_assistant?. ← `{ok, id}` |

## ۵٫۲ احراز هویت پرتال و نشست

| نقطه پایانی | متد | احراز | نکات |
|---|---|---|---|
| `/api/auth/login/` | POST | public | `{username, password}` — نام کاربری **یا ایمیل**؛ برابرسازی زمان. ← `{token, user}` (user = `_user_dict` کامل شامل قابلیت‌ها، `ai_eligible`، `accesses[]` با پرچم `ready` برای هر خودرو) |
| `/api/auth/logout/` | POST | portal | توکن ارائه‌شده را حذف می‌کند |
| `/api/auth/me/` | GET | portal | `{user}` — همان شکل login |
| `/api/auth/fleet/` | GET | portal | `{items:[{brand_name, car_name, year}]}` — خودروهای اعطاشده **و** روی دیسک (کاشی‌های /browse را می‌راند) |
| `/api/activity/` | POST | portal | beacon: `{action, detail?, category?|segments?, car_id?|brand+model+year?, node_title?, app_url?}` ← `{ok}`؛ دسته را سمت سرور تعیین می‌کند؛ رویداد `activity` شرکت را منتشر می‌کند |

## ۵٫۳ محتوا (همه به‌ازای هر خودرو گیت‌شده — سند ۰۶ بخش ۶٫۴)

| نقطه پایانی | متد | احراز | نکات |
|---|---|---|---|
| `/<brand>/` | GET | public* | سال‌های برند (فقط سطح کاتالوگ) |
| `/<brand>/<year>/` | GET | public* | مدل‌های سال. سال بی‌معنی ← `[]` (مسامحه‌گر) |
| `/<brand>/<year>/<model>/` | GET | **portal + اعطای خودرو** | گره‌های ریشه؛ عمیق‌تر با پارامترهای تکراری `?seg=<title>` (به ترتیب). فهرست گره یا برای صفحهٔ برگ `{nodes, content}` برمی‌گرداند؛ URL تصاویر از پیش بازنویسی شده |
| `/api/search/` | GET | portal + گیت خودرو | `q, brand, model, car?, limit?` — جست‌وجوی معنایی چندزبانه برای هر خودرو؛ اگر ایندکس نباشد به SQL LIKE برمی‌گردد |
| `/api/assist/` | GET/POST | portal + گیت خودرو | `{query, brand?, model?, car?}` ← گزیده‌های پایه‌دار با URL واقعی درون برنامه + مرتبط‌های گراف + زمینهٔ بین‌خودرویی (محدود به فهرست مجاز) |
| `/api/diagnose/` | GET/POST | portal + گیت خودرو | `{query, brand?, model?, car?}` ← نتیجهٔ قطعی DTC/علامت: کاندیدها، گام‌ها، تعمیر + زمان کار، تطبیق‌های بین‌خودرویی |

\* سطح برند/سال برای جریان فروش عمومی می‌ماند؛ محتوای خودرو اعطا می‌خواهد. `db_address` هرگز در هیچ پاسخی نمایش داده نمی‌شود.

## ۵٫۴ بازخورد دستیار / ارزیابی

| نقطه پایانی | متد | احراز | نکات |
|---|---|---|---|
| `/api/assist/feedback/` | POST | portal | لاگ کلیک `{query, blob_id, app_url}` (سیگنال ارتباط)، همیشه `{ok}` |
| `/api/feedback/rate/` | POST | portal | حکم 👍/👎 روی یک پاسخ (+دلیل/توضیح) |
| `/api/feedback/pin/` | POST | admin | pin کارشناسی: الگوی پرسش ← هدف شناخته‌شدهٔ درست |
| `/api/feedback/recent/` | GET | admin | فید بازبینی (`/admin-review` را می‌راند) |
| `/api/eval/report/` | GET | admin (از ۲۰۲۶‑۱۰‑۲۸ اجباری؛ پیش‌تر بدون اعتبارنامه در دسترس بود) | آخرین اجرای ارزیابی آفلاین (فقط‌خواندنی) |

## ۵٫۵ مدیریت تیم (مدیر)

نقاط پایانی قدیمی `/api/team/members|org|roles` در ۲۰۲۶‑۰۹‑۰۷ (کامیت `5aefebf`) حذف و با API گراف سازمانی `/api/org/*` جایگزین شدند (← `docs/openapi.yaml`).

| نقطه پایانی | متد | احراز | نکات |
|---|---|---|---|
| `/api/invite/<token>/` | GET | public | اعتبارسنجی دعوت ← `{user, company}` یا 4xx |
| `/api/invite/<token>/` | POST | public | `{password}` ← پذیرش + ورود خودکار `{token, user}` |

## ۵٫۶ تحلیل و پیشنهاد

| نقطه پایانی | متد | احراز | نکات |
|---|---|---|---|
| `/api/team/analytics/` | GET | analytics | `?range=N&member=<id>&category=<cid>` ← جمع‌ها، میله‌های هر دسته، تحلیل عمیق هر عضو، روند روزانه |
| `/api/team/report/` | GET | analytics | `?range=N` ← **PDF** (WeasyPrint فارسی/RTL، attachment) |
| `/api/team/insights/` | GET | manager | بهره‌برداری صندلی، اعضای بی‌کار/برتر، پوشش دسته و شکاف‌ها |
| `/api/recommendations/` | GET | portal | `?limit=N` ← شخصی‌سازی‌شده: ادامه / مرتبط / حوزه‌های تمرکز / محبوب در شرکت / کاوش |

## ۵٫۷ میزکار پشتیبانی (هر صندلی ↔ ادمین)

پیش‌تر «درخواست‌های شرکت (مدیر ↔ ادمین)» بود. از ۲۰۲۶‑۱۰‑۳۰ **هر صندلی واردشده** می‌تواند درخواست `support` یا `other` ثبت کند؛ انواع تجاری (`vehicle_access`، `seats`، `ai_assistant`، `documents`) فقط برای مدیر می‌ماند چون شرکت را به هزینه یا دامنه متعهد می‌کنند. صندلی تیکت‌هایی را می‌بیند که خودش ثبت کرده؛ مدیر تیکت‌های شرکت را. کد: `api/requests_api.py`، `api/sla.py`. دلیل و تحلیل علت ریشه‌ای: `audit-evidence/16-improvement-programme/`.

| نقطه پایانی | متد | احراز | نکات |
|---|---|---|---|
| `/api/company/requests/` | GET/POST | portal | فهرست (مال خود، یا مال شرکت برای مدیر)؛ ساخت `{kind, subject, body?, payload?, priority?}` (payload برای هر نوع فهرست مجاز می‌شود). `source` همیشه `portal` است — هرگز از کلاینت گرفته نمی‌شود |
| `/api/company/requests/<id>/` | GET/POST | portal | جزئیات با رشتهٔ پیام (یادداشت‌های داخلی حذف). POST یکی از `{message}` (پاسخ؛ تیکت بسته را دوباره باز و ساعت حل را از نو شروع می‌کند)، `{csat:{score 1..5, comment?}}` (یک‌بار، پس از بسته‌شدن، توسط ثبت‌کننده)، `{cancel:true}` |
| `/api/admin/company-requests/` | GET/POST | admin | صندوق (فیلتر با `status`، `source`، `company_id`)؛ POST ‏`{company_id, subject, body?, kind?, priority?, source?}` درخواستی را ثبت می‌کند که تلفنی، ایمیلی یا حضوری رسیده |
| `/api/admin/company-requests/<id>/` | GET/POST | admin | GET تیکت را با یادداشت‌های داخلی می‌دهد. POST ‏`{status?, admin_note?, handled_by?, message?, internal?, assignee_id?, escalate?}`. اولین چیزی که مشتری می‌تواند بخواند — پیام عمومی **یا** `admin_note` غیرخالی — `first_response_at` را مهر می‌زند؛ یادداشت داخلی و تغییر ساده وضعیت نمی‌زند و هرگز بازنویسی نمی‌شود. `escalate` ایدمپوتنت است و اولویت را به high می‌برد |
| `/api/admin/company-requests/<id>/promote-to-article/` | POST | admin | `{slug, title?, category?, audience?}` — تیکت بسته را به **پیش‌نویس** مقالهٔ پایگاه دانش تبدیل می‌کند که با پرسش، رشتهٔ عمومی و راه‌حل پر می‌شود |
| `/api/admin/support/metrics/` | GET | admin | `?days=30` — حجم‌ها، زمان‌های اولین پاسخ و حل (میانگین و p90)، رعایت SLA، CSAT، `by_source`، `by_kind`، کهنگی backlog، بلوک‌های بازخورد و دانش. هر فیلد در `audit-evidence/16-improvement-programme/METRIC_DEFINITIONS.md` تعریف شده است |

**اهداف SLA** (`api/sla.py`، ساعت تقویمی، نه ساعت کاری): بالا ۲ ساعت اولین پاسخ / ۸ ساعت حل · عادی ۸ / ۴۸ · پایین ۲۴ / ۱۲۰. وضعیت هر تیکت `met` / `breached` / `pending` است؛ `pending` از رعایت کنار گذاشته می‌شود.

## ۵٫۷a بازخورد محصول

بازخورد عمومی محصول عمداً تیکت نیست (بدون SLA)، ← `api/feedback.py`.

| نقطه پایانی | متد | احراز | نکات |
|---|---|---|---|
| `/api/feedback/submit/` | POST | portal | `{page?, rating? 1..5, comment?}` — یا امتیاز یا توضیح الزامی است. محدودیت نرخ `feedback` برابر ۳۰/۶۰ ثانیه. برای مخاطب ادمین منتشر می‌کند |
| `/api/admin/feedback/` | GET | admin | `?days=30` — فید به‌علاوهٔ جمع‌ها و تفکیک هر صفحه |

## ۵٫۷b پایگاه دانش

مقالات **مالک مشخص**، فاصلهٔ بازبینی (`is_stale` = هرگز بازبینی نشده یا از فاصله گذشته)، ویرایش‌های فقط‌افزودنی و منشأ اختیاری از تیکتی که از آن ارتقا یافته‌اند دارند. کد: `api/knowledge.py`.

| نقطه پایانی | متد | احراز | نکات |
|---|---|---|---|
| `/api/kb/` | GET | portal | `?q=&category=` — مقالات منتشرشدهٔ رو به مشتری. جست‌وجوی `q=` با تعداد نتیجه لاگ می‌شود (`KbSearchLog`)؛ مرور فهرست لاگ نمی‌شود |
| `/api/kb/<slug>/` | GET | portal | مقاله؛ یک بازدید می‌شمارد |
| `/api/kb/<slug>/vote/` | POST | portal | `{helpful: bool}` |
| `/api/admin/kb/` | GET/POST | admin | GET همه (`?status=`، `?audience=`، `?stale=1`)؛ POST ‏`{title, slug, body, category?, audience?, status?, review_interval_days?}`. `slug` باید با `^[a-zA-Z0-9][-a-zA-Z0-9_]*$` جور باشد — آنچه route خواننده یعنی `<slug:slug>` می‌تواند مطابقت دهد — تا مقالهٔ منتشرشده همیشه با URL خودش قابل دسترس باشد |
| `/api/admin/kb/<id>/` | GET/POST | admin | GET همراه تاریخچهٔ ویرایش. POST ‏`{title?, body?, category?, status?, audience?, owner_id?, review_interval_days?, reviewed?, note?}` — تغییر **متن** یک ویرایش اضافه و نسخه را افزایش می‌دهد؛ بازبینی، تغییر وضعیت یا تغییر مالک نمی‌دهد |

## ۵٫۷c چت پشتیبانی (بازدیدکنندهٔ ناشناس و صندوق ورودی کارکنان)

از زیر ۵٫۷a به اینجا منتقل شد، جایی که ردیف‌هایش بدون عنوان گذاشته شده بودند. معنا، ماشین وضعیت، محدودیت‌ها و RBAC: [35-support-system.md](35-support-system.md). برای threadهای جدید بازدیدکننده خاموش است مگر `KG_SUPPORT_CHAT_ENABLED=1`.

| نقطه پایانی | متد | احراز | نکات |
|---|---|---|---|
| `/api/support-chat/status/` | GET | public | `{enabled, mode: live\|async, reply_target_minutes}`؛ `?intent=sales\|demo\|technical\|other` اختیاری دربارهٔ یک intent می‌پرسد (فقط وقتی `live` است که کسی که می‌تواند به *همان* intent پاسخ دهد در دسترس باشد، پس از اعمال نقش‌ها؛ برای intent ناشناخته 400). `live` فقط وقتی است که یک عضو کارکنان وصل باشد (ping در ۶۰ ثانیهٔ اخیر) **و** در دسترس اعلام کرده باشد. `reply_target_minutes` تهی است مگر مالک `KG_SUPPORT_REPLY_TARGET_MINUTES` را تنظیم کند؛ SLA داخلی تیکت هرگز نمایش داده نمی‌شود. محدودیت `status_ip` |
| `/api/support-chat/threads/` | POST | public + Turnstile (action با نام `support_chat`) | `{message, intent?, client_id?, token?, contact?, page?, referrer?, website?}`. با `token` ۴۳ نویسه‌ای تولیدشده در کلاینت، ایجاد ایدمپوتنت است: تکرار همان thread را (200) بدون پیام جدید و بدون بررسی Turnstile دوم برمی‌گرداند. بدون آن سرور یک‌بار توکن می‌دهد. `page`/`referrer` بدون query و fragment ذخیره می‌شوند. محدودیت `create_ip` (۲۰ در ۱۰ دقیقه برای هر IP) |
| `/api/support-chat/threads/<id>/messages/` | GET, POST | توکن بازدیدکننده (`X-Support-Chat-Token`) | GET ‏`?after=<id>`: پیام‌ها (یادداشت داخلی هرگز؛ کارکنان فقط با برچسب «پشتیبانی»، خطوط سیستم با «سامانه»)، `status`، `mode`، `staff_seen_at`، `can_reopen`. POST: ۲۰۰۰ نویسه، ایدمپوتنت روی `client_id`، 409 با `closed` روی thread بسته. محدودیت هر thread (`poll`، `send`، `send_hour`)؛ توکن مخدوش = 404 بدون query |
| `/api/support-chat/threads/<id>/contact/` | PATCH | توکن بازدیدکننده | `{name?, phone?, email?}`؛ تلفن نرمال می‌شود. محدودیت `contact` |
| `/api/support-chat/threads/<id>/reopen/` | POST | توکن بازدیدکننده | ادامهٔ thread بسته در `KG_SUPPORT_REOPEN_DAYS` (پیش‌فرض ۱۴)؛ وگرنه 409 با `reopen_window_expired`. شمرده، با یادداشت سیستم، و بدون IP ممیزی می‌شود |
| `/api/support-chat/threads/<id>/csat/` | POST | توکن بازدیدکننده | `{score 1..5}`؛ فقط threadهای بسته؛ یک امتیاز برای هر بسته‌شدن، امتیازهای قبلی حفظ می‌شود. محدودیت `csat` |
| `/api/admin/support-chat/presence/heartbeat/` | POST | نشست ادمین (شخص) | ping کنسول (حدود ۲۰ ثانیه) |
| `/api/admin/support-chat/presence/` | GET, PUT | admin (GET) / نشست ادمین (PUT) | GET: برای هر عضو کارکنان `connected`، `declared`، `eligible`. PUT ‏`{status: available\|away\|offline}` |
| `/api/admin/support-chat/threads/<id>/reply/` | POST | نشست ادمین (شخص) | `{message, internal?}`. پاسخ عمومی ← `waiting_customer`؛ thread بسته رد می‌شود (409) و هرگز با پاسخ باز نمی‌شود |
| `/api/admin/support-chat/threads/<id>/close/` | POST | نشست ادمین (شخص) | بستن؛ پیام سیستم + ردیف ممیزی (فقط شناسه‌ها) |
| `/api/admin/support-chat/threads/<id>/reopen/` | POST | نشست ادمین (شخص) | بازگشایی صریح؛ شمرده و ممیزی می‌شود |
| `/api/admin/support-chat/threads/<id>/seen/` | POST | نشست ادمین (شخص) | thread را دیده‌شده توسط کارکنان علامت می‌زند |
| `/api/admin/support-chat/threads/` | GET | نشست ادمین (شخص) | فهرست صندوق ورودی کارکنان. فیلترها: `status` (`active` پیش‌فرض، `all`، یا یک وضعیت)، `intent`، `priority`، `assignee` (`me`/`none`/id)، `unread=1`، `q` (پیشوند id یا فیلدهای تماس، هرگز متن پیام)، `limit` از ۱ تا ۱۰۰، `cursor`. `threads`، `counts`، `next_cursor` برمی‌گرداند. تلفن و ایمیل ماسک می‌شوند |
| `/api/admin/support-chat/threads/<id>/` | GET | نشست ادمین (شخص) | یک thread با همهٔ پیام‌ها (یادداشت‌های داخلی علامت‌دار)، تاریخچهٔ امتیاز و `capabilities` (آنچه فراخواننده اینجا می‌تواند: reply، take، assign، priority، intent، close، reopen، spam، reveal_contact؛ سرور هر درخواست را دوباره بررسی می‌کند). threadهای خارج از دامنه پس از اعمال نقش‌ها 404 می‌دهند. `?after=<id>`؛ `?reveal_contact=1` تماس کامل را برمی‌گرداند و یک ردیف ممیزی فقط‌شناسه می‌نویسد |
| `/api/admin/support-chat/threads/<id>/assign/` | POST | نشست ادمین (شخص) | `{admin: <id>\|"me"\|null}`؛ هدف باید حساب فعال کارکنان باشد |
| `/api/admin/support-chat/threads/<id>/priority/` | POST | نشست ادمین (شخص) | `{priority: low\|normal\|high\|urgent}` |
| `/api/admin/support-chat/threads/<id>/intent/` | POST | نشست ادمین (شخص) | `{intent: sales\|demo\|technical\|other}` |
| `/api/admin/support-chat/threads/<id>/spam/` | POST | نشست ادمین (شخص) | spam: توکن بازدیدکننده از کار می‌افتد (404)؛ `restore` آن را برمی‌گرداند |
| `/api/admin/support-chat/threads/<id>/restore/` | POST | نشست ادمین (شخص) | بازگرداندن spam به `waiting_staff` |

## ۵٫۸ بی‌درنگ

| نقطه پایانی | متد | احراز | نکات |
|---|---|---|---|
| `/api/events/stream/` | GET | portal یا admin | **SSE.** پرس‌وجوی `?admin=1` برای مخاطب ادمین. ازسرگیری با هدر `Last-Event-ID` یا `?after=`. فریم‌ها: `id`، `event:<type>`، `data:{id,type,ts,payload}`؛ توضیح heartbeat هر ۱۵ ثانیه؛ جریان پس از ۳۰۰ ثانیه بازیافت می‌شود (کلاینت خودکار دوباره وصل می‌شود). nginx برای این مسیر location بدون بافر اختصاصی دارد |
| `/api/events/recent/` | GET | portal یا admin | جبران عقب‌ماندگی REST: `?after=<id>&limit=` |

دیده‌شدن مخاطب شرکت `can_manage_team` یا `can_view_analytics` می‌خواهد؛ کاربر ساده فقط رویدادهای مخاطب `user` خودش را می‌گیرد.

## ۵٫۹ API ادمین پلتفرم

همه احراز هویت *admin*. پنل ادمین (`/admin`) تنها مصرف‌کننده است.

| نقطه پایانی | متد | نکات |
|---|---|---|
| `/api/admin/login/` | POST | `{username, password}` ← `{token, admin}` (PlatformAdmin) |
| `/api/admin/overview/` | GET | خلاصهٔ KPI پلتفرم |
| `/api/admin/dashboard/` | GET | تجمیع داشبورد زنده (KPI، پردازش، درخواست‌ها، هشدارها، فعالیت، ترافیک) |
| `/api/admin/processing-snapshot/` | GET | عکس فوری کار در انتظار (همان منبع پنل pipeline) |
| `/api/admin/packages/` | GET | فهرست شناسه/برچسب بسته‌ها |
| `/api/admin/cars/` | GET | کاتالوگ + آمادگی پایگاه هر خودرو + شاخص‌های سلامت (`health`: وضعیت، درصد کامل‌بودن، بخش‌های جاافتاده/خالی، ایندکس RAG/diag/دارایی، فرایندهای در انتظار — از آخرین DataQualityRun) + `has_spec`/`spec_fields`؛ `audited_at` روی پاکت. فیلتر کاتالوگ ادمین را می‌راند (سند ۰۷ بخش ۷٫۷) |
| `/api/admin/requests/` | GET | درخواست‌های خرید؛ `/<id>/status/` با POST وضعیت گردش‌کار را به‌روز می‌کند |
| `/api/admin/companies/` | GET/POST | فهرست/ساخت (کاشت پیش‌فرض نقش‌های سازمانی دیگر وجود ندارد؛ گراف سازمانی در اولین استفاده از `api/org/*` کاشته می‌شود) |
| `/api/admin/companies/<id>/` | GET/POST | جزئیات (عمیق: دسترسی‌ها+کاربران) / به‌روزرسانی (با کلمپ طول فیلد) |
| `/api/admin/companies/<id>/access/` | POST | جایگزینی دامنهٔ خریداری‌شده؛ اعطاهای خارج از دامنه را هرس می‌کند (ردیف‌های admin_granted می‌مانند) |
| `/api/admin/users/` | GET/POST | مدیریت کاربر بین‌شرکتی؛ ساخت اعتبارنامه صادر می‌کند |
| `/api/admin/users/<id>/` | GET/POST | به‌روزرسانی شامل جابه‌جایی نقش/شرکت؛ ترمیم سازگاری سازمانی را اجرا می‌کند |
| `/api/admin/users/<id>/access/` | POST | جایگزینی اعطاها با `apply_user_access(allow_admin_grants=True)` — ممکن است از خرید فراتر رود (admin_granted) |
| `/api/admin/activity/` | GET | گزارش فعالیت قابل فیلتر (شرکت/کاربر/اقدام/دسته/تاریخ) |
| `/api/admin/analytics/` | GET | تحلیل استفادهٔ بین‌شرکتی |
| `/api/admin/data-quality/` | GET/POST | GET آخرین گزارش ممیزی؛ POST ‏`{refresh:true}` یا `{fix:true}` ← اجرای ناهمگام |
| `/api/admin/pipeline/` | GET/POST | GET وضعیت کامل (job، کار در انتظار، بار، توصیه، تنظیمات، تاریخچه)؛ POST ‏`{action:'start'|'schedule'|'resume'|'cancel'|'settings', …}` |
| `/api/admin/system/` | GET | `system_snapshot`: disk/mem/load/uptime، وضعیت DB+RAG، هشدارها |
| `/api/admin/traffic/` | GET | سری ترافیک، جدول تأخیر/خطای هر نقطهٔ پایانی، استفاده از ویژگی‌ها، یکتای روزانه |

## ۵٫۱۰ API داخلی فرانت‌اند (سرور Next.js)

| نقطه پایانی | متد | احراز | نکات |
|---|---|---|---|
| `/api/chat` | POST | توکن پرتال (در برابر `/api/auth/me/` بک‌اند + `ai_eligible` اعتبارسنجی می‌شود) | route گفتگوی دستیار. با diagnose←assist بک‌اند پایه‌دار می‌کند، سپس Metis با پرامپت سخت‌گیرانهٔ فقط‌زمینه + دروازهٔ وفاداری پیوند بازنویسی می‌کند؛ fallback قطعی بدون LLM. محدودیت نرخ به‌ازای IP (از `x-real-ip`/آخرین hop در XFF). اعتبارنامهٔ Metis هرگز به مرورگر نمی‌رسد. جزئیات: [30](30-ai-assistant-deep-dive.md) |

## ۵٫۱۱ قراردادها برای نقاط پایانی جدید

- بدنه‌ها را با کمک‌های سخت‌شده بخوانید (`portal._body` / `views._post_body` / `adminops._json_body`) — JSON غیر dict را به `{}` تبدیل می‌کنند (بدنهٔ `"string"` نباید ۵۰۰ بدهد).
- برای خطاهای مورد انتظار رشتهٔ `error` فارسی و قابل‌نمایش به کاربر برگردانید؛ فیلدهای ماشینی (`ok`، idها) را پایدار نگه دارید.
- هر چیز بدون احراز هویت یا پرهزینه را محدود نرخ کنید (`@rate_limited`).
- برای تغییر وضعیت‌هایی که داشبوردهای دیگر باید ببینند رویداد منتشر کنید (سند ۰۹ بخش emitterها).

</div>
