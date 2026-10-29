# Mutation testing (test-suite strength)

Coverage shows which lines ran; mutation testing shows whether the tests
would notice if those lines were wrong. Tool: mutmut 2.5.1 on an isolated
copy of the backend (it rewrites source files), each mutant run against the
suites that exercise the module, `--failfast`.

| Module | Mutants | Killed | Survived | Equivalent (no observable change) | Score excluding equivalents | Status |
|---|---|---|---|---|---|---|
| `api/mediaauth.py` (paid media gate) | 41 | 34 → **36** | 7 → 5 | 5 | 34/36 (94 %) → **36/36 (100 %)** | Done 2026-10-29 |
| `api/access.py` (entitlements) | 440 | running | running | — | — | In progress (interim: 228 tested, 195 killed, 33 survived) |
| `api/quota.py` (AI allowance) | — | queued | — | — | — | Queued after `access.py` |

## `api/mediaauth.py`

Survivors and verdicts (`mutmut show <id>`):

| Id | Mutation | Verdict |
|---|---|---|
| 3 | `(uri or '')` → `(uri or 'XXXX')` | Equivalent: both yield "not a media path" |
| 5 | query string no longer split off | **Real gap** → test added: `?/../../<car>/` after a shared folder must not re-target the folder |
| 6 | `split('?', 1)` → `split('?', 2)` | Equivalent: same first element |
| 13 | `lstrip('/')` → `lstrip('XX/XX')` | **Real gap** → test added: URIs not rooted at the media prefix are refused |
| 21 | `split('/', 1)` → `split('/', 2)` | Equivalent |
| 31 | `startswith('_')` → `startswith('XX_XX')` | Equivalent: an underscore folder that is no car still resolves to "login only" |
| 32 | `or` → `and` in the shared-folder check | Equivalent: same outcome through the car lookup |

Both real gaps are closed by `KG_backend/api/test_qa_mediaauth_paths.py`
(commit `e52cef6`); applying either mutant now fails the suite.

Reproduce (on a copy of `KG_backend/`):

```bash
mutmut run --paths-to-mutate api/mediaauth.py --tests-dir api --runner "python manage.py test api.test_qa_mediaauth_paths api.test_qa_catalog.MediaAuthTests --noinput --failfast -v 0"
```
