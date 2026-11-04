<!-- i18n-source: 28-team-workflow.md sha256:428b36620877 -->
<div dir="rtl" lang="fa">

# ۲۸ — روال تیم: GitHub، Jira، Slack، Trello

کار چگونه پیگیری و تحویل می‌شود. مخزن سابقهٔ مهندسی است؛ این سند قراردادهایی را ثبت می‌کند که بیرون از آن وجود دارند، تا مهندس یا عامل جدید مجبور نباشد آن‌ها را از گفتگو بازسازی کند. منابع: Slack ‏`#kg-dev`، `#kg-decisions`، `#kg-releases` و Jira ‏KGTEC خوانده‌شده در ۲۰۲۶‑۱۱‑۰۴ [D]؛ قواعد شاخه و PR از `.github/` و `docs/11` [C]. نقش‌ها و در دسترس‌بودن افراد جز آنچه گفته شده **[U]** است.

## ۲۸٫۱ افراد و نقش‌ها [D]

- مدیر محصول و مالک تصمیم/پذیرش: GitHub ‏`mjsn800403` (برچسب مالک `owner-pm`).
- مهندسی: Ali Sartipi (GitHub ‏`alistp27`، برچسب `owner-ali`). `alistp27` دسترسی push + triage دارد، نه admin؛ نمی‌تواند شاخه‌های با الگوی محافظت‌شده را حذف کند.
- هر دو maintainer مالک هر سند هستند (`docs/OWNERS.toml`).

## ۲۸٫۲ سیستم‌ها و نقش‌هایشان

| سیستم | نقش | نکات |
|---|---|---|
| GitHub ‏`mjsn800403/KGKG` (عمومی) | سابقهٔ مهندسی: کد، PR، issue، CI | شاخهٔ پیش‌فرض `main`؛ شاخهٔ یکپارچه‌سازی `work`؛ هر دو محافظت‌شده (PR الزامی، ۰ تأیید، چک‌های backend/frontend/security/images/governance؛ بدون force-push) [D ‏۲۰۲۶‑۱۱‑۰۲، پیش از اتکا تنظیمات را دوباره ببینید] |
| پروژهٔ Jira با نام `KGTEC` (سایت `mohammad-javad-salimi-s-workspace`) | منبع حقیقت وضعیت کار | نوع پروژهٔ Business: To Do / In Progress / Done، بدون بُرد یا sprint. issueهای GitHub را آینه می‌کند. KGTEC-1..24 در ۲۰۲۶‑۱۱‑۰۴ وجود داشتند |
| بُرد Trello با نام «KGtechvault Delivery» | آینهٔ بصری فقط‌خواندنی Jira | کارت‌ها با عنوان `KGTEC-n`؛ عقب می‌ماند (KGTEC-22..24 در ۲۰۲۶‑۱۱‑۰۴ کارت نداشتند) |
| Slack ‏`#kg-dev` | ارتباط، خلاصهٔ reconcile روزانه، یادداشت‌های دیپلوی از Ali | |
| Slack ‏`#kg-releases` | یک پست برای هر انتشار: نسخه، SHA، کلیدهای Jira، نتیجهٔ staging، چه کسی promote کرد | متن هدف کانال در ۲۰۲۶‑۱۱‑۰۲ کهنه بود |
| Slack ‏`#kg-decisions` | یک رشته برای هر تصمیم: پرسش، گزینه‌ها، توصیه، تصمیم + کلید Jira | آن زمان باز: KGTEC-4، 5، 6 |
| Confluence | **خالی** (فقط قالب‌ها)؛ استفاده نمی‌شود | |

## ۲۸٫۳ قراردادها

- برچسب‌های Jira: مالک `owner-pm` / `owner-ali`؛ پیوند GitHub به‌صورت `gh-<issue>`؛ پیوند PR به‌صورت `gh-pr-<n>`؛ epicها `epic-*`؛ وضعیت `in-review`، `blocked`، `needs-decision`، `needs-approval`؛ حوزه `area-ops`، `area-security`.
- شاخهٔ `KGTEC-<n>-title` یا `type/KGTEC-n-title`؛ PR به `work`؛ عنوان/متن به کلید Jira و یک issue گیت‌هاب ارجاع می‌دهند (`check_traceability.py` ارجاع به issue را اجباری می‌کند). سقف WIP دو مورد برای هر نفر.
- از `refs #N` یا `fixes #N` استفاده کنید: **هیچ‌کدام issue را نمی‌بندد**، چون GitHub فقط هنگام ادغام در شاخهٔ پیش‌فرض (`main`) خودکار می‌بندد و PRها به `work` ادغام می‌شوند. issueها را پس از راستی‌آزمایی تولید دستی ببندید و در PR بگویید. [D ‏Slack ‏۲۰۲۶‑۱۱‑۰۴]
- هر PR: `.github/pull_request_template.md` (ردیابی، چگونه راستی‌آزمایی شد، چک‌لیست شامل `docs/` و ADR).
- انتشارها: CI روی push سبز به `work` stage می‌کند؛ یک انسان `kgkg-promote <sha>` را اجرا می‌کند؛ Ali دیپلوی‌ها را در `#kg-dev` اعلام کرده است.

## ۲۸٫۴ اتوماسیونی که وجود دارد

- وظیفهٔ زمان‌بندی‌شده با نام `kgkg-daily-reconcile` (اپ دسکتاپ Claude، ساعت ۰۹:۰۳ محلی): مقایسهٔ فقط‌خواندنی GitHub، Jira و Trello، یک خلاصه را با برچسب «پیشنهادی، اعمال نشده» در `#kg-dev` می‌گذارد. فقط وقتی اپ دسکتاپ باز است اجرا می‌شود. پیشنهاد جدایی برای نسخهٔ سمت سرور با کمترین امتیاز KGTEC-21 است (تأیید نشده). [D]
- هیچ قاعدهٔ اتوماسیون Jira، اپ GitHub-for-Jira یا یکپارچگی Slack-Jira راستی‌آزمایی نشده **[U]**.
- Dependabot (`.github/dependabot.yml`)، تنظیم پیش‌فرض CodeQL، و push protection برای اسکن راز فعال‌اند [D ‏۲۰۲۶‑۱۱‑۰۲].

## ۲۸٫۵ تصمیم‌های در انتظار (owner-pm) — در سند ۲۷ پیگیری می‌شوند

KGTEC-4 قیمت‌گذاری بین ۲۹ و ۳۰ صندلی؛ KGTEC-5 شاخهٔ checkout تولید و Tunnel در برابر SSH برای CI؛ KGTEC-6 تغییرات میزبان (probeهای معلق، ردیف‌های staging، xrdp)؛ KGTEC-19 آزمون نفوذ مستقل؛ KGTEC-20 ردیف‌های فعالیت بازسازی‌شده؛ KGTEC-16 حذف `rag-db-improvements`؛ KGTEC-18 پشتیبان‌ها (نگهداشت سمت دیگر، escrow رازها؛ گسترش به `kgkg_vec`، GitHub #80).

</div>
