#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# One-time setup of the GitHub -> server connection that CI's `stage` job
# uses. Run on the server, as root:
#
#   bash /opt/KGKG/ops/deploy/setup_ci_access.sh             # set it all up
#   bash /opt/KGKG/ops/deploy/setup_ci_access.sh --print     # print the secrets, don't use gh
#   bash /opt/KGKG/ops/deploy/setup_ci_access.sh --rotate    # replace the key
#   bash /opt/KGKG/ops/deploy/setup_ci_access.sh --host 203.0.113.7
#
# Before this file is part of the live release (promotion needs a staging
# run, and staging needs this connection), run it from origin/work; it still
# takes the gates from the live release in /opt/KGKG:
#
#   git -C /opt/KGKG fetch origin work
#   git -C /opt/KGKG show origin/work:ops/deploy/setup_ci_access.sh > /root/setup_ci_access.sh
#   bash /root/setup_ci_access.sh
#
# It
#   1. installs the forced-command gates from the live release,
#   2. creates a dedicated CI key, /root/.ssh/kgkg-github-ci, no passphrase,
#   3. pins it in authorized_keys to kg-ci-gate with `restrict`, so the key
#      can stage and read status and nothing else (no shell, no forwarding),
#   4. proves it: kg-ci-gate refuses `deploy`, and a real SSH login with the
#      key reaches the gate as role ci,
#   5. sets DEPLOY_HOST, DEPLOY_KNOWN_HOSTS and DEPLOY_SSH_KEY (DEPLOY_PORT
#      when sshd is not on 22) on the GitHub repository with `gh` when it is
#      logged in, or prints them to paste into
#      Settings -> Secrets and variables -> Actions.
#
# Safe to re-run: the key is reused unless --rotate, its authorized_keys line
# is replaced rather than duplicated, and authorized_keys is backed up first.
# The CI side of the connection is ops/deploy/ci_ssh.sh.
# ---------------------------------------------------------------------------
set -uo pipefail

PROD=${KG_PROD_DIR:-/opt/KGKG}
BIN=${KG_BIN_DIR:-/usr/local/bin}
SSH_DIR=${KG_SSH_DIR:-/root/.ssh}
HOST_KEY=${KG_HOST_KEY:-/etc/ssh/ssh_host_ed25519_key.pub}
KEY=$SSH_DIR/kgkg-github-ci
AK=$SSH_DIR/authorized_keys
ZERO_SHA=0000000000000000000000000000000000000000

say()  { printf '  %s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }
warn() { printf '  WARNING: %s\n' "$1"; shift; (( $# )) && printf '           %s\n' "$@"; return 0; }
die()  { printf '\nFAILED: %s\n' "$1" >&2; shift; (( $# )) && printf '  %s\n' "$@" >&2; exit 1; }

HOST='' REPO='' ROTATE=0 USE_GH=auto
while (( $# )); do
  case $1 in
    --host)   HOST=${2:-}; [[ -n $HOST ]] || die "--host needs an address"; shift 2 ;;
    --repo)   REPO=${2:-}; [[ -n $REPO ]] || die "--repo needs owner/name"; shift 2 ;;
    --rotate) ROTATE=1; shift ;;
    --print)  USE_GH=no; shift ;;
    -h|--help) sed -n '3,33p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown option '$1' (see --help)" ;;
  esac
done

(( EUID == 0 )) || [[ -n ${KG_SSH_DIR:-} ]] || die "run this as root: CI logs in as root, so the key goes in /root/.ssh"
for c in ssh-keygen awk grep install; do
  command -v "$c" >/dev/null || die "'$c' is not installed"
done

# ---- 1. the gates ----------------------------------------------------------
step "1/5 forced-command gates"
for w in kg-deploy-gate kg-ci-gate; do
  src=$PROD/ops/deploy/$w
  if [[ -f $src ]] && ! cmp -s "$src" "$BIN/$w"; then
    install -m 755 "$src" "$BIN/$w" || die "cannot install $BIN/$w"
    say "installed $BIN/$w from $PROD"
  fi
  [[ -x $BIN/$w ]] || die "$BIN/$w is missing and $src does not exist" \
    "Bring $PROD up to date with the work branch first (kgkg-promote, or ops/deploy/deploy.sh work)."
  say "$BIN/$w ok"
done

# ---- 2. sshd ----------------------------------------------------------------
step "2/5 sshd"
sshd_conf=$(sshd -T 2>/dev/null) || sshd_conf=
port=$(awk '$1 == "port" {print $2; exit}' <<<"$sshd_conf")
port=${port:-22}
if [[ -n $sshd_conf ]]; then
  prl=$(awk '$1 == "permitrootlogin" {print $2; exit}' <<<"$sshd_conf")
  [[ $prl != no ]] || die "sshd has 'PermitRootLogin no', so CI cannot log in as root" \
    "Set 'PermitRootLogin prohibit-password' (keys only) in /etc/ssh/sshd_config, then: systemctl reload ssh"
  [[ $(awk '$1 == "pubkeyauthentication" {print $2; exit}' <<<"$sshd_conf") != no ]] \
    || die "sshd has 'PubkeyAuthentication no'; key logins are impossible"
  password_auth=$(awk '$1 == "passwordauthentication" {print $2; exit}' <<<"$sshd_conf")
  akf=$(awk '$1 == "authorizedkeysfile" {$1=""; print; exit}' <<<"$sshd_conf")
  [[ -z $akf || $akf == *".ssh/authorized_keys"* || $akf == *"%h/.ssh/authorized_keys"* ]] \
    || warn "sshd's AuthorizedKeysFile is '$akf', not ~/.ssh/authorized_keys; the key below may not be read"
  say "port $port, PermitRootLogin ${prl:-?}"
else
  warn "could not read sshd's effective config (sshd -T); assuming port $port"
fi

if [[ -z $HOST ]]; then
  HOST=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i < NF; i++) if ($i == "src") {print $(i+1); exit}}')
  [[ -n $HOST ]] || HOST=$(hostname -I 2>/dev/null | awk '{print $1}')
fi
[[ -n $HOST ]] || die "cannot work out this server's public address; re-run with --host <IP>"
case $HOST in
  10.*|192.168.*|172.1[6-9].*|172.2[0-9].*|172.3[01].*|127.*)
    warn "$HOST is a private address. If GitHub reaches this server through NAT, re-run with --host <public IP>." ;;
esac
say "address GitHub will connect to: $HOST (port $port)"

[[ -r $HOST_KEY ]] || die "no ed25519 host key at $HOST_KEY"
entry=$HOST; (( port == 22 )) || entry="[$HOST]:$port"
KNOWN_HOSTS="$entry $(awk '{print $1" "$2}' "$HOST_KEY")"
if command -v ssh-keyscan >/dev/null; then
  served=$(ssh-keyscan -t ed25519 -p "$port" -T 5 127.0.0.1 2>/dev/null | awk '{print $3}')
  if [[ -n $served && $served != "$(awk '{print $2}' "$HOST_KEY")" ]]; then
    die "sshd serves a different ed25519 host key than $HOST_KEY" "Pass the right file as KG_HOST_KEY=..."
  fi
fi

# ---- 3. the key and its authorized_keys line -------------------------------
step "3/5 CI key"
install -d -m 700 "$SSH_DIR"
old_blob=
if [[ -f $KEY ]] && (( ROTATE )); then
  old_blob=$(ssh-keygen -y -f "$KEY" 2>/dev/null | awk '{print $2}')
  rm -f "$KEY" "$KEY.pub"
  say "rotating: the old key is removed from authorized_keys below"
fi
if [[ ! -f $KEY ]]; then
  ssh-keygen -q -t ed25519 -N '' -C kgkg-github-ci -f "$KEY" || die "ssh-keygen failed"
  say "created $KEY"
else
  say "reusing $KEY (--rotate replaces it)"
fi
pub=$(ssh-keygen -y -P '' -f "$KEY" 2>/dev/null | awk '{print $1" "$2}')
[[ -n $pub ]] || die "cannot read $KEY (it must have no passphrase)"
blob=${pub#* }
fingerprint=$(ssh-keygen -l -f "$KEY" | awk '{print $2}')

line="command=\"$BIN/kg-ci-gate\",restrict $pub kgkg-github-ci"
[[ -f $AK ]] || install -m 600 /dev/null "$AK"
# Settled only when the restricted line is the ONLY line carrying this key:
# sshd uses the first line that matches, so a second, unrestricted copy above
# it would hand the key a root shell.
if [[ $(grep -cF "$blob" "$AK") == 1 ]] && grep -qxF "$line" "$AK"; then
  say "authorized_keys already pins it to kg-ci-gate"
else
  backup=$AK.bak-$(date -u +%Y%m%d%H%M%S)
  cp -p "$AK" "$backup" || die "cannot back up $AK"
  tmp=$(mktemp "$SSH_DIR/.authorized_keys.XXXXXX") || die "mktemp failed"
  # Drop any earlier line for this key (or the rotated one), whatever it was
  # pinned to, then add the one line that decides what it may do.
  grep -vF -e "$blob" ${old_blob:+-e "$old_blob"} "$AK" > "$tmp"
  (( $? <= 1 )) || { rm -f "$tmp"; die "cannot read $AK"; }
  printf '%s\n' "$line" >> "$tmp"
  chmod 600 "$tmp" && mv "$tmp" "$AK" || die "cannot write $AK (backup: $backup)"
  say "pinned the key to $BIN/kg-ci-gate in $AK (backup: $backup)"
fi
say "key fingerprint: $fingerprint (CI prints the same in its 'stage' job)"
while IFS= read -r other; do
  say "other key pinned to kg-deploy-gate (can promote; a person's key, never put it in GitHub): ${other##* }"
done < <(grep -F 'kg-deploy-gate' "$AK" | grep -vF "$blob")

# ---- 4. prove it -------------------------------------------------------------
step "4/5 test"
out=$(KG_GATE_DRYRUN=1 KG_GATE_LOG=/dev/null SSH_ORIGINAL_COMMAND="deploy $ZERO_SHA" "$BIN/kg-ci-gate" 2>&1)
rc=$?
(( rc != 0 )) && [[ $out == *denied* ]] || die "kg-ci-gate did not refuse 'deploy' (rc=$rc): $out"
say "kg-ci-gate refuses deploy: ok"

if command -v ssh >/dev/null; then
  # Ask for the one thing only kg-ci-gate refuses with this answer. A shell
  # would try to run `deploy`, the operator gate would accept the verb, and
  # neither prints "role 'ci' may not 'deploy'". Nothing can be deployed:
  # the sha is all zeros, which is on no branch.
  login() {  # address -> sets LOGIN_OUT, returns ssh's status
    LOGIN_OUT=$(ssh -n -F none -i "$KEY" -p "$port" -o BatchMode=yes -o IdentitiesOnly=yes \
      -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o GlobalKnownHostsFile=/dev/null \
      -o LogLevel=ERROR -o ConnectTimeout=10 "root@$1" "deploy $ZERO_SHA" 2>&1)
  }
  login 127.0.0.1; rc=$?
  if (( rc == 255 )) && [[ $LOGIN_OUT == *refused* || $LOGIN_OUT == *"timed out"* ]]; then
    login "$HOST"; rc=$?
  fi
  if (( rc == 255 )) && [[ $LOGIN_OUT == *"Permission denied"* ]]; then
    die "sshd refused the new key for root: $LOGIN_OUT" \
      "Check AllowUsers/AllowGroups/DenyUsers and any Match block in /etc/ssh/sshd_config." \
      "sshd's log: journalctl -u ssh -n 30"
  elif (( rc == 255 )); then
    warn "could not log in over SSH from this machine to test it: $LOGIN_OUT"
  elif [[ $LOGIN_OUT == *"role 'ci' may not 'deploy'"* ]]; then
    say "SSH login with the key lands in kg-ci-gate as role ci, which refuses deploy: ok"
  else
    die "an SSH login with the key does not land in kg-ci-gate as role ci (exit $rc): $LOGIN_OUT" \
      "Look for another line with this key in $AK or in any other AuthorizedKeysFile."
  fi
else
  warn "no ssh client here, so the login itself was not tested"
fi

# GitHub's runners come from changing addresses, so SSH has to accept any
# source. That is only reasonable with password logins off: the CI key is
# harmless, but every other account would face the whole internet.
if [[ ${password_auth:-} == yes ]]; then
  warn "sshd accepts passwords (PasswordAuthentication yes). Before port $port is open to every address," \
       "set 'PasswordAuthentication no' in /etc/ssh/sshd_config (check you can log in with a key first), then: systemctl reload ssh"
fi
if command -v ufw >/dev/null && ufw status 2>/dev/null | grep -q '^Status: active'; then
  ufw status | grep -qE "^($port(/tcp)?|OpenSSH)[[:space:]]+(ALLOW|LIMIT)([[:space:]]+IN)?[[:space:]]+Anywhere" \
    || warn "ufw is active and does not allow port $port from anywhere, so GitHub cannot connect." \
            "Once password logins are off: ufw limit $port/tcp"
fi
if command -v fail2ban-client >/dev/null && fail2ban-client ping >/dev/null 2>&1; then
  say "fail2ban is running; if CI reports 'Connection closed', check: fail2ban-client status sshd"
fi

# ---- 5. hand the credential to GitHub --------------------------------------
step "5/5 GitHub secrets"
if [[ -z $REPO ]]; then
  url=$(git -C "$PROD" remote get-url origin 2>/dev/null)
  [[ $url =~ github\.com[:/]([^/]+)/([^/]+)$ ]] && REPO=${BASH_REMATCH[1]}/${BASH_REMATCH[2]%.git}
fi
REPO=${REPO:-mjsn800403/KGKG}
secrets_url="https://github.com/$REPO/settings/secrets/actions"
runs_url="https://github.com/$REPO/actions/workflows/ci.yml?query=branch%3Awork"

if [[ $USE_GH != no ]] && command -v gh >/dev/null && gh auth status >/dev/null 2>&1; then
  gh secret set DEPLOY_HOST        --repo "$REPO" --body "$HOST" \
    && gh secret set DEPLOY_KNOWN_HOSTS --repo "$REPO" --body "$KNOWN_HOSTS" \
    && gh secret set DEPLOY_SSH_KEY  --repo "$REPO" < "$KEY" \
    || die "gh could not set the secrets on $REPO (the account needs admin rights on it)" \
           "Re-run with --print to paste them by hand instead."
  if (( port != 22 )); then
    gh secret set DEPLOY_PORT --repo "$REPO" --body "$port" || die "gh could not set DEPLOY_PORT"
  else
    gh secret delete DEPLOY_PORT --repo "$REPO" >/dev/null 2>&1 || true
  fi
  say "DEPLOY_HOST, DEPLOY_KNOWN_HOSTS and DEPLOY_SSH_KEY are set on $REPO"
  failed=$(gh run list --repo "$REPO" --workflow ci.yml --branch work --limit 1 \
             --json databaseId,conclusion --jq '.[0] | select(.conclusion == "failure") | .databaseId' 2>/dev/null)
  echo
  echo "Done. Push to work, or re-run the last failed CI run on work:"
  [[ -n $failed ]] && echo "  gh run rerun $failed --repo $REPO --failed"
  echo "  $runs_url"
  exit 0
fi

cat <<EOF

Done on the server. Last step, in the browser (gh is not logged in here):
open $secrets_url
and add each of these with "New repository secret" (name, then value):

----- name: DEPLOY_HOST -------------------------------------------------
$HOST
----- name: DEPLOY_KNOWN_HOSTS ------------------------------------------
$KNOWN_HOSTS
----- name: DEPLOY_SSH_KEY  (copy from -----BEGIN to -----END, both included)
$(cat "$KEY")
EOF
(( port == 22 )) || printf -- '----- name: DEPLOY_PORT -------------------------------------------------\n%s\n' "$port"
cat <<EOF
-------------------------------------------------------------------------

This key can only stage and read status; it cannot deploy to production.
Keep it in that secret and nowhere else.
Then push to work, or re-run the failed 'stage' job: $runs_url
EOF
