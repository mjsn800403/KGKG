#!/usr/bin/env bash
# Run the browser E2E suite against the QA stack (qa/stack.sh up first).
# Output: qa/e2e/results/{junit.xml,results.json,html/}
set -Eeuo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
QA=${KG_QA_DIR:-/opt/KGKG_qa/stack}
ORIGIN=$(sed -n 's/^QA_ORIGIN=//p' "$QA/stack.env")
"$HERE/stack.sh" reseed
cd "$HERE/e2e"
rm -rf results test-results
docker run --rm --network host --ipc=host -v "$PWD":/w -w /w \
  -v "$QA/fixtures.json":/qa/fixtures.json:ro -e QA_ORIGIN="$ORIGIN" \
  mcr.microsoft.com/playwright:v1.52.0-noble \
  sh -c 'npm ci --no-audit --no-fund >/dev/null && npx playwright test "$@"' -- "$@"
