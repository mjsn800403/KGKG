#!/usr/bin/env bash
# KGKG smoke tests against a running backend + frontend. Read-only requests
# only (safe against production). With a portal token (staging) it also checks
# the signed-in paths: profile, A/B flags, quota, a car tree and retrieval.
#
# Usage: ops/deploy/smoke.sh <backend-url> <frontend-url> [portal-token]
set -uo pipefail
BE=${1:?backend url}; FE=${2:?frontend url}; TOKEN=${3:-}
FAILS=0
check() {  # name, expected-status-regex, curl args...
  local name=$1 want=$2; shift 2
  local got
  got=$(curl -s -o /tmp/kg-smoke.body -w '%{http_code}' --max-time 60 "$@")
  if [[ $got =~ ^($want)$ ]]; then printf '  ok    %-38s %s\n' "$name" "$got"
  else printf '  FAIL  %-38s got %s, want %s\n' "$name" "$got" "$want"; head -c 300 /tmp/kg-smoke.body; echo; FAILS=$((FAILS+1)); fi
}
contains() {  # name, needle (checks the last response body)
  if grep -q -- "$2" /tmp/kg-smoke.body; then printf '  ok    %-38s contains %s\n' "$1" "$2"
  else printf '  FAIL  %-38s missing %s\n' "$1" "$2"; FAILS=$((FAILS+1)); fi
}

echo "== backend $BE"
check "health"                    200 "$BE/api/health/"
check "brand list"                200 "$BE/"
check "protected API needs auth"  401 "$BE/api/auth/me/"
check "unknown API path is 404"   404 "$BE/api/no-such-endpoint/"
check "admin API needs auth"      401 "$BE/api/admin/flags/"

echo "== frontend $FE"
check "landing"                   200 "$FE/"
contains "landing brand"          "KGTechVault"
check "login page"                200 "$FE/login"
check "pricing page"              200 "$FE/purchase"
check "signed-out car -> login"   '307|308' "$FE/toyota/2025/corolla-cross"
check "chat API needs auth"       '401|403' -X POST -H 'Content-Type: application/json' -d '{"message":"x"}' "$FE/api/chat"

if [[ -n $TOKEN ]]; then
  AUTH=(-H "Authorization: Bearer $TOKEN")
  echo "== signed-in (staging token)"
  check "profile"                 200 "${AUTH[@]}" "$BE/api/auth/me/"
  check "A/B flags"               200 "${AUTH[@]}" "$BE/api/auth/flags/"
  contains "flags payload"        '"flags"'
  check "AI quota + arms"         '200|429' "${AUTH[@]}" "$BE/api/auth/ai-usage/"
  contains "quota carries arms"   '"flags"'
  check "car catalog (Toyota 2025)" 200 "${AUTH[@]}" "$BE/Toyota/2025/"
  check "retrieval (no LLM)"      200 "${AUTH[@]}" -X POST -H 'Content-Type: application/json' \
        -d '{"query":"engine oil capacity","brand":"Toyota","model":"Corolla Cross"}' "$BE/api/assist/"
  contains "retrieval returns hits" '"hits"'
  check "car page (SSR, signed-in)" 200 -H "Cookie: kg_portal_token=$TOKEN" "$FE/toyota/2025/corolla-cross"
fi

echo
if (( FAILS )); then echo "SMOKE FAILED: $FAILS check(s)"; exit 1; fi
echo "SMOKE PASSED"
