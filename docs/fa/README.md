<div dir="rtl" lang="fa">

# مستندات فارسی KGtechvault

این پوشه نسخهٔ فارسیِ همهٔ اسناد مرجع مهندسی (۰۰ تا ۳۷) است. هر فایل دقیقاً همنام فایل انگلیسی خودش در `docs/` است و خط اول آن مهری به شکل `<!-- i18n-source: <name>.md sha256:… -->` دارد. اگر سند انگلیسی تغییر کند، مهر دیگر مطابقت ندارد و بررسی `ops/governance/check_i18n.py` در CI تا به‌روزشدن ترجمه شکست می‌خورد (دستور `python3 ops/governance/check_i18n.py --stamp <file>` را فقط پس از به‌روزرسانی واقعی متن فارسی اجرا کنید). فهرست اسنادی که ترجمهٔ الزامی دارند در `docs/i18n.toml` است.

| سند فارسی | نسخهٔ انگلیسی |
|---|---|
| [۰۰ — مشخصات نیازمندی‌های نرم‌افزار (SRS)](00-srs.md) | [00-srs.md](../00-srs.md) |
| [۰۱ — نمای کلی سیستم](01-overview.md) | [01-overview.md](../01-overview.md) |
| [۰۲ — معماری](02-architecture.md) | [02-architecture.md](../02-architecture.md) |
| [۰۳ — مدل داده](03-data-model.md) | [03-data-model.md](../03-data-model.md) |
| [۰۴ — مرجع بک‌اند (`KG_backend/api`)](04-backend-reference.md) | [04-backend-reference.md](../04-backend-reference.md) |
| [۰۵ — مرجع API](05-api-reference.md) | [05-api-reference.md](../05-api-reference.md) |
| [۰۶ — مجوزها و RBAC](06-permissions-rbac.md) | [06-permissions-rbac.md](../06-permissions-rbac.md) |
| [۰۷ — فرانت‌اند (`kg_frontend`)](07-frontend.md) | [07-frontend.md](../07-frontend.md) |
| [۰۸ — دستیار هوش مصنوعی و RAG](08-ai-assistant-rag.md) | [08-ai-assistant-rag.md](../08-ai-assistant-rag.md) |
| [۰۹ — رویدادهای بی‌درنگ (SSE)](09-realtime-sse.md) | [09-realtime-sse.md](../09-realtime-sse.md) |
| [۱۰ — تحلیل، گزارش و پیشنهاد](10-analytics-reporting.md) | [10-analytics-reporting.md](../10-analytics-reporting.md) |
| [۱۱ — عملیات و استقرار](11-operations-deployment.md) | [11-operations-deployment.md](../11-operations-deployment.md) |
| [۱۲ — امنیت](12-security.md) | [12-security.md](../12-security.md) |
| [۱۳ — سیستم راهنمای کاربر](13-guidance-system.md) | [13-guidance-system.md](../13-guidance-system.md) |
| [۱۴ — مخزن اصطلاحات دوزبانه](14-terminology.md) | [14-terminology.md](../14-terminology.md) |
| [۱۵ — داده ساختاریافتهٔ خودرو (schema.org) و گسترش pipeline ورود محتوا](15-vehicle-schema.md) | [15-vehicle-schema.md](../15-vehicle-schema.md) |
| [۱۶ — کاتالوگ قطعات یدکی (Parts Catalog)](16-parts-catalog.md) | [16-parts-catalog.md](../16-parts-catalog.md) |
| [۱۷ — مجموعهٔ ارزیابی هوش مصنوعی](17-evaluation.md) | [17-evaluation.md](../17-evaluation.md) |
| [۱۸ — سخت‌سازی امنیت: رازها، محدودسازی نرخ، WAF، پایش خطا](18-security-hardening.md) | [18-security-hardening.md](../18-security-hardening.md) |
| [۱۹ — آشناسازی مهندس جدید](19-onboarding.md) | [19-onboarding.md](../19-onboarding.md) |
| [۲۰ — رانبوک‌ها](20-runbooks.md) | [20-runbooks.md](../20-runbooks.md) |
| [۲۱. viewهای معاف از CSRF](21-csrf-exempt-views.md) | [21-csrf-exempt-views.md](../21-csrf-exempt-views.md) |
| [۲۲ — چت پشتیبانی (ویجت بازدیدکننده و صندوق ورودی کارکنان)](22-support-chat.md) | [22-support-chat.md](../22-support-chat.md) |
| [۲۳ — لایهٔ داده: چه چیزی کجا ذخیره می‌شود](23-data-layer.md) | [23-data-layer.md](../23-data-layer.md) |
| [۲۴ — یکپارچگی‌های خارجی](24-integrations.md) | [24-integrations.md](../24-integrations.md) |
| [۲۵ — موجودی عملیات: میزبان، واحدها، کانتینرها، پوشه‌ها](25-ops-inventory.md) | [25-ops-inventory.md](../25-ops-inventory.md) |
| [۲۶ — احراز هویت و نشست‌ها همان‌گونه که ساخته شده](26-auth-and-sessions.md) | [26-auth-and-sessions.md](../26-auth-and-sessions.md) |
| [۲۷ — ریسک‌های باز و تصمیم‌های در انتظار](27-open-risks-and-decisions.md) | [27-open-risks-and-decisions.md](../27-open-risks-and-decisions.md) |
| [۲۸ — روال تیم: GitHub، Jira، Slack، Trello](28-team-workflow.md) | [28-team-workflow.md](../28-team-workflow.md) |
| [۲۹ — مرجع متغیرهای محیطی (متغیرهای عملیاتی و تنظیمی)](29-environment-reference.md) | [29-environment-reference.md](../29-environment-reference.md) |
| [۳۰ — دستیار هوش مصنوعی تخصصی: بررسی عمیق از ابتدا تا انتها](30-ai-assistant-deep-dive.md) | [30-ai-assistant-deep-dive.md](../30-ai-assistant-deep-dive.md) |
| [۳۱ — مرجع فایل‌ها و واحدهای عملیاتی (پایش، لاگ، تحلیل، ابزار آفلاین RAG، baselineهای امنیتی)](31-ops-files-reference.md) | [31-ops-files-reference.md](../31-ops-files-reference.md) |
| [۳۲ — تست، تضمین کیفیت و راستی‌آزمایی](32-testing-and-qa.md) | [32-testing-and-qa.md](../32-testing-and-qa.md) |
| [۳۳ — طراحی سیستم (آنچه پیاده‌سازی شده)](33-system-design.md) | [33-system-design.md](../33-system-design.md) |
| [۳۴ — مرجع مدل داده (موجودیت‌ها، روابط، چرخهٔ عمر، الگوهای دسترسی)](34-data-model-reference.md) | [34-data-model-reference.md](../34-data-model-reference.md) |
| [۳۵ — سامانهٔ پشتیبانی مشتری (چت بازدیدکننده، صندوق ورودی کارکنان، تیکت، اعلان‌ها)](35-support-system.md) | [35-support-system.md](../35-support-system.md) |
| [۳۶ — CI/CD، انتشار و استقرار (از ابتدا تا انتها)](36-cicd-and-deployment.md) | [36-cicd-and-deployment.md](../36-cicd-and-deployment.md) |
| [۳۷ — ردیابی نیازمندی تا پیاده‌سازی](37-requirements-traceability.md) | [37-requirements-traceability.md](../37-requirements-traceability.md) |
| [۳۸ — ماتریس وضعیت پیاده‌سازی و بهره‌برداری](38-implementation-status-matrix.md) | [38-implementation-status-matrix.md](../38-implementation-status-matrix.md) |
| [۳۹ — راهنمای شواهد ارزیابی](39-evaluation-evidence-guide.md) | [39-evaluation-evidence-guide.md](../39-evaluation-evidence-guide.md) |
| [۴۰ — راهنمای دسترسی به مستندات](40-documentation-access-guide.md) | [40-documentation-access-guide.md](../40-documentation-access-guide.md) |
| [۴۱ — ارزیابی پوشش مستندات و فهرست کارهای باقی‌مانده](41-documentation-coverage-and-backlog.md) | [41-documentation-coverage-and-backlog.md](../41-documentation-coverage-and-backlog.md) |
| [۴۲ — مرجع معماری فرانت‌اند](42-frontend-architecture.md) | [42-frontend-architecture.md](../42-frontend-architecture.md) |
| [۴۳ — نمودارهای معماری و جریان داده](43-architecture-diagrams.md) | [43-architecture-diagrams.md](../43-architecture-diagrams.md) |
| [۴۴ — چرخهٔ عمر داده](44-data-lifecycle.md) | [44-data-lifecycle.md](../44-data-lifecycle.md) |
| [راهنمای کاربر](../manuals/fa/01-user-guide.md) · [راهنمای کارکنان و ادمین](../manuals/fa/02-staff-admin-guide.md) | فقط فارسی |
| [۴۷ — فهرست پیگیری مهندسی](../47-engineering-followups.md) | فقط انگلیسی (فهرست داخلی) |

قواعد ترجمه: شناسه‌ها، مسیر فایل‌ها، دستورات، نام جدول‌ها و کلیدهای پیکربندی عیناً حفظ می‌شوند؛ متن توضیحی فارسی است؛ برچسب‌های شواهد (`[C]`، `[S]`، `[D]`، `[H]`، `[U]`) ترجمه نمی‌شوند. اسناد تاریخی (ADRها و CHANGELOG) به‌عنوان سابقه می‌مانند و ترجمه یا بازنویسی نمی‌شوند. سندهای تولیدشده (`docs/generated/`) فقط انگلیسی هستند چون از کد ساخته می‌شوند.

راهنمای ورود برای عامل‌ها و مهندسان: [../AGENTS.md](../AGENTS.md).

</div>
