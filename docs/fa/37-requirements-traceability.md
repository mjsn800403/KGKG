<!-- i18n-source: 37-requirements-traceability.md sha256:0ec0b189137d -->
<div dir="rtl" lang="fa">

# ۳۷ — ردیابی نیازمندی تا پیاده‌سازی

هر نیازمندی [00-srs.md](../00-srs.md) (از FR-01 تا FR-30 و NFR-01 تا NFR-14) را به کدی که پیاده‌اش می‌کند (route، ماژول، مدل) و به تست‌هایی که SRS به‌عنوان راستی‌آزمایی نام برده نگاشت می‌کند. ستون *راستی‌آزمایی* از SRS کپی شده و **توسط `ops/governance/check_srs_trace.py` بررسی می‌شود**: هر فایل تستِ نام‌برده در آنجا باید وجود داشته باشد و هر شناسهٔ نیازمندی SRS باید در این جدول باشد. این بررسی فقط ثابت می‌کند تست‌های نام‌برده **وجود دارند**، نه اینکه موفق‌اند یا نیازمندی را پوشش می‌دهند؛ موفقیت یا شکست نتیجهٔ CI روی کامیت انتشار است. نسخهٔ `origin/work` در `07f3ab5` **[C]**. نسخهٔ انگلیسی: [../37-requirements-traceability.md](../37-requirements-traceability.md). قواعد امنیتی/کسب‌وکاری `RQ-xx`: `audit-evidence/01-requirements-and-traceability/TRACEABILITY.md` (شواهد تاریخ‌دار ممیزی).

واژگان وضعیت: **پیاده‌شده** = کد و routeها وجود دارند؛ **پیاده‌شده، وابسته به پیکربندی** = وجود دارد اما مگر با کلید خاص خاموش است؛ **جزئی** = پیاده‌شده با شکاف ذکرشده؛ **دستی** = با روال راستی‌آزمایی می‌شود نه تست.

## ۳۷٫۱ نیازمندی‌های عملکردی

| شناسه | نیازمندی (کوتاه) | پیاده‌سازی (route ← ماژول ← مدل) | راستی‌آزمایی (SRS) | وضعیت |
|---|---|---|---|---|
| FR-01 | درخواست خرید | `POST api/purchase-request/` ← `views.purchase_request_view` ← `PurchaseRequest` | `test_purchase_flow.py` | پیاده‌شده |
| FR-02 | درخواست ← شرکت، اعطاها، کاربران اولیه | `api/admin/requests/…`، `api/admin/companies/…`، `api/admin/users/…` ← `portal.admin_*` ← `Company`، `CompanyCarAccess`، `PortalUser`، `UserCarAccess`، `InviteToken` | `test_purchase_flow.py`، RQ-11 | پیاده‌شده |
| FR-03 | گذرواژه + OTP پیامکی، بازیابی با پیامک | `api/auth/login|verify-otp|resend-otp|recover/*` ← `portal.*`، `portal_auth.py`، `ratelimit.py` ← `OtpChallenge`، `OtpEvent`، `KnownDevice`، `AuthToken` | `test_qa_auth.py`، `test_recover.py`، `test_sms_bodies.py`، `auth.spec.js`، RQ-04 | پیاده‌شده |
| FR-04 | یک نشست زنده، ابطال سمت سرور | `api/auth/logout/`، `api/auth/me/` ← `portal.*`، `portal_auth.py` ← `AuthToken` (هش‌شده) | `session.spec.js`، `test_security.py`، RQ-05 | پیاده‌شده |
| FR-05 | فهرست فقط خودروها/لایه‌های مجاز | `api/auth/fleet/`، `{brand}/{year}/{model}/` ← `portal.fleet_view`، `views.car_view`، `access.py`، `listing.py` ← `CompanyCarAccess`، `UserCarAccess` | `test_qa_access.py`، `test_vehiclefilter.py`، `tests.py`، RQ-01 | پیاده‌شده |
| FR-06 | نمایش درخت/صفحات دفترچه؛ تصاویر فقط برای مجازها | `views.car_view`، `api/media-auth/` (`auth_request` در nginx) ← `cardb.py`، `cardb_pg.py`، `mediaauth.py` | `test_qa_catalog.py`، `test_qa_mediaauth_paths.py`، `media.spec.js`، RQ-03 | پیاده‌شده (موتور مخزن محتوا طبق [23](../23-data-layer.md)) |
| FR-07 | جست‌وجوی فارسی/انگلیسی درون یک خودرو | `api/search/` ← `views.search_view` ← `rag/service.search`، `rag/retrieve.py` | `rag/test_fts.py`، `rag/test_retrieve.py`، `rag/test_service_paths.py` | پیاده‌شده |
| FR-08 | پاسخ فارسی پایه‌دار، پیوندهای قابل‌حل و مجاز | `POST /api/chat` (Next) ← `api/assist/` ← `rag/*`؛ `chatPrompt.js` | `rag/test_*.py`، `test_qa_content_guard.py`، `chatPrompt.test.mjs`، RQ-09 | پیاده‌شده؛ بخش‌های اختیاری طبق [30](30-ai-assistant-deep-dive.md) بخش ۳۰٫۱۲ |
| FR-09 | موتور قطعی DTC/علامت ابتدا | `api/diagnose/` ← `rag/diag.py`، `diag_build.py` | `test_qa_content_guard.py`، `rag/test_service_paths.py` | پیاده‌شده هرجا sidecar هست **[U]** |
| FR-10 | شمارهٔ قطعه، ابزار مخصوص، زمان کار در صورت خرید | `parts.py`، `sst.py`، `labortimes.py`، `assist_lookup.py`؛ `api/admin/parts/` | `tests_parts.py`، `test_exports.py`، `test_qa_access.py` | پیاده‌شده |
| FR-11 | نمودار سازمانی، دعوت/ساخت کاربر، تفویض ≤ دسترسی خود | `api/org/*`، `api/invite/<token>/` ← `orggraph_api.py`، `orggraph.py`، `team.py` ← `OrgGraph`، `OrgNode`، `NodePermission`، `NodeInvite` | `test_orggraph.py`، `test_qa_orggraph_authz.py`، `test_qa_orggraph_input.py`، `test_team.py`، RQ-01 | پیاده‌شده |
| FR-12 | تحلیل شاخه و PDF فارسی | `api/team/analytics|report|insights/` ← `team.py`، `reporting.py`، `recommend.py` | `test_team.py`، `test_orgreach.py` | پیاده‌شده |
| FR-13 | درخواست‌های مدیر با وضعیت زنده | `api/company/requests/…`، `api/admin/company-requests/` ← `requests_api.py`، `events.py` ← `CompanyRequest`، `TicketMessage`، `TicketRead`، `Event` | `test_qa_requests.py`، `test_events.py` | پیاده‌شده |
| FR-14 | پیشنهاد فقط از خودروهای قابل‌گشایش | `api/recommendations/` ← `recommend.py` | `test_recommend.py`، `rag/test_store_ro.py` | پیاده‌شده |
| FR-15 | کنسول ادمین | `api/admin/*` ← `adminops.py`، `portal.py`، `monitoring.py` | `test_adminops.py`، `test_ops.py`، `test_admin_token_scope.py` | پیاده‌شده |
| FR-16 | ورود محتوای قابل‌ازسرگیری بدون مسدودکردن سرویس | `api/admin/pipeline/`، `ops/hostjobs` ← `pipeline.py`، `ingest.py`، `parse_worker.py`، `tis_crawler.py`، `partsouq_*.py` ← `ZipPackage`، `ProcessingJob`، `PipelineSettings` | `test_pipeline.py`، `test_pipeline_ext.py`، `test_tisparse.py`، `test_partsouq_build.py` | پیاده‌شده |
| FR-17 | لاگ مبادلات/فعالیت، محدود به شرکت | `api/auth/chat-log/`، `api/team/chat-logs/`، `api/admin/chat-logs/`، `api/activity/` ← `chatlog.py` ← `ChatLog`، `ActivityLog` | `test_chatlog.py`، `test_events.py` | پیاده‌شده |
| FR-18 | پرچم ویژگی شامل A/B | `api/auth/flags/`، `api/admin/flags/…` ← `flags.py` ← `FeatureFlag` | `test_flags.py` | پیاده‌شده |
| FR-19 | مشخصات ساختاریافته خودرو | `api/admin/vehicle-specs/` ← `adminops.py`، `frm.py` ← `VehicleSpec` | `test_vehicleschema.py`، `test_adminops.py` | پیاده‌شده |
| FR-20 | هشدار پیامکی بدون تکرار | `alert_rules.py`، `monitoring.py`، `ops/observability/watchdog.py` ← `SystemAlert`، `NotificationLog` | `test_alert_probe.py`، `test_disk_guard_resolve.py`، `ops/observability/test_*.py`، `--selftest` مربوط به watchdog | پیاده‌شده |
| FR-21 | چت پشتیبانی ناشناس | `api/support-chat/*` (status، threads، messages، contact، reopen، csat) ← `support_chat/views_public.py`، `tokens.py`، `limits.py`، `throttle.py`، `lifecycle.py`، `config.py` ← `SupportThread`، `SupportMessage`، `SupportRating` | `test_public_api.py`، `test_lifecycle.py`، `test_tokens.py`، `test_security_sweep.py`، `test_kill_switch.py`، `test_throttling.py`، `support-chat.spec.js` | پیاده‌شده، وابسته به پیکربندی (`KG_SUPPORT_CHAT_ENABLED`)؛ وضعیت تولید **[U]** |
| FR-22 | صندوق ورودی کارکنان و RBAC پشتیبانی | `api/admin/support-chat/*` ← `views_admin.py`، `views_admin_inbox.py`، `views_status.py`، `rbac.py`، `permissions.py` ← `SupportPresence` (به‌علاوهٔ ذخیرهٔ نقش پس از یک migration بعدی **[U]**) | `test_inbox_api.py`، `test_staff_actions.py`، `test_rbac.py`، `test_rbac_api.py`، `test_support_roles_command.py` | پیاده‌شده؛ RBAC به‌صورت پیش‌فرض خاموش |
| FR-23 | صندوق خروجی اعلان | `notifications/service.py`، `worker.py`، `providers.py`، `config.py`؛ `manage.py process_outbox`؛ `ops/outbox/` ← `NotificationOutbox` | `notifications/test_service.py`، `notifications/test_worker.py`، `notifications/test_providers.py`، `notifications/test_privacy_and_concurrency.py`، `notifications/test_command.py` | پیاده‌شده، وابسته به پیکربندی (کانال‌ها پیش‌فرض `off`)؛ رسید تحویل مشاهده نمی‌شود |
| FR-24 | پایگاه دانش | `api/kb/*`، `api/admin/kb/*`، `api/admin/company-requests/<id>/promote-to-article/` ← `knowledge.py` ← `KnowledgeArticle`، `KnowledgeRevision`، `KbSearchLog` | `test_knowledge.py`، `test_helpdesk_desk.py` | پیاده‌شده |
| FR-25 | سهمیهٔ دستیار بر اساس طرح | `api/auth/ai-usage/` ← `quota.py` (`PLAN_AI`) ← `ActivityLog` (ردیف‌های `ask_assistant`)، `Company.plan`؛ در `/api/chat` بررسی می‌شود | `test_qa_access.py`، `pricing.test.mjs` | پیاده‌شده؛ **ماژول تست اختصاصی ندارد** (فقط مسیرهای سهمیه درون تست‌های دسترسی) |
| FR-26 | اهداف SLA میزکار و بازخورد محصول | `sla.py` (بالا ۲ ساعت/۸ ساعت، عادی ۸/۴۸، پایین ۲۴/۱۲۰، ساعت تقویمی)، `feedback.py` (`api/feedback/submit/`، `api/admin/feedback/`)، `support_metrics.py` ← `CompanyRequest`، `Feedback` | `test_helpdesk.py`، `test_helpdesk_desk.py` | پیاده‌شده |
| FR-27 | چک‌لیست کشف ویژگی | `api/auth/onboarding/` ← `onboarding.py`، `access.user_ai_eligible` ← `ActivityLog` | `test_onboarding.py`، `onboarding.test.mjs` | پیاده‌شده |
| FR-28 | محافظ محتوا (shield) و سقف خواندن | `shield.py` (`api/shield/key/`، `KG_SHIELD`، `KG_SHIELD_SECRET`)، `contentguard.py` | `test_shield.py`، `test_contentguard.py` | پیاده‌شده، وابسته به پیکربندی (shield)؛ سقف‌ها همیشه روشن |
| FR-29 | دروازه‌های ابزار ادمین | `grafanaauth.py` (`api/admin/grafana-ticket/`، `api/grafana-auth/`)، `vncauth.py` (`api/vnc-auth/`)، `auth_request` در nginx | **(دستی)** | پیاده‌شده؛ **تست خودکاری یافت نشد** |
| FR-30 | بینش رفتار دستیار | `behavior.py`، `insights.py` (`api/admin/insights/*`، `api/auth/chat-feedback/`) ← `ChatLog` | `test_routes_and_independence.py` (فقط پوشش route) | پیاده‌شده؛ منطق رفتار تست اختصاصی ندارد **[U]** |

### بیانیهٔ پوشش

FR-21 تا FR-30 در ۲۰۲۶‑۱۱‑۰۴ از روی کد راستی‌آزمایی‌شده به SRS افزوده شدند (از پیش وجود داشتند؛ SRS نامی از آن‌ها نبرده بود). «فایل تست وجود دارد» در ستون *راستی‌آزمایی* یعنی فایل موجود است و برای آن رفتار نام‌گذاری شده؛ **نه** اینکه هر قاعدهٔ نیازمندی assert شده یا تست موفق است. ردیف‌های دارای عبارت *ماژول تست اختصاصی ندارد* (FR-25، FR-30) یا *(دستی)* (FR-29) شکاف‌های شناخته‌شدهٔ راستی‌آزمایی‌اند. موفقیت یا شکست هر نیازمندی نتیجهٔ CI روی کامیت انتشار است.

## ۳۷٫۲ نیازمندی‌های کیفیتی

| شناسه | نیازمندی (کوتاه) | محل تحقق | راستی‌آزمایی (SRS) | وضعیت |
|---|---|---|---|---|
| NFR-01 | انزوای مستأجر و استحقاق | `access.py`، `mediaauth.py`، `allowed_cars` در بازیابی | RQ-01/02/03/07 (TRACEABILITY.md) | پیاده‌شده |
| NFR-02 | ورودی مخرب هرگز ۵xx نمی‌دهد | `nulguard.py`، اعتبارسنجی viewها | `test_qa_*`، `test_adminops.py`، `qa/dast/` | پیاده‌شده؛ عدد نتیجهٔ DAST در این مخزن نیست **[U]** |
| NFR-03 | توکن ادمین فقط از loopback؛ انقضای نشست | `admin_auth.py` | `test_admin_token_scope.py`، `test_security.py` | پیاده‌شده |
| NFR-04 | هیچ آسیب‌پذیری شناخته‌شدهٔ high/critical یا رازی منتشر نمی‌شود | گیت‌های CI | `ci.yml` بخش‌های security و images، RQ-15 | با CI اجباری |
| NFR-05 | آستانه‌های کارایی | `qa/perf/k6-kgkg.js` | آستانه‌های k6، `audit-evidence/06-…/PERFORMANCE_REPORT.md` | آستانه‌ها تعریف شده؛ نتیجهٔ آخرین اجرا **[U]** |
| NFR-06 | تشخیص، watchdog، دیپلوی بدون وقفه، rollback | `alert_rules.py`، `watchdog.py`، `deploy.sh` | probeهای blackbox، selftest مربوط به watchdog، ADR-0003 | پیاده‌شده؛ وضعیت timer میزبان **[U]** |
| NFR-07 | قابلیت بازیابی | پشتیبان‌ها ([34](34-data-model-reference.md) بخش ۳۴٫۷) | سند ۱۱ بخش ۱۱٫۶ (تمرین بازیابی دستی) | **اثبات نشده** (R1) |
| NFR-08 | دسترس‌پذیری (WCAG 2.1 A/AA) | فرانت‌اند | `a11y.spec.js`، RQ-14 | فقط QA شبانه |
| NFR-09 | فارسی/RTL/جلالی | فرانت‌اند، `team.py` | `faTerms*.test.mjs`، `test_team.py` | پیاده‌شده |
| NFR-10 | پوشش کم نمی‌شود؛ مجوز با mutation تست می‌شود | `coverage_min`، `qa/mutation/run.sh` | کف CI | کف ۵۹٪؛ mutation در صورت نیاز |
| NFR-11 | مستندات همراه کد؛ مطابقت spec API با routeها | job حاکمیت، `docs/openapi.yaml` | `test_openapi_routes.py` | با CI اجباری |
| NFR-12 | کنترل انتشار توسط انسان | `kg-deploy-gate`، `kgkg-promote`، ADR-0004 | `test_gate_roles.sh`، `test_promote.sh` | با تست اجباری |
| NFR-13 | غیرتولید هرگز در داده تولید نمی‌نویسد | بازهدایت پایگاه بازخورد، پاک‌ساز | `rag/test_feedback_isolation.py`، `test_qa_fixtures.py`، RQ-12 | **جزئی**: staging `kgkg_vec` تولید را خوانده (R5) |
| NFR-14 | وفاداری AI | گیت‌های دامنه، پاک‌ساز پیوند | `qa/eval/`، `rag/test_service_paths.py` | پیاده‌شده؛ گیت کیفیت خودکار در CI نیست ([32](32-testing-and-qa.md) بخش ۳۲٫۱۳) |

## ۳۷٫۳ استفاده و نگهداری ماتریس

۱. تغییر رفتار ← ردیف SRS، ردیف این ماتریس و تست‌های نام‌برده را در همان PR تغییر دهید (پروتکل مستندات، [AGENTS.md](../AGENTS.md) بخش ۵).
۲. `python3 ops/governance/check_srs_trace.py` شکست می‌خورد اگر تستی که SRS نام برده وجود نداشته باشد یا شناسهٔ نیازمندی SRS اینجا نباشد.
۳. نیازمندی فقط وقتی **برآورده** است که راستی‌آزمایی آن روی کامیت انتشار اجرا شده باشد (SRS بخش ۷)؛ این ماتریس چنین ادعایی نمی‌کند.

</div>
