#!/usr/bin/env bash
# Run the browser E2E suite against the QA stack (qa/stack.sh up first).
# Output: qa/e2e/results/{junit.xml,results.json,html/}
#
# Every run also leaves an evidence record for the commit the QA stack is
# serving, $KG_REL_DIR/e2e/<sha>.env (qa/e2e_record.py), which kgkg-promote
# reads before production. A run with arguments (a filtered run, e.g. one spec)
# is recorded as scope=partial and does not count as release evidence.
set -Eeuo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
QA=${KG_QA_DIR:-/opt/KGKG_qa/stack}
REL=${KG_REL_DIR:-/opt/KGKG_release}
ORIGIN=$(sed -n 's/^QA_ORIGIN=//p' "$QA/stack.env")
SHA=$(sed -n 's/^QA_SHA=//p' "$QA/stack.env")
SCOPE=full
(( $# )) && SCOPE=partial
"$HERE/stack.sh" reseed
cd "$HERE/e2e"
rm -rf results test-results
rc=0
docker run --rm --network host --ipc=host -v "$PWD":/w -w /w \
  -v "$QA/fixtures.json":/qa/fixtures.json:ro -e QA_ORIGIN="$ORIGIN" \
  mcr.microsoft.com/playwright:v1.64.1-noble \
  sh -c 'npm ci --no-audit --no-fund >/dev/null && npx playwright test "$@"' -- "$@" || rc=$?
echo
echo "E2E evidence record ($REL/e2e/$SHA.env):"
python3 "$HERE/e2e_record.py" results/results.json "$SHA" "$SCOPE" "$REL/e2e" | sed 's/^/  /'
exit "$rc"
