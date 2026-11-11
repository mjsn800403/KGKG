<!-- i18n-source: 32-testing-and-qa.md sha256:57b9c8b1e74d -->
<div dir="rtl" lang="fa">

# ۳۲ — تست، تضمین کیفیت و راستی‌آزمایی

چگونه هر تغییر در KGtechvault را راستی‌آزمایی کنیم، هر سازوکار چه چیزی را ثابت می‌کند و چه چیزی را **پوشش نمی‌دهد**. نسخهٔ سورس `origin/work` در `f078878` **[C]**. هیچ نرخ موفقیت یا درصد پوششی در این سند نیامده مگر آنکه در فایلی از مخزن ذکر شده و منبعش برچسب خورده باشد؛ اعداد زنده در خلاصهٔ اجرای CI هستند. نسخهٔ انگلیسی: [../32-testing-and-qa.md](../32-testing-and-qa.md). مرتبط: [17-evaluation.md](../17-evaluation.md) (ارزیابی هوش مصنوعی)، [11-operations-deployment.md](../11-operations-deployment.md)، [31-ops-files-reference.md](../31-ops-files-reference.md) و `audit-evidence/` (بستهٔ ممیزی ۲۰۲۶؛ شواهد تاریخ‌دار است، نه وضعیت زنده).

## ۳۲٫۱ نقشهٔ سازوکارها

| # | سازوکار | محل اجرا | محرک | مانع merge؟ |
|---|---|---|---|---|
| ۱ | مجموعهٔ تست Django بک‌اند (۱۱۲ ماژول `test_*`/`tests*.py` زیر `KG_backend/`) با پوشش شاخه | job با نام `backend` در CI (سرویس PostgreSQL 16) | هر push و PR | بله |
| ۲ | بررسی migrationها (`makemigrations --check`، فقط‌افزایشی، `ops/deploy/check_migrations.py`) | job بک‌اند؛ گیت دیپلوی | push/PR؛ دیپلوی | بله |
| ۳ | کفِ پوشش (`ops/deploy/coverage_min`، اکنون **۵۹**) | job بک‌اند | push/PR | بله |
| ۴ | کفِ هشدارهای lint فرانت‌اند (`ops/deploy/lint_max_warnings`، اکنون **۱۱۶**)، تست‌های واحد (`node --test`، ۲۱ فایل) و build تولید | job با نام `frontend` | push/PR | بله |
| ۵ | تست‌های عملیاتی (نقش‌های گیت دیپلوی، شواهد promote، سیم‌کشی guard، SSH در CI، watchdog، پاک‌ساز staging، smoke ناوگان) | job با نام `security` | push/PR | بله |
| ۶ | گیت‌های امنیتی: shellcheck، hadolint، gitleaks، bandit، pip-audit، npm audit، trivy (ایمیج‌ها)، CodeQL | jobهای `security` و `images` و workflow مربوط به CodeQL | push/PR | بله |
| ۷ | حاکمیت: مالکیت/تازگی سند، موجودی تولیدشده + کفِ بدهی، ردیابی‌پذیری PR، همگامی ترجمه | job با نام `governance` | push/PR | بله |
| ۸ | E2E چت پشتیبانی (Playwright) روی پشتهٔ یک‌بارمصرف | job با نام `support-chat-e2e` | push/PR | بله (روی PR #88 اجرا و موفق شد) |
| ۹ | E2E کامل مرورگر، DAST غیرفعال، baseline کارایی روی پشتهٔ QA | میزبان: `qa/nightly.sh` از طریق `ops/qa/kgkg-qa-nightly.timer/.service` | شبانه | خیر (هشدار از قاعدهٔ `_qa`) |
| ۱۰ | بار / فشار / ماندگاری (k6) | در صورت نیاز: `qa/perf/run_perf.sh <profile>`، `qa/k6/support_chat_poll.js` | دستی | خیر |
| ۱۱ | آزمون جهش (mutation) برای ماژول‌های مجوز (mutmut) | workflow با نام `mutation.yml`، `qa/mutation/run.sh` | دستی (`workflow_dispatch`) | خیر |
| ۱۲ | ارزیابی آفلاین RAG (مجموعه‌های طلایی، بدون فراخوانی LLM) | `qa/eval/run_rag_eval.sh`، `manage.py run_evalsuite` | دستی | خیر |
| ۱۳ | گیت دیپلوی، دیپلوی staging، smoke پس از دیپلوی | میزبان: `ops/deploy/gate.sh`، `deploy.sh`، `smoke.sh`، `smoke_fleet.py` | هر stage/promote | بله (برای دیپلوی) |
| ۱۴ | شواهد زمان promote (موفقیت CI برای sha، رکورد E2E، بررسی tip) | `kgkg-promote`، `ci_evidence.sh`، `ci_is_tip.sh`، `promote_guard.sh` | هر promote توسط یک انسان | بله |

## ۳۲٫۲ تست‌های بک‌اند

- **ساختار:** ماژول‌های `TestCase`/`SimpleTestCase` جنگو با نام `test_*.py` کنار کد (`api/`، `api/rag/`، `api/support_chat/`، `api/evalsuite/` و ...) به‌علاوهٔ `tests.py` و `tests_parts.py`. در نسخهٔ بالا ۱۱۲ فایل **[C]**.
- **پایگاه داده:** در CI، PostgreSQL 16 (`KG_DB_ENGINE=postgres`، کانتینر سرویس با اعتبارنامهٔ مخصوص CI)؛ نام پایگاه تست در هر اجرا از طریق `KG_PG_TEST_NAME` قابل تعیین است. گیت دیپلوی از PostgreSQL میزبان روی سوکت محلی و با نام جدا در هر اجرا (`test_kgkg_gate_$$`) استفاده می‌کند.
- **آفلاین از ریشه:** `HF_HUB_OFFLINE=1`، `TRANSFORMERS_OFFLINE=1`، `KG_WARMUP=0`، و `KG_ADMIN_TOKEN`/`KG_ENV_FILE` ساختگی در CI: بدون دانلود مدل و بدون فراخوانی خارجی.
- **تصادفی‌سازی ترتیب:** `--shuffle`؛ لاگ `Using shuffle seed: N` را چاپ می‌کند. بازتولید: `python manage.py test --shuffle N`.
- **اجرای محلی** (از `KG_backend/`، با وابستگی‌های lock نصب‌شده):

<div dir="ltr">

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test --noinput --shuffle           # whole suite
python manage.py test api.rag --noinput             # one package
python manage.py test api.test_qa_auth --noinput    # one module
```

</div>

  بدون PostgreSQL، با تنظیم‌نکردن `KG_DB_ENGINE` از SQLite (پیش‌فرض توسعه) استفاده می‌شود؛ رفتارِ مخصوص PostgreSQL (مثلاً `cardb_pg`) به محیطی شبیه CI نیاز دارد.
- **پوشش:** `coverage run --branch --source=api --omit='*/test_*,*/tests.py,*/tests_*.py,*/migrations/*' manage.py test ...`. ماژول‌های تست و migrationها کنار گذاشته می‌شوند تا عدد با پوشش‌دادن خودِ تست‌ها باد نکند. دستور `coverage report --fail-under=$(cat ops/deploy/coverage_min)`. این فایل یک **کف است که فقط بالا می‌رود** و باید در همان کامیتی که تست اضافه می‌کند افزایش یابد. گزارش‌ها (JUnit XML، `coverage.xml`، HTML) با نام artifact برابر `backend-test-reports-<sha>` بارگذاری می‌شوند؛ جمع‌ها در خلاصهٔ گام job می‌آیند. مقدار اندازه‌گیری‌شدهٔ فعلی **در مخزن ثبت نشده است**؛ خلاصهٔ آخرین اجرا را بخوانید **[U]**.
- **تفسیر شکست:** گام `Full test suite` قرمز با یک shuffle seed ← با همان seed دوباره اجرا کنید تا شکست واقعی از وابستگی به ترتیب جدا شود؛ گام `Coverage ratchet` قرمز ← پوشش زیر کف رفته (تست اضافه کنید؛ فایل را کم نکنید)؛ گام `Migrations match models` قرمز ← migration را بسازید و کامیت کنید.
- **مجموعه‌های مهم:** مجوز (`test_qa_auth.py`، ماژول‌های access و media-auth؛ هدف آزمون جهش)، RAG (`api/rag/test_*.py`، ← [30](30-ai-assistant-deep-dive.md) بخش ۳۰٫۱۱)، چت پشتیبانی (`api/support_chat/`، ← [22](../22-support-chat.md))، مترجم PostgreSQL پایگاه خودرو (`test_cardb_pg.py`)، host jobs (`test_hostjobs.py`)، قرارداد OpenAPI (`docs/openapi.yaml` با تست اجباری می‌شود — تغییر view بدون تغییر spec شکست می‌خورد).

## ۳۲٫۳ تست‌های فرانت‌اند

- **اجراکننده:** test runner داخلی Node: `npm test` برابر `node --test --experimental-test-coverage src/` (نه Jest و نه Vitest). فایل‌ها `*.test.mjs` کنار کد، عمدتاً در `kg_frontend/src/lib/__tests__/` هستند (۲۱ فایل در این نسخه: `chatPrompt`، `contextualize`، `faTerms`، `safeUrl`، `sanitizeHtml`، `support`، `desk`، `pricing`، `packages`، `onboarding`، `manualContent`، `vehicleContent`، `friendlyError` و غیره) **[C]**. منطق خالص را تست می‌کنند (ساخت پرامپت، پاک‌سازی پیوند، sanitization، اصطلاحات فارسی)، نه رندر React؛ در `package.json` چارچوب تست کامپوننت وجود ندارد.
- **Lint:** ESLint (`npm run lint`) با **کف هشدار** (`ops/deploy/lint_max_warnings`، ۱۱۶): شمار هشدارها فقط می‌تواند کم شود.
- **Build:** `npm run build` (build تولید Next.js) باید در CI موفق شود.
- **همگامی راهنما:** `kg_frontend/scripts/check-guidance-sync.mjs` داده‌های تورهای راهنما را با منبعشان تطبیق می‌دهد (← [13-guidance-system.md](../13-guidance-system.md)).
- **اجرای محلی:**

<div dir="ltr">

```bash
cd kg_frontend && npm ci --no-audit --no-fund
npm run lint && npm test && npm run build
```

</div>

## ۳۲٫۴ E2E چت پشتیبانی (CI)

job با نام `support-chat-e2e` یک پشتهٔ یک‌بارمصرف بک‌اند + فرانت‌اند بالا می‌آورد (`qa/e2e/support-chat-stack.sh`؛ ویندوز: `local-support-chat-stack.ps1`)، Playwright را نصب می‌کند و `npx playwright test support-chat.spec.js --project=chromium` را اجرا می‌کند. دو محافظ مانع «موفقیت تو‌خالی» می‌شوند: یک **بررسی منفی** که نبودن پشته *شکست* بخورد نه skip، و `qa/e2e/support_chat_guard.py` که `results.json` را می‌خواند و مگر **همهٔ** تست‌های چت پشتیبانی اجرا و موفق شده باشند (بدون skip و بدون مفقود) شکست می‌دهد. رکورد مجموعه با نام `support-chat-e2e-<sha>` بارگذاری می‌شود. آنچه تست‌ها assert می‌کنند: [22-support-chat.md](../22-support-chat.md).

## ۳۲٫۵ E2E کامل مرورگر، DAST و baseline کارایی (پشتهٔ QA، شبانه)

- **پشتهٔ QA** (`qa/stack.sh up|down|reseed|status`): کانتینرهای برچسب‌دار خودش روی پورت‌های حلقوی ۸۱۲۰ (بک‌اند)، ۳۱۱۷ (فرانت‌اند)، ۸۱۳۰ (پراکسی تک‌مبدأ `qa/nginx-qa.conf`؛ بخش `/kg-api/` آن باید `Host $http_host` را همراه با پورت بفرستد، چون `OriginGuardMiddleware` مقدار `Origin` مرورگر (`http://127.0.0.1:8130`) را با طرح+میزبان خود درخواست مقایسه می‌کند و اگر یک نوشتن با کوکی تفاوت داشته باشد پاسخ ۴۰۳ می‌دهد)، هرگز تولید (۸۰۰۰/۳۰۰۰) یا staging (۸۱۱۰/۳۱۰۷). داده یک **نسخهٔ تازهٔ پاک‌سازی‌شده** از پایگاه تولید است (کلون `pg_dump` در PostgreSQL به نام `<db>_qa` یا پشتیبان آنلاین SQLite) که از `ops/deploy/sanitize_staging_db.py` عبور می‌کند، پس هیچ حساب واقعی نمی‌تواند وارد شود و هیچ تلفن/ایمیل واقعی وجود ندارد؛ پیامک، Sentry، Turnstile، Metis و host jobs غیرفعال‌اند؛ مخزن بازخورد RAG بازهدایت شده (`RAG_FEEDBACK_DB`)؛ CPU/حافظه سقف دارد. حساب‌های تست از `manage.py seed_qa_fixtures` می‌آیند (با محافظ `KG_QA_STACK=1` و `KG_QA_PASSWORD` تولیدشده در هر اجرا در فایلی با حالت ۶۰۰). کامنت `stack.sh` می‌گوید چه چیزی آن را ایمن می‌کند؛ نمی‌گوید `kgkg_vec` کلون می‌شود، پس محتوای خودرو از mount انبار میزبان می‌آید **[U]** (← ریسک R5، [27](../27-open-risks-and-decisions.md)).
- **E2E با Playwright** (`qa/e2e/tests/`: `public`، `auth`، `authz`، `session`، `media`، `a11y`، `support`، `support-chat`): locale برابر `fa-IR`، یک worker، **صفر retry** («تست ناپایدار یک یافته است») و trace/screenshot هنگام شکست؛ اگر origin شبیه تولید باشد پیکربندی از اجرا امتناع می‌کند. روی پشته: `qa/run_e2e.sh` (خروجی `qa/e2e/results/{junit.xml,results.json,html/}`؛ یک رکورد شواهد `$KG_REL_DIR/e2e/<sha>.env` هم با `qa/e2e_record.py` می‌نویسد که `kgkg-promote` می‌خواند؛ اجرای فیلترشده با `scope=partial` ثبت می‌شود و به حساب نمی‌آید).
- **DAST:** `qa/dast/run_zap.sh baseline` — baseline غیرفعال OWASP ZAP، بدون ترافیک حمله؛ وضعیت قواعد در `qa/dast/rules.tsv` (پیش‌فرض WARN؛ ورودی فقط با دلیل triage).
- **baseline کارایی:** `qa/perf/run_perf.sh baseline` با `qa/perf/k6-kgkg.js`: یک کاربر به مدت ۲ دقیقه. **آستانه‌ها:** نرخ خطا < ۱٪؛ p95 صفحه < ۱۵۰۰ms؛ p95 API < ۵۰۰ms؛ p95 دستیار (RAG) < ۴۰۰۰ms. پروفایل‌های دیگر: `load` (۱۰ کاربر مجازی، حدود ۶٫۵ دقیقه)، `stress` (۱۰←۲۵←۵۰ کاربر مجازی، بدون آستانه — دنبال نقطهٔ شکست است)، `soak` (۸ کاربر مجازی، ۲۰ دقیقه).
- **هماهنگی شبانه:** `qa/nightly.sh [ref]` (محافظ flock؛ worktree تازهٔ detached؛ گام‌ها: بالا آوردن پشته ← E2E ← DAST ← کارایی ← پایین آوردن پشته، هرکدام حتی اگر گام قبل شکست خورده ثبت می‌شود). نتایج: `/opt/KGKG_qa/nightly/<UTC>-<sha9>/` (۳۰ اجرا نگه داشته می‌شود)؛ متریک‌ها `kgkg_qa.prom` در پوشهٔ textfile مربوط به node-exporter؛ قاعدهٔ `_qa` وقتی آخرین نتیجه قدیمی‌تر از `KG_ALERT_QA_STALE_H` (۳۶ ساعت) یا ناموفق باشد page می‌دهد. اینکه timer فعال است و آخرین موفقیت چه زمانی بوده **[U]** است (راستی‌آزمایی میزبان مسدود بود).

## ۳۲٫۶ آزمون بار چت پشتیبانی

`qa/k6/support_chat_poll.js` poll بازدیدکننده را می‌راند (پیش‌فرض ۱۰۰ کاربر مجازی به مدت ۶۰ ثانیه؛ با متغیرهای `VUS` و `DURATION` قابل تغییر) تا هزینهٔ polling در برابر SSE سنجیده شود. یافته‌ها و تصمیم‌ها: [22-support-chat.md](../22-support-chat.md) و [09-realtime-sse.md](../09-realtime-sse.md).

## ۳۲٫۷ آزمون جهش (Mutation)

`qa/mutation/run.sh [module …]` (پیش‌فرض `admin_auth mediaauth access`) mutmut نسخهٔ ۲٫۴٫۵ را روی یک کپی یک‌بارمصرف از `git archive HEAD` اجرا می‌کند تا درخت کار دست نخورد. پوشش می‌گوید یک خط اجرا شده؛ جهش بازمانده یعنی تغییری در منطق مجوز که هیچ تستی متوجه‌اش نمی‌شود. برای ماژول‌های بزرگ حدود یک ساعت طول می‌کشد، در صورت نیاز اجرا می‌شود (workflow با نام `mutation`، `workflow_dispatch`، سقف ۱۸۰ دقیقه) و وقتی به `audit-evidence/03-unit-testing/mutation/` کپی شود شواهد انتشار است. هیچ نتیجه‌ای در `docs/` ثبت نشده؛ آخرین اعداد در صورت وجود در `audit-evidence/` است **[U]**.

## ۳۲٫۸ تحلیل ایستا و گیت‌های زنجیرهٔ تأمین

| گیت | ابزار و دامنه | مسدود می‌کند وقتی | فایل استثنا |
|---|---|---|---|
| lint شل | shellcheck روی `ops/**/*.sh` و `ops/deploy/kg-deploy-gate` | هر هشدار | — |
| lint داکرفایل | hadolint روی `ops/docker/*.Dockerfile` | هر هشدار | `.hadolint.yaml` |
| اسکن راز | gitleaks (درخت + کامیت‌های push‌شده) | هر یافته | فهرست مجاز `.gitleaks.toml` |
| SAST | bandit روی Python | یافته‌های خارج از baseline | `ops/security/bandit-baseline.json` |
| وابستگی‌های Python | pip-audit روی `ops/docker/backend-requirements.lock` | advisory نادیده‌گرفته‌نشده | `pip-audit-ignore.txt` |
| وابستگی‌های Node | npm audit (تولید)، `npm_audit_gate.mjs`، شدت ≥ high | advisory غیرمجاز | `ops/security/npm-audit-allow.json` (خالی) |
| اسکن ایمیج | trivy روی هر دو ایمیج تولید، HIGH/CRITICAL قابل‌رفع | یافتهٔ نادیده‌گرفته‌نشده | `.trivyignore.yaml` |
| CodeQL | اسکن کد GitHub برای Python، JavaScript/TypeScript و Actions | هشدارها طبق سیاست مخزن | — |

همین سه اسکن سمت سرور در **گیت دیپلوی** هم اجرا می‌شوند (`ops/security/scan.sh`، اسکنرها از venv ثابت؛ اسکنری که اجرا نشود گیت را رد می‌کند). جزئیات: `ops/security/README.md`.

## ۳۲٫۹ تست‌های عملیاتی (job با نام `security`، گام «Operations tests»)

تست‌هایی که فقط به کتابخانهٔ استاندارد تکیه دارند و سازوکار محافظ تولید را می‌سنجند: `test_gate_roles.sh`، `test_promote.sh`، `ci_evidence.sh --selftest`، `prune_images.sh --selftest`، `ci_is_tip.sh --selftest`، `test_detached_prod.sh`، `test_promote_guard.sh`، `test_promote_guard_wiring.sh`، `qa/e2e_record.py --selftest`، `ops/deploy/smoke_fleet.py --selftest`، `qa/e2e/support_chat_guard.py --selftest`، تست‌های واحد مشاهده‌پذیری، `sanitize_staging_db.py --selftest`، `watchdog.py --selftest`، `test_ci_ssh.sh`. هرکدام را محلی با `bash ops/deploy/<name>` یا `python3 <path> --selftest` اجرا کنید.

## ۳۲٫۱۰ تست‌های حاکمیت

دستور `python3 -m unittest discover` درون `ops/governance/` (job با نام `governance` هم اجرایش می‌کند) بررسی تازگی، بررسی ردیابی‌پذیری، کفِ موجودی و همگامی ترجمه را پوشش می‌دهد (۱۴ تست موجودی، مخزن‌های git موقت می‌سازند تا ثابت کنند بازتولید فایل بدهی نمی‌تواند baseline شاخهٔ مقصد را دور بزند؛ تست‌های `test_i18n.py` رانش ترجمه را می‌سنجند). دستورات: [AGENTS.md](../AGENTS.md) بخش ۶.

## ۳۲٫۱۱ راستی‌آزمایی دیپلوی

- **گیت** (`ops/deploy/gate.sh`، پیش از هر تغییر توسط `deploy.sh` اجرا می‌شود): بررسی افزایشی‌بودن migration نسبت به `KG_MIGRATION_BASE`، مجموعهٔ تست بک‌اند روی پایگاه PostgreSQL یک‌بارمصرف، اسکن‌های امنیتی، لاگ‌ها در `$REL/logs/gate-<ts>`. گیت ناموفق تولید را دست‌نخورده می‌گذارد.
- **Stage** (job با نام `stage` در CI، فقط روی push به `work` و با وجود credential؛ روی PR رد می‌شود): sha را روی کانتینرهای جدا (`kgkg-stg-*`) مستقر می‌کند، migration را روی کلون پاک‌سازی‌شده اجرا می‌کند، داده می‌کارد و smoke می‌زند. نبودن راز staging job را قرمز می‌کند (ریسک شناخته‌شده).
- **Smoke** (`ops/deploy/smoke.sh`): سلامت، بررسی پراکسی معکوس با هدر `Host:`، شنوندهٔ scrape باید برای هر چیز جز متریک‌ها 403 بدهد، و `smoke_fleet.py` به‌ازای هر دسته `KG_SMOKE_SAMPLE` (پیش‌فرض ۳، از ۱ تا ۲۰) خودرو را با یک توکن باز می‌کند.
- **دیپلوی سبز یا HTTP 200 را معادل سلامت نگیرید:** سلامت کانتینر، GlitchTip و متریک‌ها را هم ببینید ([AGENTS.md](../AGENTS.md) قاعدهٔ ۷).

## ۳۲٫۱۲ جدول تصمیم: یک تغییر را چگونه راستی‌آزمایی کنیم

| چه چیز را تغییر دادید | حداقل راستی‌آزمایی محلی | گیت CI که بررسی می‌کند |
|---|---|---|
| منطق / مدل / view بک‌اند | `manage.py test <package>`؛ `makemigrations --check`؛ به‌روزرسانی `docs/openapi.yaml` و اسناد | `backend`، `governance` |
| یک migration | فقط افزایشی؛ `ops/deploy/check_migrations.py` | `backend`، گیت دیپلوی |
| بازیابی / رتبه‌بندی / پرامپت | `manage.py test api.rag`؛ برای تغییر رتبه‌بندی ارزیابی آفلاین (`qa/eval/run_rag_eval.sh`) را اجرا و با `paired_significance.py` مقایسه کنید | `backend`، دستی |
| مجوز (`access.py`، `admin_auth.py`، `mediaauth.py`) | تست واحد + در نظر گرفتن `qa/mutation/run.sh <module>` | `backend`، `mutation` در صورت نیاز |
| منطق فرانت‌اند | `npm run lint && npm test && npm run build` | `frontend` |
| چت پشتیبانی | تست‌های بک‌اند + `support-chat.spec.js` روی پشتهٔ یک‌بارمصرف | `support-chat-e2e` |
| اسکریپت یا واحد `ops/` | `shellcheck`؛ `--selftest` همان؛ ردیف سند در ۳۱ | `security`، `governance` |
| فقط سند | `check_docs_freshness.py`، `gen_inventory.py --check`، `check_i18n.py` | `governance` |

## ۳۲٫۱۳ شکاف‌های شناخته‌شده (گفته‌شده، نه پنهان)

- تست در سطح کامپوننت/DOM برای فرانت‌اند و گیت پوششی برای آن وجود ندارد؛ `node --experimental-test-coverage` گزارش چاپ می‌کند اما چیزی کف را اجباری نمی‌کند.
- کف پوشش بک‌اند ۵۹٪ است؛ مقدار اندازه‌گیری‌شده و روند آن در مخزن ذخیره نمی‌شود.
- E2E مرورگر (به‌جز چت پشتیبانی) در CI هر PR **نیست**؛ شبانه روی میزبان اجرا می‌شود، پس رگرسیون‌ها پس از merge پیدا می‌شوند.
- تست‌های بار دستی‌اند؛ baselineِ ثبت‌شده‌ای در مخزن نیست **[U]**.
- کیفیت پاسخ هوش مصنوعی در CI بررسی خودکار ندارد؛ ارزیابی آفلاین و دستی است (بخش ۳۰٫۱۱).
- رفتار مخصوص PostgreSQL ذخیرهٔ محتوای خودرو (`kgkg_vec`) از طریق تست‌های واحد مترجم سنجیده می‌شود؛ تستی روی `kgkg_vec` پرشدهٔ ۵۸ گیگابایتی وجود ندارد.
- منبع داده محتوای خودرو در پشتهٔ QA **[U]** است (بخش ۳۲٫۵).

</div>
