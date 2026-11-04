<!-- i18n-source: 19-onboarding.md sha256:e917ea704b0f -->
<div dir="rtl" lang="fa">

# ۱۹ — آشناسازی مهندس جدید

یک مهندس جدید چگونه از صفر به تغییر بازبینی‌شده‌ای می‌رسد که در تولید اجرا می‌شود. هر گام سندی را که جزئیات را دارد و بررسی‌ای را که ثابت می‌کند گام انجام شده نام می‌برد، تا مربی بدون پرسیدن بفهمد فرد کجاست. رانبوک‌ها برای وقتی که کارها خراب می‌شوند در [۲۰ — رانبوک‌ها](../20-runbooks.md) است.

## روز ۱ — دسترسی و نقشه

| انجام بده | انجام‌شده وقتی |
|---|---|
| GitHub: به `mjsn800403/KGKG` با **Write** اضافه شو (برای مدیران انتشار Maintain) | `gh api repos/mjsn800403/KGKG --jq .permissions.push` مقدار `true` چاپ کند |
| سرور: کلید SSH خودت روی میزبان تولید (دسترسی root را یک maintainer می‌دهد، هرگز مشترک نیست) | `ssh root@<host> 'ops/deploy/deploy.sh --status'` از `/opt/KGKG_work` |
| به ترتیب بخوان: [README](README.md) ← [01 نمای کلی](01-overview.md) ← [02 معماری](02-architecture.md) ← [06 RBAC](06-permissions-rbac.md) ← [11 عملیات](../11-operations-deployment.md) | بتوانی بگویی دفترچهٔ یک خودرو کجاست، چه کسی می‌بیند و یک تغییر چگونه به تولید می‌رسد |
| [CONTRIBUTING](../CONTRIBUTING.md) و [ADRها](adr/README.md) را بخوان | بدانی چرا فقط یک انسان promote می‌کند (ADR-0004) |
| اگر on-call خواهی بود به گیرندگان هشدار بپیوند (`KG_ALERT_PHONES`) | اجرای آزمایشی watchdog شمارهٔ تو را فهرست کند |

## هفتهٔ ۱ — اجرا کن، سپس تغییر بده

۱. **تست‌ها را اجرا کن.** بک‌اند: `KG_RL_DISABLE=1 .venv/bin/python manage.py test api` (PostgreSQL، روی یک پایگاه گیت — هرگز پایگاه تولید). فرانت‌اند: `npm test` در `kg_frontend/`. هر دو باید پیش از لمس چیزی سبز باشند.
۲. **پشتهٔ QA را بالا بیاور** و سفرهای مرورگر را اجرا کن: `qa/stack.sh up <ref>` سپس `qa/run_e2e.sh`.
۳. **یک issue با برچسب `good first issue` یا `priority:normal`** از milestone فعلی در GitHub برگزین. هر pull request باید به یک issue ارجاع دهد — `ops/governance/check_traceability.py` وگرنه CI را شکست می‌دهد.
۴. **تغییر را تست‌محور** روی شاخه‌ای از `work` بساز، pull request به `work` باز کن، یک بازبینی بگیر.
۵. **با نظارت یک maintainer منتشرش کن:** کامیت در `/opt/KGKG_work` روی `work` می‌نشیند، سپس `bash ops/deploy/deploy.sh work` (گیت ← staging ← promote ← smoke، rollback خودکار). هرگز `/opt/KGKG` را دستی ویرایش نکن.
۶. **مستندات را در همان کامیت به‌روز کن** و تاریخ `reviewed` سند را در `docs/OWNERS.toml` جابه‌جا کن — CI هر دو را اجباری می‌کند.

## ماه ۱ — مالک یک حوزه شو

| حوزه | شروع از | بررسی مالکیت |
|---|---|---|
| pipeline داده خودرو (دانلود ← parse ← PostgreSQL ← RAG ← diag) | [15 شمای خودرو](../15-vehicle-schema.md)، [11.4](../11-operations-deployment.md) | یک خودرو را از ابتدا تا انتها اضافه کن و همهٔ مراحل از جمله `pgcar` را ببین |
| دستیار هوش مصنوعی و بازیابی | [08](08-ai-assistant-rag.md)، [17 ارزیابی](../17-evaluation.md) | ارزیابی مجموعهٔ طلایی را اجرا و اعداد منتشرشده را بازتولید کن |
| میزکار پشتیبانی و پایگاه دانش | `audit-evidence/16-improvement-programme/` | یک تیکت را حل و به مقالهٔ پایگاه دانش ارتقا بده |
| عملیات | [11](../11-operations-deployment.md)، [18](../18-security-hardening.md)، [20 رانبوک‌ها](../20-runbooks.md) | روی staging یک rollback و یک بررسی بازیابی انجام بده |

## دانش چگونه در جریان می‌ماند

* **مستندات به‌عنوان کد** (ADR-0006): تغییر رفتار و مستندات آن با هم منتشر می‌شوند.
* **مالکان مشخص و تاریخ‌های بازبینی** برای هر سند (`docs/OWNERS.toml`، با `ops/governance/check_docs_freshness.py` اجباری می‌شود).
* **تصمیم‌ها** در ADR می‌روند؛ **رخدادها** postmortem بدون سرزنش زیر `audit-evidence/11-operations-and-support/` و یک تست رگرسیون می‌گیرند.
* **دانش مشتری**: تیکت حل‌شده‌ای که دیگران هم با آن روبه‌رو می‌شوند به مقالهٔ پایگاه دانش با مالک و فاصلهٔ بازبینی خودش تبدیل می‌شود.
* **تحویل**: پیش از ترک یک حوزه، فرد رانبوک آن را روی staging با مالک بعدی مرور می‌کند و مالکیت را در `OWNERS.toml` جابه‌جا می‌کند.

</div>
