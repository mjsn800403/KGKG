#!/usr/bin/env bash
# KGKG smoke tests against a running backend + frontend. Read-only requests
# only (safe against production). With a portal token (staging) it also checks
# the signed-in paths: profile, A/B flags, quota, a car tree and retrieval.
#
# Usage: ops/deploy/smoke.sh <backend-url> <frontend-url> [portal-token]
#
# With KG_SMOKE_NGINX set (e.g. http://127.0.0.1) it also checks the reverse
# proxy itself: security headers, and that the internal-only paths are refused.
# It goes through loopback with a Host header rather than the public name, so a
# CDN or DNS blip cannot fail a deploy and trigger a rollback.
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
header() {  # name, header-name, expected-substring, url, [curl args...]
  local name=$1 hdr=$2 want=$3 url=$4; shift 4
  local got
  got=$(curl -s -D - -o /dev/null --max-time 30 "$@" "$url" \
        | tr -d '\r' | grep -i "^$hdr:" | head -1 | cut -d' ' -f2-)
  # An empty $want means "any value, but the header must be there": a check
  # that passes on an absent header is worse than no check.
  if [[ -n $got && ${got,,} == *${want,,}* ]]; then printf '  ok    %-38s %s\n' "$name" "$got"
  else printf '  FAIL  %-38s %s header is %s, want %s\n' "$name" "$hdr" "${got:-absent}" "${want:-any value}"; FAILS=$((FAILS+1)); fi
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
# Added with the metrics endpoint: Prometheus gets its own credential, so an
# unauthenticated scrape must never succeed. 503 is an instance with no
# KG_METRICS_TOKEN set, and 404 is a release older than the endpoint - which
# matters because this same suite runs after a rollback. The assertion that
# earns its place is the one that holds in all three cases: never a 200.
check "metrics never open"        '401|403|404|503' "$BE/api/metrics/"
check "SSE stream needs auth"     '401|403' "$BE/api/events/stream/"
check "health rejects POST"       '405|403' -X POST "$BE/api/health/"

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

if [[ -n ${KG_SMOKE_NGINX:-} ]]; then
  NX=${KG_SMOKE_NGINX%/}
  HOSTHDR=(-H "Host: ${KG_SMOKE_HOST:-kgtechvault.com}")
  echo "== reverse proxy $NX (Host: ${KG_SMOKE_HOST:-kgtechvault.com})"
  check "proxied landing"           200 "${HOSTHDR[@]}" "$NX/"
  check "proxied health"            200 "${HOSTHDR[@]}" "$NX/kg-api/api/health/"
  # Internal state must not be reachable from the public path, token or not.
  check "public metrics refused"    403 "${HOSTHDR[@]}" "$NX/kg-api/api/metrics/"
  # The scrape listener serves exactly one location.
  check "scrape port serves only metrics" 403 "${KG_SMOKE_SCRAPE:-http://127.0.0.1:8081}/kg-api/api/health/"
  header "nosniff header"           x-content-type-options nosniff "$NX/" "${HOSTHDR[@]}"
  header "frame-options header"     x-frame-options "" "$NX/" "${HOSTHDR[@]}"
  header "referrer-policy header"   referrer-policy "" "$NX/" "${HOSTHDR[@]}"
  # A config backup left in sites-enabled is loaded by nginx and breaks every
  # reload; it cost a failed reload on 2026-10-27.
  if [[ -d /etc/nginx/sites-enabled ]]; then
    stray=$(find /etc/nginx/sites-enabled -maxdepth 1 -type f ! -name kgkg | head -3)
    if [[ -z $stray ]]; then printf '  ok    %-38s only the site file\n' "sites-enabled is clean"
    else printf '  FAIL  %-38s stray file(s): %s\n' "sites-enabled is clean" "$(tr '\n' ' ' <<<"$stray")"; FAILS=$((FAILS+1)); fi
  fi
fi

echo
if (( FAILS )); then echo "SMOKE FAILED: $FAILS check(s)"; exit 1; fi
echo "SMOKE PASSED"
