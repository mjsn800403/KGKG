#!/bin/sh
# Rotate Umami's default admin password and register kgtechvault.com.
set -e
cd /opt/umami
psql() { docker compose exec -T db psql -U umami -d umami -tAc "$1"; }

if [ ! -f admin.secret ]; then
  umask 077
  PW=$(openssl rand -base64 18 | tr -d '/+=')
  # bcrypt on the host (the Umami image bundles it out of reach of `require`)
  HASH=$(PW="$PW" python3 -c 'import bcrypt,os;print(bcrypt.hashpw(os.environ["PW"].encode(),bcrypt.gensalt(10)).decode())')
  [ -n "$HASH" ] || exit 1
  psql "update \"user\" set password='$HASH' where username='admin'"
  printf 'username=admin\npassword=%s\n' "$PW" > admin.secret
  echo "admin password rotated"
fi

WID=$(psql "select website_id from website where domain='kgtechvault.com' and deleted_at is null limit 1")
if [ -z "$WID" ]; then
  WID=$(cat /proc/sys/kernel/random/uuid)
  UID_=$(psql "select user_id from \"user\" where username='admin'")
  psql "insert into website (website_id, name, domain, user_id, created_at) values ('$WID','KGTechVault','kgtechvault.com','$UID_', now())"
fi
echo "website_id=$WID"
