#!/usr/bin/env bash
# Mutation testing for the authorization modules (mutmut 2.4.5).
#
# Coverage says a line ran; mutation testing says a test would notice if the
# line were wrong. mutmut flips one operator/constant/condition at a time
# ("<=" -> "<", "and" -> "or", True -> False ...) and re-runs the tests that
# guard that module. A mutant the tests still pass on ("survived") is a change
# in authorization logic nobody would catch.
#
#   qa/mutation/run.sh [module ...]       default: admin_auth mediaauth access
#   OUT=/path qa/mutation/run.sh          results directory (default qa/mutation/results)
#
# Needs: the backend's Python deps + mutmut==2.4.5 on PATH. Works on a
# throwaway copy of KG_backend from `git archive HEAD` (mutmut edits source in
# place), so the working tree is never touched. Slow by nature (one test run
# per mutant): access.py takes about an hour on a laptop.
set -Eeuo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(git -C "$HERE" rev-parse --show-toplevel)
OUT=${OUT:-$HERE/results}
MODULES=("$@")
(( ${#MODULES[@]} )) || MODULES=(admin_auth mediaauth access)

# The tests that guard each module (the fast, targeted set; the full suite
# would multiply the run time by ~20 for no extra kills).
declare -A TESTS=(
  [admin_auth]="api.test_admin_token_scope api.rag.test_ratelimit api.test_qa_auth api.test_adminops.GateTests api.test_security.AdminTokenTests"
  [mediaauth]="api.test_qa_mediaauth_paths api.test_qa_catalog api.tests"
  [access]="api.test_access_rules api.test_qa_access api.test_qa_orggraph_authz api.test_orgreach api.test_orggraph api.test_team"
)

command -v mutmut >/dev/null || { echo "mutmut not found (pip install mutmut==2.4.5)" >&2; exit 1; }
export DJANGO_DEBUG=true KG_ADMIN_TOKEN=mutation-dummy KG_ENV_FILE=/tmp/mutation-dummy.env \
       HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 KG_WARMUP=0

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
git -C "$REPO" archive HEAD KG_backend | tar -x -C "$WORK"
SHA=$(git -C "$REPO" rev-parse HEAD)
mkdir -p "$OUT"

for m in "${MODULES[@]}"; do
  [[ -n ${TESTS[$m]:-} ]] || { echo "no test set for $m" >&2; exit 1; }
  echo "=== $m  (tests: ${TESTS[$m]})"
  ( cd "$WORK/KG_backend"
    rm -f .mutmut-cache
    mutmut run --paths-to-mutate "api/$m.py" --tests-dir api --no-progress \
      --runner "python manage.py test --noinput --failfast ${TESTS[$m]}" || true
    mutmut results > "$OUT/$m.results.txt" || true
    mutmut junitxml > "$OUT/$m.junit.xml" || true
    # surviving mutants as diffs, for review
    : > "$OUT/$m.survivors.diff"
    for id in $(mutmut result-ids survived 2>/dev/null); do
      { echo "### mutant $id"; mutmut show "$id"; echo; } >> "$OUT/$m.survivors.diff"
    done
  )
  python3 - "$OUT/$m.junit.xml" "$m" "$SHA" >> "$OUT/summary.tsv" <<'PY'
import sys, xml.etree.ElementTree as ET
path, mod, sha = sys.argv[1:]
r = ET.parse(path).getroot()
s = r if r.tag == 'testsuite' else next(r.iter('testsuite'))
total = int(s.get('tests', 0)); failed = int(s.get('failures', 0)) + int(s.get('errors', 0))
skipped = int(s.get('skipped', 0) or 0)
killed = total - failed - skipped
scored = total - skipped
print(f"{sha[:9]}\t{mod}\t{total}\tkilled={killed}\tsurvived={failed}\tskipped={skipped}\t"
      f"score={100.0 * killed / scored if scored else 0:.1f}%")
PY
  tail -1 "$OUT/summary.tsv"
done
