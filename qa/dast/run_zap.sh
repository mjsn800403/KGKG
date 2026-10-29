#!/usr/bin/env bash
# Dynamic application security testing (OWASP ZAP) against the QA stack.
#   qa/dast/run_zap.sh baseline   passive: spider + passive rules (minutes)
#   qa/dast/run_zap.sh full       active: spider + active attack rules, signed in
#   qa/dast/run_zap.sh api        active: every operation in docs/openapi.yaml, signed in
#                                 (the app is a JS-driven SPA, so the spider alone
#                                 finds only a handful of URLs; this is the real API scan)
# Reports land in qa/dast/results/ (HTML, JSON, Markdown).
#
# Only ever the QA stack: the active scan sends injection, traversal and XSS
# payloads, which is acceptable against a throwaway, sanitized copy and not
# acceptable anywhere else. The QA proxy has no WAF, so findings reflect what
# the application itself lets through (production additionally runs
# ModSecurity + OWASP CRS in front).
set -Eeuo pipefail
MODE=${1:?baseline|full}
HERE=$(cd "$(dirname "$0")" && pwd)
QA=${KG_QA_DIR:-/opt/KGKG_qa/stack}
OUT=$HERE/results
ORIGIN=$(sed -n 's/^QA_ORIGIN=//p' "$QA/stack.env")
case $ORIGIN in http://127.0.0.1:81[0-9][0-9]) ;; *) echo "refusing: $ORIGIN is not the QA proxy" >&2; exit 2 ;; esac
mkdir -p "$OUT"; chmod 777 "$OUT"
"$HERE/../stack.sh" reseed >/dev/null
TOKEN=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["tokens"]["manager"])' "$QA/fixtures.json")

# Signed in as qa_e2e_manager for every request; logout is excluded so the
# scan cannot end its own session. Production and staging ports and the public
# domain are excluded outright: the frontend bundle contains the server-side
# fallback URL http://127.0.0.1:8000, and on 2026-10-27 the spider extracted it
# from JavaScript and sent one passive GET / to the production backend.
ZAPOPTS="-config replacer.full_list(0).description=session \
 -config replacer.full_list(0).enabled=true \
 -config replacer.full_list(0).matchtype=REQ_HEADER \
 -config replacer.full_list(0).matchstr=Cookie \
 -config replacer.full_list(0).regex=false \
 -config replacer.full_list(0).replacement=kg_portal_token=$TOKEN \
 -config globalexcludeurl.url_list.url(0).regex=.*/logout/?.* \
 -config globalexcludeurl.url_list.url(0).enabled=true \
 -config globalexcludeurl.url_list.url(1).regex=.*/api/events/stream/.* \
 -config globalexcludeurl.url_list.url(1).enabled=true \
 -config globalexcludeurl.url_list.url(2).regex=^https?://(127\\.0\\.0\\.1|localhost):(8000|3000|8110|3107)(/.*)?$ \
 -config globalexcludeurl.url_list.url(2).enabled=true \
 -config globalexcludeurl.url_list.url(3).regex=^https?://([a-z0-9-]+\\.)*kgtechvault\\.com(/.*)?$ \
 -config globalexcludeurl.url_list.url(3).enabled=true"

case $MODE in
  baseline) SCRIPT=zap-baseline.py; EXTRA=(-m 3) ;;
  full) SCRIPT=zap-full-scan.py; EXTRA=(-m 5 -T 60 -j) ;;
  api)
    # Absolute server URL for the scanner; the spec itself uses /kg-api.
    # The global URL excludes do not apply to operations imported from a spec,
    # so logout is removed from the scanner's copy (it would revoke the scan's
    # own session and turn the rest of the run into signed-out probing).
    python3 - "$HERE/../../docs/openapi.yaml" "$ORIGIN" > "$OUT/openapi-scan.yaml" <<'PY'
import re, sys
spec, origin = open(sys.argv[1]).read(), sys.argv[2]
spec = spec.replace('- url: /kg-api', f'- url: {origin}/kg-api', 1)
spec = re.sub(r'\n  /api/auth/logout/:\n(?:    .*\n|\n)*?(?=  /)', '\n', spec)
assert '/api/auth/logout/' not in spec, 'logout still in scan spec'
print(spec, end='')
PY
    SCRIPT=zap-api-scan.py; EXTRA=(-f openapi -T 60) ;;
  *) echo "usage: $0 baseline|full|api" >&2; exit 2 ;;
esac

IMAGE=ghcr.io/zaproxy/zaproxy:stable
docker image inspect "$IMAGE" >/dev/null 2>&1 || docker pull -q "$IMAGE" >/dev/null
{ echo "mode=$MODE"; echo "target=$ORIGIN"; echo "started=$(date -u +%FT%TZ)"; grep QA_SHA "$QA/stack.env"
  docker image inspect -f 'zap image {{.Id}} {{.Created}}' "$IMAGE"; } > "$OUT/env-$MODE.txt"
set +e
cp "$HERE/rules.tsv" "$OUT/rules.tsv"
TARGET=$ORIGIN; [[ $MODE == api ]] && TARGET=/zap/wrk/openapi-scan.yaml
docker run --rm --network host --cpus 4 -v "$OUT":/zap/wrk:rw \
  "$IMAGE" $SCRIPT -t "$TARGET" "${EXTRA[@]}" -c rules.tsv -I \
  -r "zap-$MODE.html" -J "zap-$MODE.json" -w "zap-$MODE.md" -z "$ZAPOPTS" 2>&1 | tee "$OUT/zap-$MODE.log"
rc=${PIPESTATUS[0]}
echo "finished=$(date -u +%FT%TZ) exit=$rc" >> "$OUT/env-$MODE.txt"
"$HERE/../stack.sh" reseed >/dev/null
exit $rc
