<!-- i18n-source: 22-support-chat.md sha256:d9a68e3b37ad -->
<div dir="rtl" lang="fa">

# ۲۲ — چت پشتیبانی (ویجت بازدیدکننده و صندوق ورودی کارکنان)

گفتگوی زندهٔ انسانی برای بازدیدکنندگان ناشناس وب‌سایت که کارکنان ادمین پلتفرم پاسخ می‌دهند. از دستیار هوش مصنوعی (`/api/chat/`، سند ۰۸) و میزکار درخواست درون پرتال (`requests_api.py`) جداست. **وضعیت:** کد روی `work` است و مستقر شده، اما ویجت عمومی در تولید خاموش است مگر یک انسان `KG_SUPPORT_CHAT_ENABLED=1` را تنظیم کند. [C ‏`support_chat/config.py`] اینکه روی میزبان تنظیم شده **[U]** است (خوانده نشد؛ `.env.prod` در کار مستندسازی بررسی نمی‌شود). سوابق طراحی و تأییدها: `docs/superpowers/specs/2026-11-02-customer-communication-design.md`، `2026-11-02-phase3-support-chat-ux-design.md`، `2026-11-03-phase3-*`، `2026-11-03-support-readiness-gap-register.md`.

## ۲۲٫۱ نقشهٔ کد [C]

| قطعه | کجا |
|---|---|
| مدل‌های `SupportThread`، `SupportMessage`، `SupportRating`، `SupportPresence` | `KG_backend/api/support_chat/models.py` (migration با نام `0041_support_chat_core`) |
| API بازدیدکننده (ناشناس، توکن bearer) | `views_public.py`؛ routeها در `support_chat/urls.py` زیر `/api/support-chat/` |
| API کارکنان (نشست ادمین پلتفرم) | `views_admin.py`، `views_admin_inbox.py`، `views_status.py` زیر `/api/admin/support-chat/` |
| مدیریت توکن | `tokens.py`: ۳۲ بایت تصادفی، base64 امن برای URL، ۴۳ نویسه؛ فقط SHA-256 ذخیره می‌شود؛ توکن انتخابی کلاینت ایجاد thread را ایدمپوتنت می‌کند |
| قواعد ورودی | `limits.py` (حداکثر متن ۲۰۰۰ نویسه؛ intentهای `sales`، `demo`، `technical`، `other`) |
| محدودیت نرخ | `throttle.py`، پیش‌فرض‌ها در `config.py` (`KG_SC_<NAME>="N/seconds"`، مقدار `0/0` غیرفعال می‌کند)؛ به‌ازای thread نه IP، مگر ایجاد و شمارنده‌های توکن ناموفق |
| حضور («آیا کسی زنده است») | `presence.py`: متصل + اعلام در دسترس + حساب فعال؛ `KG_SUPPORT_PRESENCE_WINDOW_S` پیش‌فرض ۶۰ |
| بستن/بازگشایی | `lifecycle.py`؛ بازدیدکننده تا `KG_SUPPORT_REOPEN_DAYS` (پیش‌فرض ۱۴) می‌تواند دوباره باز کند |
| ماسک تماس | `mask.py`: کارکنان تلفن/ایمیل ماسک‌شده می‌بینند مگر مجوز فاش‌کردن داشته باشند |
| نقش‌ها | `rbac.py` (پنج نقش، حالت‌های `off` / `audit` / `enforce`)، `management/commands/support_roles.py` |
| سلامت صف | `health.py`، `manage.py support_health` (فقط‌خواندنی، به هشدارها وصل نیست) |
| نگهداشت | `manage.py purge_support_chat` فقط گزارش می‌دهد مگر `KG_SUPPORT_RETENTION_ENABLED=1` **و** `--apply` |
| فرانت‌اند | `kg_frontend/src/support-chat/` (کلاینت ویجت)، صندوق ورودی کارکنان در کنسول ادمین |

## ۲۲٫۲ مدل thread [C]

`SupportThread.status`: `open`، `waiting_staff`، `waiting_customer`، `closed`، `spam`. فیلدها: `intent`، `priority`، `assignee` (PlatformAdmin)، `contact_name/phone/email` (اختیاری، ارائه‌شده توسط بازدیدکننده)، `source_page`، `referrer`، `ua_hash` (هش، نه رشتهٔ agent)، `token_hash`، `promoted_request` (پیوند به یک `CompanyRequest` وقتی thread به درخواست میزکار تبدیل می‌شود)، `staff_seen_at`، `closed_at`. `SupportMessage.author_kind` (مقدارهای `visitor` / `admin` / `system`؛ کارکنان ردیف‌های `admin` هستند)، `internal` (یادداشت فقط‌کارکنان)، `client_id` (شناسهٔ سمت بازدیدکننده برای حذف تکرار ارسال مجدد). امتیازها (CSAT) یک ردیف برای هر رویداد امتیازدهی‌اند.

## ۲۲٫۳ ویژگی‌های امنیتی [C، تست‌شده در `support_chat/test_security_sweep.py`]

- routeهای بازدیدکننده برای thread واقعی و ناشناخته یکسان پاسخ می‌دهند (بدون oracle وجود).
- routeهای کارکنان بدون نشست ادمین ۴۰۱ می‌دهند؛ توکن حلقوی `KG_ADMIN_TOKEN` هرگز یک شخص نیست و در هیچ حالت RBAC مجوز پشتیبانی ندارد.
- لاگ‌ها متن پیام، داده تماس یا توکن حمل نمی‌کنند.
- همهٔ viewهای پشتیبانی عمداً `@csrf_exempt` هستند و در `api/csrf_registry.py` فهرست شده‌اند (سند ۲۱): routeهای بازدیدکننده با هدر توکن bearer و routeهای کارکنان با هدر ادمین احراز هویت می‌شوند؛ `OriginGuardMiddleware` بررسی بین‌مبدأ برای نوشتن‌های احرازشده با کوکی اضافه می‌کند.
- نسخه‌های staging/QA از داده تولید، فیلدهای تماس پشتیبانی و متن پیام‌ها را ماسک می‌کنند و اگر مقدار ماسک‌شده‌ای باقی بماند sanitizer اجرا را شکست می‌دهد (`ops/deploy/sanitize_staging_db.py --strict-audit`، PR #85). تولید در ۲۰۲۶‑۱۱‑۰۴ صفر thread پشتیبانی داشت. [D ‏Slack #kg-dev]

## ۲۲٫۴ عرضهٔ RBAC (اعمال خاموش است مگر پیکربندی شود)

`KG_SUPPORT_RBAC`: تنظیم‌نشده/خالی/`off` = هر ادمین *شخص* واردشده هرکاری را می‌تواند؛ `audit` = همان دسترسی اما ردهایی که رخ می‌داد به‌صورت ردیف ممیزی فقط‌شناسه نوشته می‌شود؛ `enforce` = پیش‌فرض رد. مقدار ناشناخته **بسته می‌شود** (به‌عنوان `enforce` رفتار می‌شود، لاگ می‌شود، `support_roles check` گزارش می‌دهد). `KG_SUPPORT_OWNERS` (نام‌های کاربری جداشده با کاما) مالکان اولیه‌اند. نقش‌ها تا وقتی جدول برنامه‌ریزی‌شدهٔ `SupportStaffRole` نیامده از محیط می‌آیند.

**migrationهای 0042/0043 روی `work` نیستند** (آخرین `0041` است، [C]). یک طراحی `0042` (`SupportThreadEvent` + `SupportThread.excluded`) و `0043` (`SupportStaffRole`) را رزرو می‌کند، در انتظار تأیید کتبی maintainer دیگر که شماره‌ها آزادند. [D ‏Slack #kg-dev ‏۲۰۲۶‑۱۱‑۰۳؛ پاسخ **[U]**]. پیش از ساخت هرکدام با `ops/deploy/check_migrations.py` و `git fetch` راستی‌آزمایی کنید.

## ۲۲٫۵ اداره آن

- رانبوک R10 در `20-runbooks.md`. پیش از فعال‌سازی عمومی: job با نام `support-chat-e2e` در CI باید سبز باشد (۲۱ تست مرورگر)، اعلان حریم خصوصی (پیش‌نویس در `docs/superpowers/specs/2026-11-02-privacy-notice-draft.md`، منتشرنشده) باید تأیید شود و نگهداشت پشتیبان باید معلوم باشد (سند ۲۷، R1/R5).
- کلید قطع: `KG_SUPPORT_CHAT_ENABLED` فقط threadهای *جدید* بازدیدکننده را کنترل می‌کند؛ threadهای موجود و پاسخ کارکنان کار می‌کنند.
- انتقال به‌روزرسانی زنده SSE با جایگزین polling است؛ جریان رویداد مشترک و watchdog توقف ۴۵ ثانیه‌ای در `kg_frontend/src/utils/eventStreamConnector.js` است (سند ۰۹).

## ۲۲٫۶ شکاف‌های شناخته‌شده [U / D]

- تا migration با نام `0042` خط زمانی `SupportThreadEvent` نیست؛ ردیابی از `AuditLog` (فقط شناسه‌ها) استفاده می‌کند.
- دوره‌های نگهداشت انتخاب نشده‌اند؛ purge غیرفعال است.
- وعدهٔ زمان پاسخ عمداً تنظیم نشده است (`KG_SUPPORT_REPLY_TARGET_MINUTES`).
- صندوق خروجی ارتباط با مشتری (`api/notifications/`، `manage.py process_outbox`، migration با نام `0040_notification_outbox`، واحد `ops/outbox/kgkg-outbox.service`) در [35-support-system.md](35-support-system.md) بخش ۳۵٫۹ مستند شده است (پیامک/ایمیل پیش‌فرض خاموش؛ ارائه‌دهندگان در `notifications/providers.py`؛ SMTP با `EMAIL_*` و `KG_NOTIFY_FROM_EMAIL`، ← سند ۲۴ هم). این فصل نقشهٔ کد است؛ [35](35-support-system.md) مرجع عمیق است.

</div>
