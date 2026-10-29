#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# What GitHub's CI says about one commit.
#
#   ci_evidence.sh verdict <sha>    -> "pass", "fail <detail>" or "unknown <detail>"
#   ci_evidence.sh --selftest       -> parse the shipped fixtures, exit 0 on pass
#
# Why this exists. The server's own gate (ops/deploy/gate.sh, then staging and
# smoke) is thorough about whether a release *runs*. It says nothing about
# whether the suite passed, because it does not run the suite: no coverage
# ratchet, no eslint ratchet, no bandit, no pip-audit, no npm audit, no Trivy.
# So a commit CI had rejected could be staged and promoted, and on 2026-10-29
# one was: 536ac91 went live with CI red on the coverage ratchet (55 % against
# a 56 % floor). The pipeline has to be the only road into production, or it is
# advice rather than a gate.
#
# This asks GitHub for the check runs on the exact commit and insists that
# every required job is completed and successful. A job that is still running,
# a job that is missing, a commit GitHub has never seen and GitHub being
# unreachable are all "unknown", never "pass": the caller must fail closed.
#
# Overrides, all for testing and for an air-gapped host:
#   KG_CI_REQUIRED   space-separated job names (default: the four quality jobs)
#   KG_CI_REPO       owner/name (default: parsed from the origin remote)
#   KG_CI_FETCH      command printing the check-runs JSON for $1; replaces curl
#   KG_CI_TIMEOUT    seconds for the HTTP call (default 20)
#   GITHUB_TOKEN     sent as a bearer token when set; the public repo needs none
# ---------------------------------------------------------------------------
set -uo pipefail

REQUIRED=${KG_CI_REQUIRED:-"backend frontend security images"}
TIMEOUT=${KG_CI_TIMEOUT:-20}

repo() {
  [[ -n ${KG_CI_REPO:-} ]] && { printf '%s' "$KG_CI_REPO"; return; }
  local url
  url=$(git -C "${KG_PROD_DIR:-.}" remote get-url origin 2>/dev/null) || return 1
  url=${url%.git}
  case $url in
    *github.com[:/]*) printf '%s' "${url#*github.com}" | sed 's|^[:/]*||' ;;
    *) return 1 ;;
  esac
}

fetch() {  # sha -> check-runs JSON on stdout
  if [[ -n ${KG_CI_FETCH:-} ]]; then
    $KG_CI_FETCH "$1"
    return
  fi
  local slug
  slug=$(repo) || { echo 'NOREPO'; return 1; }
  local -a auth=()
  [[ -n ${GITHUB_TOKEN:-} ]] && auth=(-H "Authorization: Bearer $GITHUB_TOKEN")
  # ${a[@]+"${a[@]}"}: an empty array under `set -u` is an unbound variable in
  # bash 3.2, which ships on macOS, and the failure would read as "GitHub is
  # unreachable" on a developer's laptop.
  curl -sS --max-time "$TIMEOUT" -f \
       -H 'Accept: application/vnd.github+json' \
       -H 'X-GitHub-Api-Version: 2022-11-28' \
       ${auth[@]+"${auth[@]}"} \
       "https://api.github.com/repos/$slug/commits/$1/check-runs?per_page=100"
}

# Reads the JSON on stdin and the required job names in $1. Prints the verdict.
# Keeping the judgement in python3 (standard library, already required by the
# ops tests) rather than in grep means a renamed field is an error instead of a
# silent "no failures found".
judge() {
  KG_CI_REQUIRED_ARG=$1 python3 -c '
import json, os, sys

required = os.environ["KG_CI_REQUIRED_ARG"].split()
raw = sys.stdin.read().strip()
if not raw:
    print("unknown GitHub returned nothing for this commit"); sys.exit(0)
try:
    runs = json.loads(raw).get("check_runs", [])
except (ValueError, AttributeError):
    print("unknown GitHub returned a body this script cannot read"); sys.exit(0)

# Keep the newest run per job name: a re-run supersedes the attempt before it.
latest = {}
for r in runs:
    name = r.get("name", "")
    if name not in latest or (r.get("started_at") or "") >= (latest[name].get("started_at") or ""):
        latest[name] = r

missing  = [j for j in required if j not in latest]
running  = [j for j in required if j in latest and latest[j].get("status") != "completed"]
failed = []
for j in required:
    r = latest.get(j)
    if r is not None and r.get("status") == "completed" and r.get("conclusion") != "success":
        failed.append(j + "=" + str(r.get("conclusion")))

if failed:
    print("fail " + ", ".join(failed)); sys.exit(0)
if missing:
    print("unknown no check run named " + ", ".join(missing)); sys.exit(0)
if running:
    print("unknown still running: " + ", ".join(running)); sys.exit(0)
print("pass")
'
}

verdict() {
  local sha=${1:?sha}
  local body rc
  body=$(fetch "$sha" 2>/dev/null); rc=$?
  if (( rc != 0 )); then
    if [[ $body == NOREPO ]]; then
      echo "unknown cannot tell which GitHub repository this is (set KG_CI_REPO)"
    else
      echo "unknown GitHub is unreachable (curl exit $rc)"
    fi
    return 0
  fi
  judge "$REQUIRED" <<<"$body"
}

selftest() {
  local fails=0
  check() {  # name expected json
    local got
    got=$(judge "backend frontend security images" <<<"$3")
    if [[ $got == "$2"* ]]; then printf '  ok    %s\n' "$1"
    else printf '  FAIL  %s\n          want %s\n          got  %s\n' "$1" "$2" "$got"; fails=$((fails+1)); fi
  }
  j() {  # name status conclusion -> one check_run object
    printf '{"name":"%s","status":"%s","conclusion":%s,"started_at":"2026-01-01T00:00:00Z"}' \
      "$1" "$2" "$([[ $3 == null ]] && echo null || printf '"%s"' "$3")"
  }
  all() {  # conclusion for every required job
    printf '{"check_runs":[%s,%s,%s,%s]}' \
      "$(j backend completed "$1")" "$(j frontend completed "$1")" \
      "$(j security completed "$1")" "$(j images completed "$1")"
  }

  check "all four green is a pass"            pass    "$(all success)"
  check "a failed job is a fail"              fail    "$(printf '{"check_runs":[%s,%s,%s,%s]}' \
                                                        "$(j backend completed failure)" "$(j frontend completed success)" \
                                                        "$(j security completed success)" "$(j images completed success)")"
  check "a cancelled job is a fail"           fail    "$(all cancelled)"
  check "a skipped job is a fail"             fail    "$(all skipped)"
  check "a job still running is unknown"      unknown "$(printf '{"check_runs":[%s,%s,%s,%s]}' \
                                                        "$(j backend in_progress null)" "$(j frontend completed success)" \
                                                        "$(j security completed success)" "$(j images completed success)")"
  check "a missing job is unknown"            unknown "$(printf '{"check_runs":[%s,%s,%s]}' \
                                                        "$(j backend completed success)" "$(j frontend completed success)" \
                                                        "$(j security completed success)")"
  check "no check runs at all is unknown"     unknown '{"check_runs":[]}'
  check "an empty body is unknown"            unknown ''
  check "a body that is not JSON is unknown"  unknown '<html>502 Bad Gateway</html>'
  # A commit GitHub has never seen answers with a message object, not check_runs.
  check "an unknown commit is unknown"        unknown '{"message":"No commit found for SHA"}'
  # Jobs outside the required set must not be able to veto or to rescue.
  check "an unrelated red job is ignored"     pass    "$(printf '{"check_runs":[%s,%s,%s,%s,%s]}' \
                                                        "$(j backend completed success)" "$(j frontend completed success)" \
                                                        "$(j security completed success)" "$(j images completed success)" \
                                                        "$(j "Dependabot Updates" completed failure)")"
  # The newest attempt wins, so a green re-run clears an earlier red one.
  check "a green re-run supersedes a red try" pass    "$(printf '{"check_runs":[%s,%s,%s,%s,%s]}' \
                                                        '{"name":"backend","status":"completed","conclusion":"failure","started_at":"2026-01-01T00:00:00Z"}' \
                                                        '{"name":"backend","status":"completed","conclusion":"success","started_at":"2026-01-02T00:00:00Z"}' \
                                                        "$(j frontend completed success)" "$(j security completed success)" \
                                                        "$(j images completed success)")"

  if (( fails )); then echo "ci_evidence selftest: $fails failure(s)" >&2; return 1; fi
  echo "ci_evidence selftest: all checks passed"
}

case ${1:-} in
  verdict)    shift; verdict "$@" ;;
  --selftest) selftest ;;
  *) echo "usage: ci_evidence.sh verdict <sha> | --selftest" >&2; exit 2 ;;
esac
