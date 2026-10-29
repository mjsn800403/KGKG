#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Tests for ops/deploy/ci_ssh.sh, the CI side of the connection to the server.
#
# `prepare` is tested on real keys made here with ssh-keygen; `run` and
# `preflight` against a stub ssh on PATH that replays what the real one prints
# for each failure, so nothing leaves this machine.
#
#   ops/deploy/test_ci_ssh.sh      (exit 0 = pass)
# ---------------------------------------------------------------------------
set -uo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CI_SSH=$HERE/ci_ssh.sh
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
PASS=0
FAIL=0

ssh-keygen -q -t ed25519 -N '' -C test -f "$T/id"
ssh-keygen -q -t ed25519 -N 'secret' -C test -f "$T/id_pass"
ssh-keygen -q -t ed25519 -N '' -C test -f "$T/host"
KEY=$(<"$T/id")
PUB=$(<"$T/id.pub")
HOSTKEY=$(awk '{print $1" "$2}' "$T/host.pub")
# Lines for every address the tests below dial; used whenever a test does
# not set DEPLOY_KNOWN_HOSTS itself.
KH_ALL=$(printf '%s\n' "1.2.3.4 $HOSTKEY" "[1.2.3.4]:2222 $HOSTKEY" "[1.2.3.4]:2200 $HOSTKEY" \
                       "ssh-ci.example.com $HOSTKEY")

# Stub ssh: records its arguments and the Access token it would hand to a
# ProxyCommand, replays FAKE_OUT / FAKE_ERR, exits FAKE_RC.
mkdir -p "$T/bin"
cat > "$T/bin/ssh" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$@" > "$FAKE_ARGS"
printf 'id=%s secret=%s\n' "${TUNNEL_SERVICE_TOKEN_ID:-}" "${TUNNEL_SERVICE_TOKEN_SECRET:-}" > "$FAKE_ARGS.env"
[[ -n ${FAKE_OUT:-} ]] && printf '%s\n' "$FAKE_OUT"
[[ -n ${FAKE_ERR:-} ]] && printf '%s\n' "$FAKE_ERR" >&2
exit "${FAKE_RC:-0}"
EOF
# Stub curl: what Cloudflare would answer (FAKE_CURL_CODE); keeps its
# arguments and the header file it was given.
cat > "$T/bin/curl" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$@" > "$FAKE_ARGS.curl"
for a in "$@"; do [[ $a == @* ]] && cat "${a#@}" > "$FAKE_ARGS.curlhdr"; done
printf '%s' "${FAKE_CURL_CODE:-000}"
EOF
printf '#!/bin/sh\nexit 0\n' > "$T/bin/cloudflared"
chmod +x "$T/bin/ssh" "$T/bin/curl" "$T/bin/cloudflared"

ci() {  # args... -> RC, OUT (stdout+stderr); secrets come from the caller's env
  rm -rf "${T:?}/home"
  OUT=$(DEPLOY_KNOWN_HOSTS=${DEPLOY_KNOWN_HOSTS-$KH_ALL} KG_CI_SSH_DIR="$T/home" bash "$CI_SSH" "$@" 2>&1)
  RC=$?
}
ok() { printf '  ok    %s\n' "$1"; PASS=$((PASS+1)); }
no() { printf '  FAIL  %s\n       -> rc=%s out=%s\n' "$1" "$RC" "$OUT"; FAIL=$((FAIL+1)); }
expect() {  # description, wanted rc, substring of the output
  if (( RC == $2 )) && [[ $OUT == *"$3"* ]]; then ok "$1"; else no "$1"; fi
}
target() { grep "^$1=" "$T/home/kgkg-target" 2>/dev/null | cut -d= -f2-; }

unset DEPLOY_SSH_KEY DEPLOY_HOST DEPLOY_KNOWN_HOSTS DEPLOY_PORT \
      DEPLOY_CF_ACCESS_CLIENT_ID DEPLOY_CF_ACCESS_CLIENT_SECRET

echo "missing secrets:"
DEPLOY_KNOWN_HOSTS='' ci prepare
expect "none set: names all three" 1 "missing repository secret(s): DEPLOY_SSH_KEY DEPLOY_HOST DEPLOY_KNOWN_HOSTS"
[[ $OUT == *setup_ci_access.sh* ]] && ok "points at the server-side setup" || no "points at the server-side setup"
DEPLOY_SSH_KEY=$KEY DEPLOY_HOST="   " ci prepare
expect "whitespace-only host counts as missing" 1 "secret(s): DEPLOY_HOST"
DEPLOY_HOST=1.2.3.4 ci prepare
expect "key missing" 1 "secret(s): DEPLOY_SSH_KEY"

echo "the key, as people paste it:"
DEPLOY_SSH_KEY=$KEY DEPLOY_HOST=1.2.3.4 ci prepare
expect "a clean key is accepted" 0 "target: root@1.2.3.4 port 22"
[[ $(stat -c %a "$T/home/deploy") == 600 ]] && ok "key file is 0600" || no "key file is 0600"
[[ $OUT == *"$(ssh-keygen -l -f "$T/id" | awk '{print $2}')"* ]] && ok "prints the key fingerprint" || no "prints the key fingerprint"
DEPLOY_SSH_KEY=${KEY//$'\n'/$'\r\n'} DEPLOY_HOST=1.2.3.4 ci prepare
expect "CRLF line endings are accepted" 0 "target:"
grep -q $'\r' "$T/home/deploy" && no "CR stripped from the key file" || ok "CR stripped from the key file"
DEPLOY_SSH_KEY=${KEY//$'\n'/\\n} DEPLOY_HOST=1.2.3.4 ci prepare
expect "one line with literal \\n is accepted" 0 "target:"
DEPLOY_SSH_KEY=$'\n\n'"$KEY"$'\n\n' DEPLOY_HOST=1.2.3.4 ci prepare
expect "surrounding blank lines are accepted" 0 "target:"
DEPLOY_SSH_KEY=$PUB DEPLOY_HOST=1.2.3.4 ci prepare
expect "a public key is refused by name" 1 "holds a public key"
DEPLOY_SSH_KEY="not a key" DEPLOY_HOST=1.2.3.4 ci prepare
expect "garbage is refused" 1 "is not a usable private key"
DEPLOY_SSH_KEY=$(head -n 3 "$T/id") DEPLOY_HOST=1.2.3.4 ci prepare
expect "a truncated key is refused" 1 "is not a usable private key"
DEPLOY_SSH_KEY=$(<"$T/id_pass") DEPLOY_HOST=1.2.3.4 ci prepare
expect "a passphrase-protected key is refused" 1 "passphrase"

echo "the host, as people paste it:"
DEPLOY_SSH_KEY=$KEY DEPLOY_HOST=" root@1.2.3.4 " ci prepare
expect "user@ and spaces are dropped" 0 "target: root@1.2.3.4 port 22"
DEPLOY_SSH_KEY=$KEY DEPLOY_HOST="ssh://root@1.2.3.4:2222" ci prepare
expect "ssh://host:port gives the port" 0 "target: root@1.2.3.4 port 2222"
DEPLOY_SSH_KEY=$KEY DEPLOY_HOST="1.2.3.4:2222" DEPLOY_PORT=2200 ci prepare
expect "DEPLOY_PORT wins over host:port" 0 "port 2200"
DEPLOY_SSH_KEY=$KEY DEPLOY_HOST="1.2.3.4; rm -rf /" ci prepare
expect "a host with shell characters is refused" 1 "must be a hostname or IPv4 address"
DEPLOY_SSH_KEY=$KEY DEPLOY_HOST=1.2.3.4 DEPLOY_PORT=ssh ci prepare
expect "a non-numeric port is refused" 1 "must be a TCP port number"
DEPLOY_SSH_KEY=$KEY DEPLOY_HOST=1.2.3.4 DEPLOY_PORT=70000 ci prepare
expect "an out-of-range port is refused" 1 "must be a TCP port number"

echo "known_hosts:"
DEPLOY_SSH_KEY=$KEY DEPLOY_HOST=1.2.3.4 DEPLOY_KNOWN_HOSTS='' ci prepare
expect "unset is refused like the other secrets, never trust-on-first-use" 1 "missing repository secret(s): DEPLOY_KNOWN_HOSTS"
[[ ! -e $T/home/kgkg-target ]] && ok "nothing to connect with is left behind" || no "nothing to connect with is left behind"
DEPLOY_SSH_KEY=$KEY DEPLOY_HOST=1.2.3.4 DEPLOY_KNOWN_HOSTS=$' \r\n ' ci prepare
expect "whitespace-only counts as unset" 1 "missing repository secret(s): DEPLOY_KNOWN_HOSTS"
DEPLOY_SSH_KEY=$KEY DEPLOY_HOST=1.2.3.4 DEPLOY_KNOWN_HOSTS="1.2.3.4 $HOSTKEY" ci prepare
[[ $RC == 0 && $(target STRICT) == yes ]] && ok "a matching line enables strict checking" || no "a matching line enables strict checking"
DEPLOY_SSH_KEY=$KEY DEPLOY_HOST=1.2.3.4 DEPLOY_KNOWN_HOSTS="1.2.3.4 $HOSTKEY"$'\r' ci prepare
expect "a CRLF line is accepted" 0 "host key check: yes"
DEPLOY_SSH_KEY=$KEY DEPLOY_HOST=1.2.3.4 DEPLOY_KNOWN_HOSTS="5.6.7.8 $HOSTKEY" ci prepare
expect "a line for another address is refused" 1 "DEPLOY_KNOWN_HOSTS has no line for 1.2.3.4"
DEPLOY_SSH_KEY=$KEY DEPLOY_HOST=1.2.3.4 DEPLOY_PORT=2222 DEPLOY_KNOWN_HOSTS="1.2.3.4 $HOSTKEY" ci prepare
expect "port 2222 needs the [host]:port form" 1 "no line for [1.2.3.4]:2222"
DEPLOY_SSH_KEY=$KEY DEPLOY_HOST=1.2.3.4 DEPLOY_PORT=2222 DEPLOY_KNOWN_HOSTS="[1.2.3.4]:2222 $HOSTKEY" ci prepare
expect "port 2222 with [host]:port is accepted" 0 "host key check: yes"

# run/preflight: prepare once, then call the script against the stub ssh.
export DEPLOY_SSH_KEY=$KEY DEPLOY_HOST=1.2.3.4 DEPLOY_KNOWN_HOSTS="1.2.3.4 $HOSTKEY"
export FAKE_ARGS=$T/args
remote() {  # rc, stderr, stdout, args... -> RC, OUT
  local rc=$1 err=$2 out=$3; shift 3
  rm -rf "${T:?}/home"
  KG_CI_SSH_DIR="$T/home" bash "$CI_SSH" prepare >/dev/null 2>&1 || { RC=99; OUT="prepare failed"; return; }
  OUT=$(PATH="$T/bin:$PATH" FAKE_RC=$rc FAKE_ERR=$err FAKE_OUT=$out KG_CI_SSH_DIR="$T/home" bash "$CI_SSH" "$@" 2>&1)
  RC=$?
}

echo "the command that is sent:"
remote 0 "" "" run stage 0123456789abcdef0123456789abcdef01234567
args=$(<"$FAKE_ARGS")
[[ $args == *$'\nroot@1.2.3.4\nstage 0123456789abcdef0123456789abcdef01234567' ]] && ok "root@host, then the verb as one argument" || no "root@host, then the verb as one argument ($args)"
[[ $args == *$'-p\n22\n'* && $args == *"StrictHostKeyChecking=yes"* && $args == *"BatchMode=yes"* && $args == *$'-F\nnone\n'* ]] \
  && ok "port, strict host key, batch mode, no client config" || no "port, strict host key, batch mode, no client config ($args)"

echo "each failure names its fix:"
remote 0 "" "staged ok" run stage 0123456789abcdef0123456789abcdef01234567
expect "success passes the server's output through" 0 "staged ok"
[[ $OUT != *"::error::"* ]] && ok "success raises no error" || no "success raises no error"
remote 255 "ssh: Could not resolve hostname 1.2.3.4: Name or service not known" "" run status
expect "unresolvable host" 255 "does not resolve"
remote 255 "root@1.2.3.4: Permission denied (publickey)." "" run status
expect "key not authorized" 255 "The server refused DEPLOY_SSH_KEY"
remote 255 "Host key verification failed." "" run status
expect "host key mismatch" 255 "host key does not match DEPLOY_KNOWN_HOSTS"
remote 255 "ssh: connect to host 1.2.3.4 port 22: Connection timed out" "" run status
expect "firewalled port" 255 "cannot reach 1.2.3.4 port 22"
remote 255 "ssh: connect to host 1.2.3.4 port 22: Connection refused" "" run status
expect "nothing listening" 255 "Nothing accepts SSH"
remote 255 "kex_exchange_identification: Connection closed by remote host" "" run status
expect "dropped before auth (fail2ban)" 255 "closed the SSH connection before authentication"
remote 255 "something new" "" run status
expect "unknown ssh failure still reported" 255 "SSH to root@1.2.3.4 port 22 failed"
remote 2 "denied: role 'ci' may not 'deploy'; allowed: stage status" "" run deploy x
expect "gate refusal is quoted" 2 "refused the request: denied: role 'ci' may not 'deploy'"
remote 4 "git fetch failed" "" run stage 0123456789abcdef0123456789abcdef01234567
expect "server cannot fetch" 4 "could not fetch origin/work"
remote 1 "" "smoke failed" run stage 0123456789abcdef0123456789abcdef01234567
expect "staging failure keeps its exit status" 1 "failed (exit 1)"

echo "preflight:"
remote 0 "" $'key role: ci\nlive: abc' preflight
expect "role ci is accepted" 0 "connection OK"
remote 0 "" $'key role: operator\nlive: abc' preflight
expect "a key that could promote is refused" 1 "could promote to production"
remote 0 "" "live: abc" preflight
expect "a gate too old to report its role is accepted" 0 "connection OK"
remote 255 "root@1.2.3.4: Permission denied (publickey)." "" preflight
expect "a failed login fails preflight" 255 "The server refused DEPLOY_SSH_KEY"
rm -rf "${T:?}/home"
OUT=$(KG_CI_SSH_DIR="$T/home" bash "$CI_SSH" run status 2>&1); RC=$?
expect "run before prepare is refused" 1 "run 'prepare' first"

echo "through the Cloudflare tunnel:"
TUN=ssh-ci.example.com
CF_ID=0123abcd.access
CF_SECRET=zzzzzzzzzzzzzzzzzzzzzzzz
DEPLOY_SSH_KEY=$KEY DEPLOY_HOST=$TUN DEPLOY_CF_ACCESS_CLIENT_ID=$CF_ID ci prepare
expect "an ID without a secret is refused" 1 "Only one of DEPLOY_CF_ACCESS_CLIENT_ID and DEPLOY_CF_ACCESS_CLIENT_SECRET"
DEPLOY_SSH_KEY=$KEY DEPLOY_HOST=1.2.3.4 DEPLOY_CF_ACCESS_CLIENT_ID=$CF_ID DEPLOY_CF_ACCESS_CLIENT_SECRET=$CF_SECRET ci prepare
expect "an IP address is refused as the tunnel host" 1 "must be the tunnel's hostname"
DEPLOY_SSH_KEY=$KEY DEPLOY_HOST=$TUN DEPLOY_PORT=2222 DEPLOY_KNOWN_HOSTS="$TUN $HOSTKEY" \
  DEPLOY_CF_ACCESS_CLIENT_ID=" $CF_ID " DEPLOY_CF_ACCESS_CLIENT_SECRET=$CF_SECRET ci prepare
expect "tunnel hostname, token and known_hosts are accepted" 0 "via:    Cloudflare Tunnel, Access service token $CF_ID"
[[ $(target TRANSPORT) == cloudflare && $(target PORT) == 22 && $(target STRICT) == yes ]] \
  && ok "transport recorded; the port is the route's business" || no "transport recorded; the port is the route's business"
[[ $(stat -c %a "$T/home/kgkg-access") == 600 ]] && ok "token file is 0600" || no "token file is 0600"
[[ $OUT != *"$CF_SECRET"* ]] && ok "the secret is never printed" || no "the secret is never printed"
DEPLOY_SSH_KEY=$KEY DEPLOY_HOST=1.2.3.4 KG_CI_SSH_DIR="$T/home" bash "$CI_SSH" prepare >/dev/null 2>&1
[[ ! -e $T/home/kgkg-access && $(target TRANSPORT) == ssh ]] && ok "back to direct ssh drops the token file" || no "back to direct ssh drops the token file"

export DEPLOY_HOST=$TUN DEPLOY_KNOWN_HOSTS="$TUN $HOSTKEY" DEPLOY_CF_ACCESS_CLIENT_ID=$CF_ID DEPLOY_CF_ACCESS_CLIENT_SECRET=$CF_SECRET
remote 0 "" "" run stage 0123456789abcdef0123456789abcdef01234567
args=$(<"$FAKE_ARGS")
[[ $args == *$'-o\nProxyCommand=cloudflared access ssh --hostname %h\n'* && $args == *$'\nroot@'"$TUN"$'\nstage '* ]] \
  && ok "ssh goes through cloudflared access ssh to the tunnel host" || no "ssh goes through cloudflared access ssh to the tunnel host ($args)"
[[ $(<"$FAKE_ARGS.env") == "id=$CF_ID secret=$CF_SECRET" ]] && ok "the token reaches the ProxyCommand's environment" || no "the token reaches the ProxyCommand's environment ($(<"$FAKE_ARGS.env"))"
[[ $args != *"$CF_SECRET"* ]] && ok "the secret is not on ssh's command line" || no "the secret is not on ssh's command line"

BH="websocket: bad handshake"$'\n'"Connection closed by UNKNOWN port 65535"
FAKE_CURL_CODE=403 remote 255 "$BH" "" run status
expect "a refused service token is named" 255 "Cloudflare Access refused the service token"
[[ $(<"$FAKE_ARGS.curl") != *"$CF_SECRET"* && $(<"$FAKE_ARGS.curlhdr") == *"CF-Access-Client-Secret: $CF_SECRET"* ]] \
  && ok "the status probe sends the token from a file, not its command line" || no "the status probe sends the token from a file, not its command line"
FAKE_CURL_CODE=302 remote 255 "$BH" "" run status
expect "a policy that is not Service Auth is named" 255 "sent the runner to a login page"
FAKE_CURL_CODE=530 remote 255 "$BH" "" run status
expect "a stopped connector is named" 255 "reached no running tunnel"
[[ $OUT != *fail2ban* ]] && ok "the tunnel's 'Connection closed' is not blamed on fail2ban" || no "the tunnel's 'Connection closed' is not blamed on fail2ban"
FAKE_CURL_CODE=502 remote 255 "$BH" "" run status
expect "anything else still points at the route and the policy" 255 "did not open an SSH session to $TUN (HTTP 502)"
rm -f "$FAKE_ARGS.curl"
remote 255 "dial tcp: lookup $TUN on 127.0.0.53:53: no such host"$'\n'"Connection closed by UNKNOWN port 65535" "" run status
expect "a hostname with no route is named" 255 "The tunnel hostname $TUN does not resolve"
[[ ! -e $FAKE_ARGS.curl ]] && ok "no status probe when the name does not resolve" || no "no status probe when the name does not resolve"
remote 255 "root@$TUN: Permission denied (publickey)." "" run status
expect "sshd's own refusal through the tunnel keeps its message" 255 "The server refused DEPLOY_SSH_KEY"
remote 0 "" $'key role: ci\nlive: abc' preflight
expect "preflight passes through the tunnel" 0 "connection OK"

echo
echo "passed $PASS, failed $FAIL"
(( FAIL == 0 )) || exit 1
echo "CI SSH TESTS PASSED"
