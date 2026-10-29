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

# Stub ssh: records its arguments, replays FAKE_OUT / FAKE_ERR, exits FAKE_RC.
mkdir -p "$T/bin"
cat > "$T/bin/ssh" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$@" > "$FAKE_ARGS"
[[ -n ${FAKE_OUT:-} ]] && printf '%s\n' "$FAKE_OUT"
[[ -n ${FAKE_ERR:-} ]] && printf '%s\n' "$FAKE_ERR" >&2
exit "${FAKE_RC:-0}"
EOF
chmod +x "$T/bin/ssh"

ci() {  # args... -> RC, OUT (stdout+stderr); secrets come from the caller's env
  rm -rf "${T:?}/home"
  OUT=$(KG_CI_SSH_DIR="$T/home" bash "$CI_SSH" "$@" 2>&1)
  RC=$?
}
ok() { printf '  ok    %s\n' "$1"; PASS=$((PASS+1)); }
no() { printf '  FAIL  %s\n       -> rc=%s out=%s\n' "$1" "$RC" "$OUT"; FAIL=$((FAIL+1)); }
expect() {  # description, wanted rc, substring of the output
  if (( RC == $2 )) && [[ $OUT == *"$3"* ]]; then ok "$1"; else no "$1"; fi
}
target() { grep "^$1=" "$T/home/kgkg-target" 2>/dev/null | cut -d= -f2-; }

unset DEPLOY_SSH_KEY DEPLOY_HOST DEPLOY_KNOWN_HOSTS DEPLOY_PORT

echo "missing secrets:"
ci prepare
expect "none set: names both" 1 "missing repository secret(s): DEPLOY_SSH_KEY DEPLOY_HOST"
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
DEPLOY_SSH_KEY=$KEY DEPLOY_HOST=1.2.3.4 ci prepare
[[ $OUT == *"::warning::DEPLOY_KNOWN_HOSTS is not set"* && $(target STRICT) == accept-new ]] \
  && ok "unset: warns and falls back to accept-new" || no "unset: warns and falls back to accept-new"
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

echo
echo "passed $PASS, failed $FAIL"
(( FAIL == 0 )) || exit 1
echo "CI SSH TESTS PASSED"
