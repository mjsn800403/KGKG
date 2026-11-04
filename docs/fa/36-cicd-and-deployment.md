<!-- i18n-source: 36-cicd-and-deployment.md sha256:e3e2c36cfa9e -->
<div dir="rtl" lang="fa">

# ۳۶ — CI/CD، انتشار و استقرار (از ابتدا تا انتها)

یک تغییر چگونه از شاخه به تولید می‌رسد، چه کنترل‌هایی جلوی آن را می‌گیرند و چگونه بازگردانده می‌شود. منبع: `.github/`، `ops/deploy/`، `ops/docker/`، `ops/security/`، `qa/` در `origin/work` نسخهٔ `07f3ab5` **[C]**. روایت عملیاتی و رانبوک‌ها: [11-operations-deployment.md](../11-operations-deployment.md)، [20-runbooks.md](../20-runbooks.md). اینکه در هر زمان روی میزبان چه چیزی در حال اجراست **[U]** است مگر مشاهدهٔ تاریخ‌دار ذکر شود؛ تولید برای این سند بررسی نشد. نسخهٔ انگلیسی: [../36-cicd-and-deployment.md](../36-cicd-and-deployment.md).

## ۳۶٫۱ شاخه‌ها، حفاظت و pull requestها

- **`work`** شاخهٔ یکپارچه‌سازی است و **`main`** شاخهٔ پیش‌فرض GitHub که از نظر محتوا از `work` عقب است. هر دو محافظت‌شده‌اند. شاخه‌های ویژگی از `origin/work` ساخته و با pull request به `work` ادغام می‌شوند ([AGENTS.md](../AGENTS.md) قاعدهٔ ۱).
- **حفاظت `work`** (خوانده‌شده از API گیت‌هاب در ۲۰۲۶‑۱۱‑۰۴ **[S-GitHub]**): چک‌های الزامی `backend`، `frontend`، `security`، `images`، `governance`؛ pull request الزامی؛ تعداد تأییدکنندهٔ الزامی **۰**؛ بازبینی‌های کهنه رد می‌شوند؛ بازبینی code-owner الزامی نیست؛ `strict` (به‌روزبودن شاخه) **خاموش**؛ قواعد برای ادمین‌ها اعمال نمی‌شود. سبک ادغام در تاریخچه: merge commit.
- **CODEOWNERS** فایل استثناهای بدهی و `gen_inventory.py` را به مالک مخزن می‌فرستد ([28](../28-team-workflow.md)).
- **قالب PR** (`.github/pull_request_template.md`): کلید Jira، issue گیت‌هاب، چه و چرا، *چگونه راستی‌آزمایی شد* (دستور و خروجی)، چک‌لیست (تست پیش از تغییر شکست می‌خورد؛ مستندات به‌روز؛ موجودی بازتولید؛ OpenAPI به‌روز؛ ADR در صورت تصمیم پایدار؛ کفی کم نشده؛ قواعد هشدار پنجره‌دار؛ چیزی نیازمند نصب دستی روی میزبان نیست)، ریسک و بازگشت.
- **گیت ردیابی‌پذیری:** عنوان/متن PR باید به یک issue ارجاع دهد (`ops/governance/check_traceability.py`؛ ارجاع داخل code fence حساب نمی‌شود). PRهای مقصد `work` حتی با `fixes #N` issue را خودکار نمی‌بندند **[D]**.
- **Dependabot** (`.github/dependabot.yml`): PRهای هفتگیِ گروه‌بندی‌شدهٔ minor/patch برای هر اکوسیستم، حداکثر ۳ باز، مقصد `work`؛ هیچ‌چیز نمی‌تواند به تولید برسد.

## ۳۶٫۲ workflowها

| workflow | محرک | jobها |
|---|---|---|
| `.github/workflows/ci.yml` | هر push (همهٔ شاخه‌ها) و هر pull request؛ گروه همزمانی برای هر ref و اجراهای در حال انجام لغو می‌شوند | `backend`، `support-chat-e2e`، `frontend`، `security`، `governance`، `images`، `stage` |
| `.github/workflows/mutation.yml` | دستی (`workflow_dispatch`) | `mutmut` روی ماژول‌های مجوز، سقف ۱۸۰ دقیقه |
| CodeQL | اسکن کد GitHub (Python، JavaScript/TypeScript، Actions) | `Analyze (…)`، `CodeQL` |

کمترین دسترسی: مجوز workflowها `contents: read` است؛ هیچ jobی در مخزن نمی‌نویسد.

### مرجع jobها (هرکدام چه چیزی را ثابت می‌کند) — جزئیات در [32-testing-and-qa.md](32-testing-and-qa.md)

| job | گام‌های کلیدی | شکست یعنی |
|---|---|---|
| `backend` (سرویس PostgreSQL 16، timeout ‏۳۰ دقیقه) | کتابخانه‌های سیستمی WeasyPrint؛ `manage.py check`؛ `makemigrations --check`؛ مجموعهٔ کامل با پوشش شاخه و `--shuffle`؛ کف پوشش `ops/deploy/coverage_min`؛ artifact با نام `backend-test-reports-<sha>` | شکست تست، migration جاافتاده، پوشش زیر کف |
| `support-chat-e2e` | پشتهٔ یک‌بارمصرف؛ بررسی منفی که نبودن پشته شکست بخورد؛ spec مربوط به Playwright؛ `support_chat_guard.py`؛ artifact رکورد | رگرسیون چت یا اجرای تو‌خالی |
| `frontend` | `npm ci`؛ ESLint با کف هشدار `ops/deploy/lint_max_warnings`؛ `node --test`؛ `next build` | افزایش هشدار lint، شکست تست یا build |
| `security` | shellcheck روی `ops/`؛ **تست‌های عملیاتی** (نقش‌های گیت، promote، شواهد CI، prune، tip، detached prod، promote guard و سیم‌کشی آن، رکورد E2E، smoke ناوگان، guard چت پشتیبانی، تست‌های مشاهده‌پذیری، پاک‌ساز staging، watchdog، SSH در CI)؛ hadolint؛ gitleaks؛ bandit؛ parse شدن مجموعه‌های QA؛ pip-audit؛ npm audit | یکی از نگهبان‌های فرایند انتشار خراب است یا آسیب‌پذیری/رازی وارد شده |
| `governance` | تست‌های واحد حاکمیت؛ مالکیت/تازگی (`check_docs_freshness.py`)؛ همتاهای فارسی (`check_i18n.py`)؛ موجودی + کف بدهی نسبت به شاخهٔ مقصد (`gen_inventory.py --check --require-base`)؛ ردیابی‌پذیری PR | سند بی‌مالک/منقضی، رانش ترجمه، مورد مستندنشدهٔ جدید، نبود ارجاع issue |
| `images` | ساخت ایمیج بک‌اند و فرانت‌اند؛ بالا آمدن بک‌اند (`manage.py check` درون ایمیج)؛ اسکن trivy هر دو | Dockerfile خراب یا آسیب‌پذیری HIGH/CRITICAL قابل‌رفع |
| `stage` | **فقط روی push به `work`** و پس از سبز شدن هر پنج job: استقرار همان کامیت در staging روی سرور (پایین) | credential نبود/نامعتبر (job قرمز — ریسک شناخته‌شده)، شکست گیت یا smoke روی میزبان |

## ۳۶٫۳ خط لولهٔ promote

<div dir="ltr">

```mermaid
flowchart LR
  A[PR merged to work] --> B[CI: backend frontend security images governance]
  B -->|all green| C[stage job: SSH as CI key]
  C --> D[kg-ci-gate: verbs stage, status only]
  D --> E[deploy.sh --staging: gate in clean worktree]
  E --> F[build images kgkg-backend:sha kgkg-frontend:sha]
  F --> G[staging on :8110/:3107 vs sanitized DB copy]
  G --> H[smoke.sh + QA token checks]
  H --> I{{A person}}
  I -->|types kgkg-promote sha on the server| J[deploy.sh full pipeline]
  J --> K[DB backup, fast-forward, migrate in new image]
  K --> L[new backend beside old on :8000, old stops when new healthy]
  L --> M[frontend stop/start about 1 s]
  M --> N[smoke; any failure rolls back to previous images]
```

</div>

- **CI هرگز نمی‌تواند promote کند.** کلید SSH آن روی سرور به `/usr/local/bin/kg-ci-gate` محدود شده که نقشش فعل `deploy` ندارد (ماتریس با `ops/deploy/test_gate_roles.sh` تست می‌شود). نشت راز CI فقط یک اجرای staging می‌دهد. promote همان `kgkg-promote <sha>` است که یک انسان روی میزبان تایپ می‌کند (ADR-0004)؛ این سند، CI و عامل‌ها آن را اجرا نمی‌کنند.
- **اتصال:** `ops/deploy/ci_ssh.sh` پنج راز (`DEPLOY_HOST`، `DEPLOY_KNOWN_HOSTS`، `DEPLOY_SSH_KEY`، `DEPLOY_CF_ACCESS_CLIENT_ID`، `DEPLOY_CF_ACCESS_CLIENT_SECRET`) را پیش از اتصال اعتبارسنجی می‌کند و برای هر شکست راه‌حل را نام می‌برد. طرح موردنظر Cloudflare Tunnel با توکن سرویس Access است؛ طبق `ops/deploy/README.md` پیکربندی زنده در ۲۰۲۶‑۱۰‑۲۹ اتصال مستقیم SSH روی پورت ۲۲ با sshd فقط‌کلید و fail2ban بود **[S 2026-10-29]**؛ وضعیت فعلی **[U]**. نصاب: `ops/deploy/setup_ci_access.sh` (کلید میزبان را pin می‌کند و اگر sshd کلید دیگری سرو کند رد می‌کند).
- **گیت** (`gate.sh`، worktree تمیز، محیط پاک‌شده: بدون رازهای تولید، پیامک، Sentry یا Metis؛ `KG_ENV_FILE` به فایل موقت اشاره می‌کند): ابزارهای امنیتی، system check، مطابقت migrationها با مدل‌ها، امن‌بودن migrationها برای rollback، مجموعهٔ کامل تست بک‌اند روی پایگاه PostgreSQL یک‌بارمصرف، `npm ci` فرانت‌اند، کف lint، تست واحد، build تولید. شکست گیت تولید را دست‌نخورده می‌گذارد.
- **شواهد برای promote:** موفقیت CI برای sha (`ci_evidence.sh`، jobهای الزامی پیش‌فرض `backend frontend security images`)، staging و یک اجرای کامل E2E ثبت‌شده برای همان sha (`qa/run_e2e.sh` فایل `$KG_REL_DIR/e2e/<sha>.env` را می‌نویسد؛ اجرای فیلترشده `scope=partial` است و حساب نمی‌شود)، و «آیا هنوز tip شاخهٔ `work` است» (`ci_is_tip.sh`). overrideها لاگ می‌شوند. کتابخانهٔ guard (`promote_guard.sh`: رد کامیتی که روی `origin/work` نیست) با تست وجود دارد اما سرصفحهٔ آن می‌گوید در این نسخه **هنوز به `deploy.sh` وصل نشده**؛ `kgkg-promote` این قاعده را روی مسیر خودش اعمال می‌کند.
- **جایگزینی بدون وقفه** (ADR-0003): کانتینر جدید بک‌اند کنار قدیمی روی `:8000` بالا می‌آید (`SO_REUSEPORT`)؛ قدیمی فقط وقتی متوقف می‌شود که جدید از طریق پورت سلامت خصوصی‌اش سالم گزارش دهد. فرانت‌اند stop/start است. شکست smoke ⇐ rollback خودکار به ایمیج‌های قبلی. migrationها **برگردانده نمی‌شوند** (فقط افزایشی)؛ پشتیبان پایگاه داده پیش از دیپلوی نگه داشته می‌شود.
- **سایر افعال دیپلوی:** `deploy.sh --staging <ref>`، `--rollback`، `--status`، `--reload` (ری‌استارت انتشار زنده برای اعمال تغییرات `.env.prod` مثلاً پس از `rotate_secrets`). قفل دیپلوی با `KG_DEPLOY_LOCK_WAIT` (۱۸۰۰ ثانیه) اجراها را سریالی می‌کند؛ کانتینرهای staging پس از اجرا حذف می‌شوند مگر `KG_KEEP_STAGING=1`.
- **پاک‌سازی:** `prune_images.sh` ایمیج ۴ انتشار آخر را نگه می‌دارد.

## ۳۶٫۴ مصنوعات و ایمیج‌ها

`ops/docker/backend.Dockerfile` (gunicorn gthread؛ سلامت روی پورت خصوصی؛ وابستگی‌های قفل‌شده `ops/docker/backend-requirements.lock`) و `frontend.Dockerfile` ([31](31-ops-files-reference.md) بخش ۳۱٫۱). برچسب‌ها sha کامیت‌اند. کانتینرها با `--network host`، bind روی loopback، `--restart unless-stopped` و `--stop-timeout 40` اجرا می‌شوند (`containers.sh`). در مخزن push به registry پیکربندی نشده؛ ایمیج‌ها روی میزبان ساخته می‌شوند **[C]**. تنها artifactهای CI گزارش‌های تست و پوشش‌اند (`backend-test-reports-<sha>`، `support-chat-e2e-<sha>`).

## ۳۶٫۵ محیط‌ها

| محیط | کجا | داده | تفاوت‌ها |
|---|---|---|---|
| CI | رانرهای GitHub | سرویس PostgreSQL یک‌بارمصرف، بدون انبار محتوا | مدل‌های آفلاین، توکن‌های ساختگی |
| پشتهٔ یک‌بارمصرف چت | رانر | SQLite مخصوص، DEBUG | فقط چت پشتیبانی |
| Staging | میزبان، `:8110` / `:3107`، `/opt/KGKG_staging` | کپی پاک‌سازی‌شدهٔ پایگاه پرتال؛ پیامک/Sentry/Metis/host jobs غیرفعال | **`kgkg_vec` تولید را خوانده با انبار mount‌شده read-write (مشاهده ۲۰۲۶‑۱۱‑۰۳، ریسک R5)** |
| QA | میزبان، `:8120` / `:3117` / `:8130` | کپی پاک‌سازی‌شده (`<db>_qa`)؛ حساب‌های تست | سقف CPU/حافظه؛ شبانه استفاده می‌شود ([32](32-testing-and-qa.md) بخش ۳۲٫۵) |
| تولید | میزبان `/opt/KGKG`، `:8000` / `:3000` | زنده | فقط توسط یک انسان با `kgkg-promote` تغییر می‌کند |

وضعیت انتشار زیر `/opt/KGKG_release` است (`state.env`، `logs/`، `db-backups/`، شواهد e2e)؛ worktree کاری `/opt/KGKG_work`.

## ۳۶٫۶ پایش پس از انتشار

دیپلوی سبز یا HTTP 200 را معادل سلامت نگیرید: سلامت کانتینر (`docker ps`)، GlitchTip، متریک‌ها و هشدارها را ببینید. probeهای blackbox (`https://kgtechvault.com/`، `/kg-api/api/health/`)، هدف‌های Prometheus، مرور هشدار ۵دقیقه‌ای و watchdog مستقل در [31](31-ops-files-reference.md) بخش‌های ۳۱٫۲ و ۳۱٫۵ آمده‌اند. `deploy.sh` «چه چیزی زنده است / چه مدت از staging گذشته» را به‌صورت متریک textfile مربوط به node-exporter منتشر می‌کند.

## ۳۶٫۷ بازگشت و بازیابی

۱. `ops/deploy/deploy.sh --rollback` (ایمیج‌های قبلی؛ migrationها اعمال‌شده می‌مانند — migrationها را افزایشی نگه دارید).
۲. اگر داده آسیب دید: پشتیبان پایگاه داده پیش از دیپلوی را از `/opt/KGKG_release/db-backups` بازیابی کنید (موتور پایگاه داده در حال استفاده را پوشش می‌دهد؛ پوشش `kgkg_vec` **راستی‌آزمایی نشده** است، R1).
۳. `deploy.sh --status` نشان می‌دهد چه چیزی زنده و انتشار قبلی کدام است.
۴. بازیابی فاجعهٔ میزبان **اثبات نشده** است (تمرین بازیابی ثبت نشده؛ NFR-07 در SRS دستی است). ← [27](../27-open-risks-and-decisions.md).

## ۳۶٫۸ رازها و مدیریت پیکربندی

رازهای زمان اجرا در `/opt/KGKG/KG_backend/.env.prod` و `/opt/KGKG/kg_frontend/.env.production` هستند (هرگز در git؛ فقط‌خواندنی درون کانتینر mount می‌شوند). `manage.py rotate_secrets` آن‌ها را می‌چرخاند و `deploy.sh --reload` اعمال می‌کند. gitleaks هر push را اسکن می‌کند؛ `.gitleaks.toml` فهرست مجاز است. نام و پیش‌فرض متغیرها: [29](29-environment-reference.md). رازهای CI همان پنج مقدار `DEPLOY_*` بالا هستند.

## ۳۶٫۹ گیت‌های امنیتی در خط لوله

shellcheck، hadolint، gitleaks، bandit (baseline)، pip-audit، npm audit، trivy، CodeQL؛ همان bandit/pip-audit/npm audit بار دیگر درون گیت سرور اجرا می‌شوند. استثناها فایل‌هایی با ذکر دلیل‌اند: [32](32-testing-and-qa.md) بخش ۳۲٫۸.

## ۳۶٫۱۰ محدودیت‌های شناخته‌شده

میزبان واحد و نبود registry؛ promote به یک انسان و دسترسی به میزبان وابسته است؛ `stage` با نبودن راز staging قرمز می‌شود؛ `strict` شاخهٔ به‌روز خاموش است و روی `work` بازبینی الزامی نیست (حفاظت خوانده‌شده در ۲۰۲۶‑۱۱‑۰۴)؛ `promote_guard.sh` به `deploy.sh` وصل نیست؛ staging محتوای خودرو تولید را می‌خواند (R5)؛ بازیابی اثبات‌شده‌ای نیست (R1)؛ timerهای واقعی میزبان و واحدهای قدیمی دوباره بررسی نشدند **[U]**.

</div>
