#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# CI side of the GitHub -> server connection (.github/workflows/ci.yml, job
# `stage`).
#
# The runner logs in as root with the key in DEPLOY_SSH_KEY, which the server
# pins to /usr/local/bin/kg-ci-gate (stage, status; never deploy). Every
# attempt up to 2026-10-29 failed on empty secrets and the only message was
# ssh's own ("Could not resolve hostname :"). This script checks the secrets
# before connecting and turns each way the connection fails into the one
# thing to fix.
#
#   ci_ssh.sh prepare           validate the secrets; write the key and known_hosts
#   ci_ssh.sh preflight         `status` on the server; refuse a key that can promote
#   ci_ssh.sh run <command...>  run a gate verb on the server; explain a failure
#
# Reads DEPLOY_SSH_KEY, DEPLOY_HOST, DEPLOY_KNOWN_HOSTS (optional) and
# DEPLOY_PORT (optional, default 22). KG_CI_SSH_DIR replaces ~/.ssh (tests).
#
# Transport. With DEPLOY_CF_ACCESS_CLIENT_ID and DEPLOY_CF_ACCESS_CLIENT_SECRET
# set, ssh goes through a Cloudflare Tunnel instead of to a public port:
# DEPLOY_HOST is the tunnel's hostname (a route to SSH localhost:22), and
# `cloudflared access ssh` presents that Access service token, so port 22 can
# stay closed to the internet. The token reaches cloudflared through its
# environment (TUNNEL_SERVICE_TOKEN_ID/SECRET), never a command line.
#
# The server half, which creates the key and sets these secrets, is
# ops/deploy/setup_ci_access.sh. Tests: ops/deploy/test_ci_ssh.sh.
# ---------------------------------------------------------------------------
set -uo pipefail

SSH_DIR=${KG_CI_SSH_DIR:-$HOME/.ssh}
KEY_FILE=$SSH_DIR/deploy
KH_FILE=$SSH_DIR/known_hosts
TARGET_FILE=$SSH_DIR/kgkg-target
ACCESS_FILE=$SSH_DIR/kgkg-access
FIX="On the server, as root: bash /opt/KGKG/ops/deploy/setup_ci_access.sh (see ops/deploy/README.md)."
FIX_TUNNEL="On the server, as root: bash /opt/KGKG/ops/deploy/setup_ci_access.sh --tunnel <hostname> (see ops/deploy/README.md)."

# One ::error:: annotation (shown on the run page), then plain detail lines.
report() { printf '::error::%s\n' "$1"; shift; (( $# )) && printf '  %s\n' "$@"; return 0; }
fail()   { report "$@"; exit 1; }

trim() {  # strip leading and trailing whitespace
  local s=$1
  s=${s#"${s%%[![:space:]]*}"}
  printf '%s' "${s%"${s##*[![:space:]]}"}"
}

prepare() {
  local key=${DEPLOY_SSH_KEY:-} host=${DEPLOY_HOST:-} port=${DEPLOY_PORT:-} kh=${DEPLOY_KNOWN_HOSTS:-}
  local missing=
  [[ -n $(trim "$key") ]]  || missing+=" DEPLOY_SSH_KEY"
  [[ -n $(trim "$host") ]] || missing+=" DEPLOY_HOST"
  [[ -z $missing ]] || fail "Staging cannot run: missing repository secret(s):$missing" \
    "GitHub has never been given the credential to reach the server; only the server can create it." \
    "$FIX" \
    "It creates a key that can only stage, pins it, tests it, and sets the secrets."

  # The host as people paste it: whitespace, user@, ssh://, host:port.
  host=$(trim "$host"); host=${host#ssh://}; host=${host##*@}; host=${host%/}
  if [[ $host =~ ^([^:]+):([0-9]+)$ ]]; then
    host=${BASH_REMATCH[1]}
    [[ -n $(trim "$port") ]] || port=${BASH_REMATCH[2]}
  fi
  port=$(trim "$port"); port=${port:-22}
  [[ $host =~ ^[A-Za-z0-9.-]+$ ]] \
    || fail "DEPLOY_HOST must be a hostname or IPv4 address, got '$host'"
  [[ $port =~ ^[0-9]+$ ]] && (( port > 0 && port < 65536 )) \
    || fail "DEPLOY_PORT must be a TCP port number, got '$port'"

  local cf_id cf_secret transport=ssh
  cf_id=$(trim "${DEPLOY_CF_ACCESS_CLIENT_ID:-}")
  cf_secret=$(trim "${DEPLOY_CF_ACCESS_CLIENT_SECRET:-}")
  if [[ -n $cf_id || -n $cf_secret ]]; then
    [[ -n $cf_id && -n $cf_secret ]] \
      || fail "Only one of DEPLOY_CF_ACCESS_CLIENT_ID and DEPLOY_CF_ACCESS_CLIENT_SECRET is set; the tunnel needs both" \
           "$FIX_TUNNEL"
    [[ $host == *.* && ! $host =~ ^[0-9.]+$ ]] \
      || fail "With the Cloudflare tunnel, DEPLOY_HOST must be the tunnel's hostname (like ssh-ci.example.com), not '$host'" \
           "$FIX_TUNNEL"
    # The port is the tunnel route's business (SSH localhost:22); ssh itself
    # only uses it to pick the known_hosts entry, which is the bare hostname.
    transport=cloudflare port=22
  fi

  # The key as people paste it: CRLF from a Windows clipboard, one line with
  # literal \n from some editors, surrounding blank lines.
  key=${key//$'\r'/}
  [[ $key == *$'\n'* || $key != *'\n'* ]] || key=${key//\\n/$'\n'}
  key=$(trim "$key")
  if [[ $key =~ ^(ssh-[a-z0-9]+|ecdsa-sha2-[a-z0-9]+|sk-[a-z0-9@.-]+)[[:space:]]+AAAA ]]; then
    fail "DEPLOY_SSH_KEY holds a public key (${BASH_REMATCH[1]} AAAA...); it needs the private key" \
      "Paste the whole private key file, from -----BEGIN to -----END, both lines included." "$FIX"
  fi
  install -m 700 -d "$SSH_DIR"
  (umask 077; printf '%s\n' "$key" > "$KEY_FILE")
  local why
  if ! why=$(ssh-keygen -y -P '' -f "$KEY_FILE" 2>&1 >/dev/null); then
    case $why in
      *passphrase*) fail "DEPLOY_SSH_KEY is protected by a passphrase, which CI cannot type" \
                      "Use a key without one, pinned to kg-ci-gate." "$FIX" ;;
      *)            fail "DEPLOY_SSH_KEY is not a usable private key (${why##*: })" \
                      "Paste the whole private key file, from -----BEGIN to -----END, both lines included." "$FIX" ;;
    esac
  fi

  # Host key. ssh looks up "[host]:port" when the port is not 22.
  local entry=$host strict=yes
  (( port == 22 )) || entry="[$host]:$port"
  kh=${kh//$'\r'/}
  if [[ -n $(trim "$kh") ]]; then
    printf '%s\n' "$(trim "$kh")" > "$KH_FILE"
    ssh-keygen -F "$entry" -f "$KH_FILE" >/dev/null 2>&1 \
      || fail "DEPLOY_KNOWN_HOSTS has no line for $entry" \
           "Each line starts with the address ssh connects to, so it must match DEPLOY_HOST$( (( port == 22 )) || printf ' as [host]:port')." \
           "$FIX It prints the right line."
  else
    : > "$KH_FILE"
    # Without a pinned host key the connection is not authenticated in the
    # server's direction, so say so loudly rather than pretend.
    echo "::warning::DEPLOY_KNOWN_HOSTS is not set; the server's host key is not verified."
    strict=accept-new
  fi

  printf 'HOST=%q\nPORT=%q\nSTRICT=%q\nTRANSPORT=%q\n' "$host" "$port" "$strict" "$transport" > "$TARGET_FILE"
  rm -f "$ACCESS_FILE"
  if [[ $transport == cloudflare ]]; then
    (umask 077; printf 'TUNNEL_SERVICE_TOKEN_ID=%q\nTUNNEL_SERVICE_TOKEN_SECRET=%q\n' "$cf_id" "$cf_secret" > "$ACCESS_FILE")
    echo "via:    Cloudflare Tunnel, Access service token $cf_id"
  fi
  echo "target: root@$host port $port"
  echo "key:    $(ssh-keygen -l -f "$KEY_FILE" | awk '{print $2}') (compare with what setup_ci_access.sh printed)"
  echo "host key check: $strict"
}

# Through the tunnel every Cloudflare-side failure reaches ssh as the same
# "Connection closed by UNKNOWN port 65535", and cloudflared prints only
# "websocket: bad handshake" whatever the cause, at any log level. The HTTP
# status of one plain request with the same token tells the causes apart.
access_status() {
  local hdr code
  hdr=$(mktemp) || return 0
  chmod 600 "$hdr"
  printf 'CF-Access-Client-Id: %s\nCF-Access-Client-Secret: %s\n' \
    "${TUNNEL_SERVICE_TOKEN_ID:-}" "${TUNNEL_SERVICE_TOKEN_SECRET:-}" > "$hdr"
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 -H "@$hdr" "https://$HOST/" 2>/dev/null)
  rm -f "$hdr"
  printf '%s' "${code:-000}"
}

explain_tunnel() {  # ssh's stderr
  local code
  case $1 in
    *"no such host"*|*"Bad Gateway"*|*"server misbehaving"*)
      report "The tunnel hostname $HOST does not resolve" \
        "In Cloudflare Zero Trust, the tunnel needs a public hostname $HOST -> SSH localhost:22." "$FIX_TUNNEL"
      return ;;
    *"cloudflared: command not found"*|*"cloudflared: not found"*)
      report "cloudflared is not installed on the runner" "The workflow's install step must run before this one."
      return ;;
  esac
  code=$(access_status)
  case $code in
    301|302|303|307)
      report "Cloudflare Access sent the runner to a login page for $HOST (HTTP $code)" \
        "The Access application's policy must have action 'Service Auth' and include this service token." ;;
    401|403)
      report "Cloudflare Access refused the service token for $HOST (HTTP $code)" \
        "DEPLOY_CF_ACCESS_CLIENT_ID/SECRET are wrong, revoked or expired (service tokens have a duration)." \
        "Create a new token, add it to the application's Service Auth policy, then: $FIX_TUNNEL" ;;
    530)
      report "Cloudflare reached no running tunnel for $HOST (HTTP 530)" \
        "The connector on the server is down or was removed: systemctl status cloudflared" ;;
    *)
      report "Cloudflare did not open an SSH session to $HOST (HTTP $code)" \
        "Check that $HOST routes to SSH localhost:22 on a running tunnel and that its Access policy" \
        "is 'Service Auth' with this token. $FIX_TUNNEL It tests the whole path from the server." ;;
  esac
}

# Map an ssh exit status and its stderr to what to do about it.
explain() {  # rc, stderr
  local rc=$1 msg=$2
  if [[ ${TRANSPORT:-ssh} == cloudflare && $rc == 255 ]]; then
    case $msg in
      # Verdicts from sshd itself, through the tunnel: the shared cases below.
      *"Host key verification failed"*|*"IDENTIFICATION HAS CHANGED"*|*"Permission denied"*) ;;
      *) explain_tunnel "$msg"; return 0 ;;
    esac
  fi
  case $rc:$msg in
    0:*) ;;
    255:*"Could not resolve hostname"*)
      report "DEPLOY_HOST '$HOST' does not resolve" \
        "Use the server's IP address. The site's domain points at Cloudflare, which does not carry SSH." ;;
    255:*"Host key verification failed"*|255:*"IDENTIFICATION HAS CHANGED"*)
      report "The server's host key does not match DEPLOY_KNOWN_HOSTS" \
        "If the server was rebuilt or its host keys regenerated, re-run setup_ci_access.sh to print the new line." \
        "Otherwise stop: something other than the server answered at $HOST." ;;
    255:*"Permission denied"*)
      report "The server refused DEPLOY_SSH_KEY for root@$HOST" \
        "Either the key above is not in /root/.ssh/authorized_keys, or the secret holds a different key." "$FIX" ;;
    255:*"Connection refused"*)
      report "Nothing accepts SSH on $HOST port $PORT" \
        "sshd is not running there, or listens on another port (then set the DEPLOY_PORT secret)." ;;
    255:*"timed out"*|255:*"No route to host"*|255:*"Network is unreachable"*)
      report "GitHub's runner cannot reach $HOST port $PORT" \
        "A firewall (ufw, the hosting provider's panel) or fail2ban is dropping it. GitHub-hosted runners" \
        "come from changing addresses, so the port must accept any source; the key itself can only stage." ;;
    255:*"Connection closed"*|255:*"Connection reset"*|255:*"kex_exchange_identification"*)
      report "The server closed the SSH connection before authentication" \
        "Usually fail2ban banning the runner's address (fail2ban-client status sshd), or sshd's" \
        "MaxStartups / AllowUsers settings." ;;
    255:*)
      report "SSH to root@$HOST port $PORT failed" "ssh's own message is above." ;;
    2:*"denied:"*)
      local why hint
      why=$(grep -m1 -o 'denied:.*' <<<"$msg")
      case $why in
        *"not on origin/work"*) hint="The server stages only commits already on origin/work." ;;
        *"may not"*)            hint="The CI key may only stage and read status: it is pinned to kg-ci-gate on purpose." ;;
        *)                      hint="The gate's rules are in ops/deploy/kg-deploy-gate." ;;
      esac
      report "The server's deploy gate refused the request: $why" "$hint" ;;
    3:*)
      report "Another staging or deploy run held the server's lock for too long; re-run this job" ;;
    4:*)
      report "The server could not fetch origin/work from GitHub" \
        "Check the server's own GitHub access: git -C /opt/KGKG fetch origin work" ;;
    *)
      report "The command ran on the server and failed (exit $rc)" \
        "The server's output above is the log; the full log is under /opt/KGKG_release/logs/ there." ;;
  esac
}

run_remote() {
  [[ -f $TARGET_FILE ]] || fail "ci_ssh.sh: run 'prepare' first"
  # shellcheck source=/dev/null
  . "$TARGET_FILE"
  local err rc via=()
  if [[ ${TRANSPORT:-ssh} == cloudflare ]]; then
    command -v cloudflared >/dev/null \
      || fail "cloudflared is not installed on the runner" "The workflow's install step must run before this one."
    # Exported to this process only, so ssh hands them to the ProxyCommand.
    set -a
    # shellcheck source=/dev/null
    . "$ACCESS_FILE"
    set +a
    via=(-o "ProxyCommand=cloudflared access ssh --hostname %h")
  fi
  err=$(mktemp)
  # -F none: no client config can change where this goes or with what key.
  # stdout goes straight through (fd 3); stderr is shown live and kept for
  # explain().
  { ssh -n -F none -i "$KEY_FILE" -p "$PORT" "${via[@]}" \
        -o BatchMode=yes -o IdentitiesOnly=yes \
        -o "StrictHostKeyChecking=$STRICT" -o "UserKnownHostsFile=$KH_FILE" -o GlobalKnownHostsFile=/dev/null \
        -o ConnectTimeout=20 -o ServerAliveInterval=30 -o ServerAliveCountMax=6 \
        "root@$HOST" "$*" 2>&1 1>&3 3>&- | tee "$err" >&2
    rc=${PIPESTATUS[0]}
  } 3>&1
  explain "$rc" "$(<"$err")"
  rm -f "$err"
  return "$rc"
}

preflight() {
  local out rc
  out=$(run_remote status)
  rc=$?
  printf '%s\n' "$out"
  (( rc == 0 )) || return "$rc"
  # The gate prints the key's role (kg-deploy-gate, status). A CI key that
  # could promote breaks the one property the pipeline is built on.
  if grep -qx 'key role: operator' <<<"$out"; then
    fail "DEPLOY_SSH_KEY is pinned to kg-deploy-gate (role operator), so CI could promote to production" \
      "Pin the CI key to /usr/local/bin/kg-ci-gate instead." "$FIX"
  fi
  echo "connection OK"
}

case ${1:-} in
  prepare)   prepare ;;
  preflight) preflight ;;
  run)       shift; (( $# )) || fail "usage: ci_ssh.sh run <command...>"; run_remote "$@" ;;
  *)         echo "usage: ci_ssh.sh prepare | preflight | run <command...>" >&2; exit 64 ;;
esac
