<!-- i18n-source: 40-documentation-access-guide.md sha256:ae89c634edef -->
<div dir="rtl" lang="fa">

# ۴۰ — راهنمای دسترسی به مستندات

نسخهٔ انگلیسی: [../40-documentation-access-guide.md](../40-documentation-access-guide.md). گیت‌هاب تنها منبع مرجع است؛ بستهٔ قابل دانلود یک عکس‌برداری بازتولیدپذیر از آن است.
نشانی پایه: `https://github.com/mjsn800403/KGKG/blob/work/` (شاخهٔ `work`). برای نمای ثابت، `blob/work` را با `blob/<sha>` عوض کنید.

## ۴۰٫۱ نقاط ورود

| هدف | پیوند |
|---|---|
| فهرست انگلیسی | [docs/README.md](https://github.com/mjsn800403/KGKG/blob/work/docs/README.md) |
| فهرست فارسی | [docs/fa/README.md](https://github.com/mjsn800403/KGKG/blob/work/docs/fa/README.md) |
| نقطهٔ ورود عامل/مهندس جدید | [docs/AGENTS.md](https://github.com/mjsn800403/KGKG/blob/work/docs/AGENTS.md) |
| ماتریس وضعیت (آنچه امروز واقعی است) | [docs/38-implementation-status-matrix.md](https://github.com/mjsn800403/KGKG/blob/work/docs/38-implementation-status-matrix.md) |
| ادعاهای امن بیرونی | [docs/39-evaluation-evidence-guide.md](https://github.com/mjsn800403/KGKG/blob/work/docs/39-evaluation-evidence-guide.md) |

## ۴۰٫۲ نقشهٔ پوشه‌ها بر اساس دسته

| دسته | انگلیسی | همتای فارسی |
|---|---|---|
| SRS و نیازمندی‌ها | [00-srs](https://github.com/mjsn800403/KGKG/blob/work/docs/00-srs.md)، [37-requirements-traceability](https://github.com/mjsn800403/KGKG/blob/work/docs/37-requirements-traceability.md) | `docs/fa/00-srs.md`، `docs/fa/37-…` |
| معماری و طراحی | [02-architecture](https://github.com/mjsn800403/KGKG/blob/work/docs/02-architecture.md)، [33-system-design](https://github.com/mjsn800403/KGKG/blob/work/docs/33-system-design.md)، [01-overview](https://github.com/mjsn800403/KGKG/blob/work/docs/01-overview.md)، [04-backend-reference](https://github.com/mjsn800403/KGKG/blob/work/docs/04-backend-reference.md)، [07-frontend](https://github.com/mjsn800403/KGKG/blob/work/docs/07-frontend.md)، [09-realtime-sse](https://github.com/mjsn800403/KGKG/blob/work/docs/09-realtime-sse.md) | همان نام فایل زیر `docs/fa/` |
| دستیار هوشمند و RAG | [30-ai-assistant-deep-dive](https://github.com/mjsn800403/KGKG/blob/work/docs/30-ai-assistant-deep-dive.md)، [08-ai-assistant-rag](https://github.com/mjsn800403/KGKG/blob/work/docs/08-ai-assistant-rag.md)، [17-evaluation](https://github.com/mjsn800403/KGKG/blob/work/docs/17-evaluation.md) | همان |
| پشتیبانی و ارتباطات | [35-support-system](https://github.com/mjsn800403/KGKG/blob/work/docs/35-support-system.md)، [22-support-chat](https://github.com/mjsn800403/KGKG/blob/work/docs/22-support-chat.md) | همان |
| پایگاه‌داده و schemaها | [34-data-model-reference](https://github.com/mjsn800403/KGKG/blob/work/docs/34-data-model-reference.md)، [23-data-layer](https://github.com/mjsn800403/KGKG/blob/work/docs/23-data-layer.md)، [03-data-model](https://github.com/mjsn800403/KGKG/blob/work/docs/03-data-model.md)، [15-vehicle-schema](https://github.com/mjsn800403/KGKG/blob/work/docs/15-vehicle-schema.md)، تولیدشدهٔ [schema](https://github.com/mjsn800403/KGKG/blob/work/docs/generated/schema.md) | همان (فایل‌های تولیدشده فقط انگلیسی‌اند) |
| API | [05-api-reference](https://github.com/mjsn800403/KGKG/blob/work/docs/05-api-reference.md)، تولیدشدهٔ [routes](https://github.com/mjsn800403/KGKG/blob/work/docs/generated/routes.md)، [openapi.yaml](https://github.com/mjsn800403/KGKG/blob/work/docs/openapi.yaml) | `docs/fa/05-…` |
| آزمون، QA، E2E، کارایی | [32-testing-and-qa](https://github.com/mjsn800403/KGKG/blob/work/docs/32-testing-and-qa.md)، [17-evaluation](https://github.com/mjsn800403/KGKG/blob/work/docs/17-evaluation.md) | همان |
| امنیت | [12-security](https://github.com/mjsn800403/KGKG/blob/work/docs/12-security.md)، [18-security-hardening](https://github.com/mjsn800403/KGKG/blob/work/docs/18-security-hardening.md)، [21-csrf-exempt-views](https://github.com/mjsn800403/KGKG/blob/work/docs/21-csrf-exempt-views.md)، [26-auth-and-sessions](https://github.com/mjsn800403/KGKG/blob/work/docs/26-auth-and-sessions.md)، [06-permissions-rbac](https://github.com/mjsn800403/KGKG/blob/work/docs/06-permissions-rbac.md) | همان |
| CI/CD و DevOps | [36-cicd-and-deployment](https://github.com/mjsn800403/KGKG/blob/work/docs/36-cicd-and-deployment.md)، [11-operations-deployment](https://github.com/mjsn800403/KGKG/blob/work/docs/11-operations-deployment.md)، [28-team-workflow](https://github.com/mjsn800403/KGKG/blob/work/docs/28-team-workflow.md) | همان |
| زیرساخت، پایش، عملیات | [25-ops-inventory](https://github.com/mjsn800403/KGKG/blob/work/docs/25-ops-inventory.md)، [31-ops-files-reference](https://github.com/mjsn800403/KGKG/blob/work/docs/31-ops-files-reference.md)، [20-runbooks](https://github.com/mjsn800403/KGKG/blob/work/docs/20-runbooks.md)، [29-environment-reference](https://github.com/mjsn800403/KGKG/blob/work/docs/29-environment-reference.md) | همان |
| ریسک‌ها، تصمیم‌ها، شواهد | [27-open-risks-and-decisions](https://github.com/mjsn800403/KGKG/blob/work/docs/27-open-risks-and-decisions.md)، [adr/](https://github.com/mjsn800403/KGKG/tree/work/docs/adr)، [38](https://github.com/mjsn800403/KGKG/blob/work/docs/38-implementation-status-matrix.md)، [39](https://github.com/mjsn800403/KGKG/blob/work/docs/39-evaluation-evidence-guide.md)، [CHANGELOG](https://github.com/mjsn800403/KGKG/blob/work/docs/CHANGELOG.md) | ۳۸ و ۳۹ همتای فارسی دارند |
| مراجع تولیدشده | [generated/](https://github.com/mjsn800403/KGKG/tree/work/docs/generated): `inventory.md`، `schema.md`، `routes.md` | — |
| اسناد فارسی | [docs/fa/](https://github.com/mjsn800403/KGKG/tree/work/docs/fa) | — |

## ۴۰٫۳ کدام سند برای کدام گزارش

| نیاز گزارش‌دهی | استفاده |
|---|---|
| «سامانه چه می‌کند و آیا زنده است؟» | ۳۸ و سپس ۳۹ |
| نیازمندی‌های رسمی و اثبات پیاده‌سازی آن‌ها | ۰۰، ۳۷ |
| معماری فنی برای ارزیابان | ۰۲، ۳۳، ۳۴ |
| کیفیت هوش مصنوعی، محدودیت‌ها، روش ارزیابی | ۳۰، ۱۷، ۳۹ بخش پ |
| وضعیت امنیتی | ۱۲، ۱۸، ۳۹ بخش چ |
| فرایند و کنترل‌های تحویل | ۳۶، ۱۱ |
| فهرست صادقانهٔ شکاف‌ها و ریسک‌ها | ۳۸ §۳۸٫۷، ۲۷ |
| آشناسازی مهندس جدید | `docs/AGENTS.md`، ۱۹ |

## ۴۰٫۴ بستهٔ قابل دانلود

`ops/governance/build_docs_package.py` فایل `kgkg-docs-<commit-date>-<sha7>.zip` را از گیت می‌سازد (همهٔ اسناد انگلیسی و فارسی، هر دو فهرست، مراجع تولیدشده، ADRها، `openapi.yaml`، `OWNERS.toml`، `i18n.toml`، `AGENTS.md` ریشه، `MANIFEST.json` با SHA-256 هر فایل، و `README-PACKAGE.txt`). یک کامیت همیشه همان بایت‌ها را تولید می‌کند. کار `governance` در CI آن را می‌سازد و با نام `kgkg-docs-package` به‌عنوان artifact اجرا بارگذاری می‌کند (نگهداری ۹۰ روز)؛ اگر الگوی شبیه راز بیابد ساخت را رد می‌کند. هیچ محتوای پایگاه‌داده، اعتبارنامه یا داده‌ٔ مشتری در آن نیست.
بازسازی محلی: `python3 ops/governance/build_docs_package.py --commit <sha>`.

</div>
