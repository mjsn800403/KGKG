# Mutation testing — authorization modules

**Question answered:** do the tests notice when authorization logic is wrong, or do they only
execute it? Coverage cannot answer this; mutation testing can.

**Method:**

* Tool: mutmut 2.4.5, driven by `qa/mutation/run.sh`, on a `git archive` copy of the
  backend.
* Each mutant is one small change: an operator flipped, a constant altered, a `continue`
  turned into `break`, a default changed.
* After each mutant, the tests that guard that module are re-run (the test set is listed in
  `run.sh`). A mutant is **killed** if any test fails, and **survives** if all pass.
* Modules: `api/admin_auth.py` (admin gate), `api/mediaauth.py` (paid-media gate) and
  `api/access.py` (entitlements, delegation, org reach).
* On demand in CI: `.github/workflows/mutation.yml`.

## Results

| Module | Run 1 (`69449d3`) | After the new tests |
|---|---|---|
| admin_auth | 42/48 killed = **87.5 %** | 42/48 = **87.5 %** (run 2, `1d886d4`) |
| mediaauth | 34/41 = **82.9 %** | 35/41 = **85.4 %** (run 2, `1d886d4`) |
| access | 327/440 = **74.3 %** | 339/440 = **77.0 %** (run 3, `f6a0450`) |

Run 2's access figure (327/440 again) is not reported: the runner's access test set did not
yet include `api.test_access_rules`, so the new tests never ran. That was fixed in `f6a0450`,
and run 3 re-scored access. The +12 kills are exactly the 12 access blind spots listed below.

Raw output for each module (`<module>.results.txt`, `.junit.xml`, `.survivors.diff`):

* run 1: `run1-69449d3/`
* run 2 (admin_auth, mediaauth): `run2-1d886d4/`
* run 3 (access): `run3-f6a0450/`

The very first admin_auth run, on `6cb611f` before `69449d3`, scored 36/48 = 75.0 %. It is
reported in that commit's message.

## What the survivors were, and what was done

### Real blind spots — now killed by new tests

| Module | Mutant that survived | Why it matters | Test that now kills it |
|---|---|---|---|
| admin_auth | `HTTP_X_REAL_IP` removed from the proxy-header list | That list is what keeps the static, no-2FA admin token to direct loopback calls; a request relayed by nginx also arrives from 127.0.0.1 | `test_admin_token_scope.py::test_via_nginx_real_ip_header_is_rejected` |
| admin_auth | error bodies, `@wraps` | the frontend reads the bodies | `AdminGateResponseTests` |
| mediaauth | query string no longer stripped before normalising | `x.png?/../../<car>/` would be judged as another car's folder while nginx serves the first | `test_query_string_cannot_smuggle_a_folder` (two-level case) |
| access | `manager_can_target`: `>=` → `>` (legacy path) | a manager could manage a same-rank peer | `test_access_rules.py::LegacyRankTests` |
| access | `apply_user_access(override_purchase=True)` default | an admin call without the flag would bypass the company purchase | `test_admin_call_without_explicit_flag_stays_inside_the_purchase` |
| access | `continue` → `break` at 8 sites (4 in `apply_user_access`, 2 in `apply_managed_access`, 2 in `enforce_org_consistency`) | one bad, unpurchased, duplicate or already-valid entry would silently drop every grant or repair after it | `test_bad_entries_do_not_drop_the_good_ones_after_them` (×2), `OrgConsistencyTests` |
| access | `manager_grantable_cars`: `and` → `or` | a stale non-admin grant outside the purchase would become delegable | `test_stale_non_admin_grant_outside_the_purchase_is_not_delegable`, `test_grantable_is_the_company_purchase_…` |
| access | `fixed += 1` → `fixed = 1` | wrong repair count reported to the admin | `OrgConsistencyTests` |

Every new test was also run against its mutant applied by hand, to confirm that it fails.

### Survivors left on purpose (equivalent or cosmetic)

**Equivalent:** the change cannot alter behaviour.

* Defaults of `request.META.get(…, '')` replaced with `'XXXX'` when the header is absent.
* `getattr(settings, 'DEBUG', …)` and `getattr(actor, 'can_manage_team', …)` defaults:
  both attributes always exist.
* `split('?', 1)` → `split('?', 2)[0]`.
* `ROLE_LEVEL.get(…, 99)` → `100`: any unknown role still ranks below every real one.

**Unreachable code:**

* the `'none'` and `'org'` branches of `manageable_user_ids`, because `user_manage_scope()`
  always returns `'subtree'`;
* the third `continue` in `enforce_org_consistency`, because `find_valid_supervisor` returns
  the current parent only when the first check already passed.

These are candidates for removal rather than for tests.

**Display text and taxonomy constants:** the larger part of the access.py survivors (67 in
run 1) are Persian and English labels and the analytics alias table (`CONTENT_CATEGORIES`).
A wrong label is a UI defect, not an authorization one. A golden list of real manual
section titles mapped to their expected category would kill the alias mutants if the
analytics categories become contractual.

**`parse_seat_plan` messages:** the Persian error texts are not asserted. The validation
itself is.

## How to re-run

```bash
pip install mutmut==2.4.5            # plus the backend dependencies
qa/mutation/run.sh                   # all three modules, about an hour
qa/mutation/run.sh admin_auth        # one module, a few minutes
```

Or run **Actions → mutation → Run workflow**. Copy the artifact here when it is release
evidence.
