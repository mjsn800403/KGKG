#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# One-time setup of the GitHub -> server connection that CI's `stage` job
# uses. Run on the server, as root:
#
#   bash /opt/KGKG/ops/deploy/setup_ci_access.sh --tunnel ssh-ci.example.com
#        through a Cloudflare Tunnel (recommended): port 22 stays closed
#   bash /opt/KGKG/ops/deploy/setup_ci_access.sh
#        direct SSH to this server's public address (port 22 must be open)
#
#   --print          print the secrets instead of setting them with gh
#   --rotate         replace the CI key
#   --host <ip>      direct mode: the address GitHub connects to
#
# Before this file is part of the live release (promotion needs a staging
# run, and staging needs this connection), run it from origin/work; it still
# takes the gates from the live release in /opt/KGKG:
#
#   git -C /opt/KGKG fetch origin work
#   git -C /opt/KGKG show origin/work:ops/deploy/setup_ci_access.sh > /root/setup_ci_access.sh
#   bash /root/setup_ci_access.sh --tunnel ssh-ci.example.com
#
# It
#   1. installs the forced-command gates from the live release,
#   2. checks sshd,
#   3. creates a dedicated CI key, /root/.ssh/kgkg-github-ci, no passphrase,
#      and pins it in authorized_keys to kg-ci-gate with `restrict`, so the
#      key can stage and read status and nothing else,
#   4. proves a real SSH login with the key lands in kg-ci-gate as role ci,
#   5. tunnel: installs cloudflared, starts the connector if it is not
#      running (asks for the tunnel token), asks for the Access service
#      token, and proves the whole path - Cloudflare's edge, Access, the
#      tunnel, sshd, the gate - by logging in through it with the host key
#      pinned; then checks that Access protects the hostname at all.
#      direct: warns about password logins, ufw and fail2ban,
#   6. sets the secrets on the GitHub repository with `gh` when it is logged
#      in, or prints them to paste into Settings -> Secrets and variables ->
#      Actions: DEPLOY_HOST, DEPLOY_KNOWN_HOSTS, DEPLOY_SSH_KEY, plus
#      DEPLOY_CF_ACCESS_CLIENT_ID/SECRET (tunnel) or DEPLOY_PORT (direct, not 22).
#
# Secrets it asks for may be given in the environment instead:
# CF_TUNNEL_TOKEN, CF_ACCESS_CLIENT_ID, CF_ACCESS_CLIENT_SECRET.
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
CF_DOCS=https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/

say()  { printf '  %s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }
warn() { printf '  WARNING: %s\n' "$1"; shift; (( $# )) && printf '           %s\n' "$@"; return 0; }
die()  { printf '\nFAILED: %s\n' "$1" >&2; shift; (( $# )) && printf '  %s\n' "$@" >&2; exit 1; }

HOST='' TUNNEL='' REPO='' ROTATE=0 USE_GH=auto
while (( $# )); do
  case $1 in
    --tunnel) TUNNEL=${2:-}; [[ -n $TUNNEL ]] || die "--tunnel needs the tunnel's hostname"; shift 2 ;;
    --host)   HOST=${2:-}; [[ -n $HOST ]] || die "--host needs an address"; shift 2 ;;
    --repo)   REPO=${2:-}; [[ -n $REPO ]] || die "--repo needs owner/name"; shift 2 ;;
    --rotate) ROTATE=1; shift ;;
    --print)  USE_GH=no; shift ;;
    -h|--help) sed -n '3,/^# ---/p' "$0" | sed '$d; s/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown option '$1' (see --help)" ;;
  esac
done
if [[ -n $TUNNEL ]]; then
  [[ -z $HOST ]] || die "--host and --tunnel do not go together: with the tunnel, GitHub connects to the tunnel's hostname"
  [[ $TUNNEL =~ ^[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$ && ! $TUNNEL =~ ^[0-9.]+$ ]] \
    || die "--tunnel takes a hostname like ssh-ci.example.com, not '$TUNNEL'"
fi

(( EUID == 0 )) || [[ -n ${KG_SSH_DIR:-} ]] || die "run this as root: CI logs in as root, so the key goes in /root/.ssh"
for c in ssh-keygen awk grep install; do
  command -v "$c" >/dev/null || die "'$c' is not installed"
done

# A secret from the environment, or typed (not echoed) at the terminal.
ask_secret() {  # VAR "what it is"
  local v=${!1:-}
  if [[ -z $v ]]; then
    [[ -t 0 ]] || die "$1 is not set and there is no terminal to ask for it on" \
      "Give it in the environment: $1=... bash $0 ..."
    IFS= read -rsp "  $2: " v || die "could not read $1"
    echo
  fi
  v=${v//[[:space:]]/}   # none of these tokens contains spaces; drop pasted newlines
  [[ -n $v ]] || die "$1 is empty"
  printf -v "$1" '%s' "$v"
}

# ---- 1. the gates ----------------------------------------------------------
step "1/6 forced-command gates"
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
step "2/6 sshd"
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

if [[ -n $TUNNEL ]]; then
  # ssh on the runner looks the host key up under the name it dials.
  HOST=$TUNNEL
  entry=$TUNNEL
  say "GitHub will connect through the tunnel hostname $TUNNEL"
else
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
  entry=$HOST; (( port == 22 )) || entry="[$HOST]:$port"
fi

[[ -r $HOST_KEY ]] || die "no ed25519 host key at $HOST_KEY"
KNOWN_HOSTS="$entry $(awk '{print $1" "$2}' "$HOST_KEY")"
if command -v ssh-keyscan >/dev/null; then
  served=$(ssh-keyscan -t ed25519 -p "$port" -T 5 127.0.0.1 2>/dev/null | awk '{print $3}')
  if [[ -n $served && $served != "$(awk '{print $2}' "$HOST_KEY")" ]]; then
    die "sshd serves a different ed25519 host key than $HOST_KEY" "Pass the right file as KG_HOST_KEY=..."
  fi
fi

# ---- 3. the key and its authorized_keys line -------------------------------
step "3/6 CI key"
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

# ---- 4. prove it locally -----------------------------------------------------
step "4/6 test on this machine"
out=$(KG_GATE_DRYRUN=1 KG_GATE_LOG=/dev/null SSH_ORIGINAL_COMMAND="deploy $ZERO_SHA" "$BIN/kg-ci-gate" 2>&1)
rc=$?
(( rc != 0 )) && [[ $out == *denied* ]] || die "kg-ci-gate did not refuse 'deploy' (rc=$rc): $out"
say "kg-ci-gate refuses deploy: ok"

command -v ssh >/dev/null || die "no ssh client on this machine, so the login cannot be tested"
# Ask for the one thing only kg-ci-gate refuses with this answer. A shell
# would try to run `deploy`, the operator gate would accept the verb, and
# neither prints "role 'ci' may not 'deploy'". Nothing can be deployed: the
# sha is all zeros, which is on no branch.
GATE_ANSWER="role 'ci' may not 'deploy'"
login() {  # address port [extra ssh options...] -> sets LOGIN_OUT, returns ssh's status
  local addr=$1 p=$2; shift 2
  LOGIN_OUT=$(timeout 60 ssh -n -F none -i "$KEY" -p "$p" -o BatchMode=yes -o IdentitiesOnly=yes \
    -o GlobalKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=20 "$@" \
    "root@$addr" "deploy $ZERO_SHA" 2>&1)
}
local_login() { login "$1" "$port" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null; }
local_login 127.0.0.1; rc=$?
if [[ -z $TUNNEL ]] && (( rc == 255 )) && [[ $LOGIN_OUT == *refused* || $LOGIN_OUT == *"timed out"* ]]; then
  local_login "$HOST"; rc=$?
fi
if (( rc == 255 )) && [[ $LOGIN_OUT == *"Permission denied"* ]]; then
  die "sshd refused the new key for root: $LOGIN_OUT" \
    "Check AllowUsers/AllowGroups/DenyUsers and any Match block in /etc/ssh/sshd_config." \
    "sshd's log: journalctl -u ssh -n 30"
elif (( rc == 255 )); then
  if [[ -n $TUNNEL ]]; then
    die "cannot log in to sshd on 127.0.0.1 port $port: $LOGIN_OUT" \
      "The tunnel connects to sshd on this machine, so it must listen on localhost."
  fi
  warn "could not log in over SSH from this machine to test it: $LOGIN_OUT"
elif [[ $LOGIN_OUT == *"$GATE_ANSWER"* ]]; then
  say "SSH login with the key lands in kg-ci-gate as role ci, which refuses deploy: ok"
else
  die "an SSH login with the key does not land in kg-ci-gate as role ci (exit $rc): $LOGIN_OUT" \
    "Look for another line with this key in $AK or in any other AuthorizedKeysFile."
fi

# ---- 5. the way in -----------------------------------------------------------
if [[ -n $TUNNEL ]]; then
  step "5/6 Cloudflare Tunnel $TUNNEL"
  if ! command -v cloudflared >/dev/null; then
    command -v apt-get >/dev/null || die "cloudflared is not installed and this is not an apt system" "Install it: $CF_DOCS"
    say "installing cloudflared from Cloudflare's signed apt repository"
    { install -d -m 0755 /usr/share/keyrings &&
      curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg -o /usr/share/keyrings/cloudflare-main.gpg &&
      echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main' \
        > /etc/apt/sources.list.d/cloudflared.list &&
      apt-get update -qq && apt-get install -y -qq cloudflared; } >/dev/null 2>&1 \
      || die "could not install cloudflared" "Install it by hand: $CF_DOCS"
  fi
  say "$(cloudflared --version 2>/dev/null | head -1)"

  if systemctl is-active --quiet cloudflared 2>/dev/null; then
    say "the tunnel connector (systemd unit cloudflared) is running"
  else
    say "the tunnel connector is not running on this machine; installing it"
    ask_secret CF_TUNNEL_TOKEN "Tunnel token (the long value after 'cloudflared service install' in the dashboard)"
    cloudflared service install "$CF_TUNNEL_TOKEN" >/dev/null 2>&1 \
      || die "cloudflared service install failed" "Check the token (Zero Trust -> Networks -> Tunnels -> your tunnel)."
    for _ in $(seq 15); do systemctl is-active --quiet cloudflared && break; sleep 2; done
    systemctl is-active --quiet cloudflared || die "the cloudflared service did not start" "journalctl -u cloudflared -n 30"
    say "installed and started the connector"
  fi

  ask_secret CF_ACCESS_CLIENT_ID "Access service token Client ID"
  ask_secret CF_ACCESS_CLIENT_SECRET "Access service token Client Secret"

  # Through Cloudflare's edge and back to this machine, exactly as the runner
  # will: same ProxyCommand, same token, and this server's host key pinned,
  # so a route that leads to some other sshd fails here instead of in CI.
  KH_TMP=$(mktemp); HDR=$(mktemp)
  trap 'rm -f "$KH_TMP" "$HDR"' EXIT
  printf '%s\n' "$KNOWN_HOSTS" > "$KH_TMP"
  chmod 600 "$HDR"
  printf 'CF-Access-Client-Id: %s\nCF-Access-Client-Secret: %s\n' "$CF_ACCESS_CLIENT_ID" "$CF_ACCESS_CLIENT_SECRET" > "$HDR"
  edge_login() {
    # Port 22 as on the runner: through a ProxyCommand the port only picks the
    # known_hosts entry, and DEPLOY_KNOWN_HOSTS carries the bare hostname.
    TUNNEL_SERVICE_TOKEN_ID=$CF_ACCESS_CLIENT_ID TUNNEL_SERVICE_TOKEN_SECRET=$CF_ACCESS_CLIENT_SECRET \
      login "$TUNNEL" 22 -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$KH_TMP" \
      -o "ProxyCommand=cloudflared access ssh --hostname %h"
  }
  # A connector that has just started, or a route that was just added, can
  # take a few seconds to answer.
  for attempt in 1 2 3 4; do
    edge_login; rc=$?
    [[ $LOGIN_OUT == *"$GATE_ANSWER"* ]] && break
    [[ $LOGIN_OUT == *"bad handshake"* || $LOGIN_OUT == *"Bad Gateway"* ]] && (( attempt < 4 )) || break
    sleep 5
  done
  if [[ $LOGIN_OUT == *"$GATE_ANSWER"* ]]; then
    say "through Cloudflare: Access let the token in, the tunnel reached sshd here, the key landed in kg-ci-gate: ok"
  elif [[ $LOGIN_OUT == *"Host key verification failed"* || $LOGIN_OUT == *"IDENTIFICATION HAS CHANGED"* ]]; then
    die "$TUNNEL leads to a different SSH server than this one" \
      "Point the hostname's route at SSH localhost:$port on the tunnel whose connector runs here."
  else
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 -H "@$HDR" "https://$TUNNEL/" 2>/dev/null)
    case ${code:-000} in
      000)             hint="$TUNNEL does not resolve: add it as a public hostname of the tunnel (type SSH, URL localhost:$port)." ;;
      301|302|303|307) hint="Access sends this token to a login page: the application's policy must have action 'Service Auth' and include the token." ;;
      401|403)         hint="Access refuses this token: check the Client ID and Secret, and that the policy includes this token." ;;
      530)             hint="Cloudflare reaches no running connector for $TUNNEL: is it a route of the tunnel whose connector runs here? (journalctl -u cloudflared -n 30)" ;;
      *)               hint="HTTP $code from $TUNNEL: check that it routes to SSH localhost:$port." ;;
    esac
    die "logging in through $TUNNEL did not reach kg-ci-gate (exit $rc): $LOGIN_OUT" "$hint"
  fi

  # Without the token, Access must stop the request; otherwise the hostname
  # is an open door to sshd for anyone with cloudflared.
  redirect=$(curl -s -o /dev/null -w '%{http_code} %{redirect_url}' --max-time 15 "https://$TUNNEL/" 2>/dev/null)
  if [[ $redirect == *cloudflareaccess.com* || $redirect == 403* || $redirect == 401* ]]; then
    say "without the token, Access turns requests away: ok"
  else
    warn "no Access application protects $TUNNEL (answer without a token: ${redirect:-none})." \
         "Anyone with cloudflared can reach sshd through it. Add a self-hosted Access application for" \
         "$TUNNEL with one policy: action 'Service Auth', include this service token."
  fi
  say "port $port can stay closed to the internet: GitHub comes in through the tunnel"
else
  step "5/6 exposure (direct SSH)"
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
              "Once password logins are off: ufw limit $port/tcp. Or use --tunnel, which needs no open port."
  fi
  if command -v fail2ban-client >/dev/null && fail2ban-client ping >/dev/null 2>&1; then
    say "fail2ban is running; if CI reports 'Connection closed', check: fail2ban-client status sshd"
  fi
  say "checked"
fi

# ---- 6. hand the credential to GitHub --------------------------------------
step "6/6 GitHub secrets"
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
  if [[ -n $TUNNEL ]]; then
    gh secret set DEPLOY_CF_ACCESS_CLIENT_ID --repo "$REPO" --body "$CF_ACCESS_CLIENT_ID" \
      && printf '%s' "$CF_ACCESS_CLIENT_SECRET" | gh secret set DEPLOY_CF_ACCESS_CLIENT_SECRET --repo "$REPO" \
      || die "gh could not set the Access token secrets"
    gh secret delete DEPLOY_PORT --repo "$REPO" >/dev/null 2>&1 || true
    set_list="DEPLOY_HOST, DEPLOY_KNOWN_HOSTS, DEPLOY_SSH_KEY and DEPLOY_CF_ACCESS_CLIENT_ID/SECRET"
  else
    for s in DEPLOY_CF_ACCESS_CLIENT_ID DEPLOY_CF_ACCESS_CLIENT_SECRET; do
      gh secret delete "$s" --repo "$REPO" >/dev/null 2>&1 || true
    done
    if (( port != 22 )); then
      gh secret set DEPLOY_PORT --repo "$REPO" --body "$port" || die "gh could not set DEPLOY_PORT"
    else
      gh secret delete DEPLOY_PORT --repo "$REPO" >/dev/null 2>&1 || true
    fi
    set_list="DEPLOY_HOST, DEPLOY_KNOWN_HOSTS and DEPLOY_SSH_KEY"
  fi
  say "$set_list are set on $REPO"
  failed=$(gh run list --repo "$REPO" --workflow ci.yml --branch work --limit 1 \
             --json databaseId,conclusion --jq '.[0] | select(.conclusion == "failure") | .databaseId' 2>/dev/null)
  echo
  echo "Done. Push to work, or re-run the last failed CI run on work:"
  [[ -n $failed ]] && echo "  gh run rerun $failed --repo $REPO --failed"
  echo "  $runs_url"
  exit 0
fi

secret() { printf -- '----- name: %s %s\n%s\n' "$1" "$(printf '%*s' $(( 60 - ${#1} )) '' | tr ' ' -)" "$2"; }
echo
echo "Done on the server. Last step, in the browser (gh is not logged in here):"
echo "open $secrets_url"
echo "and add each of these with \"New repository secret\" (name, then value):"
echo
secret DEPLOY_HOST "$HOST"
secret DEPLOY_KNOWN_HOSTS "$KNOWN_HOSTS"
echo "----- name: DEPLOY_SSH_KEY  (copy from -----BEGIN to -----END, both included)"
cat "$KEY"
if [[ -n $TUNNEL ]]; then
  secret DEPLOY_CF_ACCESS_CLIENT_ID "$CF_ACCESS_CLIENT_ID"
  secret DEPLOY_CF_ACCESS_CLIENT_SECRET "$CF_ACCESS_CLIENT_SECRET"
elif (( port != 22 )); then
  secret DEPLOY_PORT "$port"
fi
cat <<EOF
-------------------------------------------------------------------------

This key can only stage and read status; it cannot deploy to production.
Keep it in that secret and nowhere else.
EOF
if [[ -n $TUNNEL ]]; then
  echo "If DEPLOY_PORT is set from an earlier direct setup, delete it."
else
  echo "If DEPLOY_CF_ACCESS_CLIENT_ID/SECRET are set from an earlier tunnel setup, delete them."
fi
echo "Then push to work, or re-run the failed 'stage' job: $runs_url"
