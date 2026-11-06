# Deploying KGKG

Manual, on the server: `bash /opt/KGKG/ops/deploy/deploy.sh work` (also `--staging`, `--rollback`, `--reload`, `--status`).
The full description is in `docs/11-operations-deployment.md` §11.3.

## How a change reaches production
1. Push to `work`.
2. CI runs (`.github/workflows/ci.yml`). When everything is green, its `stage` job logs in to the
   server and stages that exact commit: images built, run against a sanitized copy of the
   production database, smoke-tested. Production is not touched.
3. A person promotes it, on the server: `kgkg-promote <sha>` (or bare, for what CI last staged).

CI can never promote. Its key is pinned on the server to `kg-ci-gate`, which only knows
`stage` and `status`.

## Connecting GitHub to the server (once)

> **Live configuration, 2026-10-29:** direct SSH on the public port 22, **not** the tunnel.
> `cloudflared` is not installed on the server and the `stage` job logs `direct SSH: not needed`.
> Key-only sshd and `fail2ban` are what stand in front of that port today. The tunnel below is
> the intended design and the recommended next step; until it is run, read this section as a
> plan, not as a description. `docs/11-operations-deployment.md` carries the same note with the
> commands that establish it.

The design: GitHub reaches the server's SSH through a **Cloudflare Tunnel** — the server dials out to
Cloudflare, GitHub's runner comes in through `cloudflared` with a Cloudflare Access service token,
and port 22 stays closed to the internet. The domain is already on Cloudflare, so nothing new to
sign up for. (Direct SSH to a public port also works: see the end of this section.)

### 1. In Cloudflare (Zero Trust dashboard, about 5 minutes)
1. **Networks → Tunnels → Create a tunnel**, type *Cloudflared*, name `kgkg-ci`. On the install
   page, copy the **token**: the long value after `cloudflared service install`. You don't need to
   run that command; the script below does.
2. In the tunnel, add a **public hostname** (route): `ssh-ci` . `kgtechvault.com`, service type
   **SSH**, URL `localhost:22`.
3. **Access controls → Service credentials → Service Tokens → Create service token**, name `kgkg-github-ci`.
   Copy the **Client ID** and **Client Secret** (the secret is shown only once). Note its duration:
   when it expires, CI says so and you repeat this step and step 2 below.
4. **Access controls → Applications → Add an application → Self-hosted**: domain `ssh-ci.kgtechvault.com`,
   one policy with action **Service Auth** that includes the service token `kgkg-github-ci`.

Cloudflare's guide, if the menus have moved: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/

### 2. On the server, as root
The first time, the script is not in the live release yet (promoting needs a staging run, and
staging needs this connection), so take it from `origin/work` without promoting anything:

```bash
git -C /opt/KGKG fetch origin work
git -C /opt/KGKG show origin/work:ops/deploy/setup_ci_access.sh > /root/setup_ci_access.sh
bash /root/setup_ci_access.sh --tunnel ssh-ci.kgtechvault.com
```

(Later: `bash /opt/KGKG/ops/deploy/setup_ci_access.sh --tunnel ssh-ci.kgtechvault.com`.)

It creates a dedicated key (`/root/.ssh/kgkg-github-ci`), pins it to `kg-ci-gate` with `restrict`,
installs `cloudflared` and the tunnel connector, asks for the tunnel token (only if the connector
isn't running yet) and the service token (typed, not shown), and then **logs in through Cloudflare
back to this server** exactly as CI will, with the host key pinned. It also checks that Access turns
away requests without the token. Then:

* if `gh` is logged in on the server (`gh auth login`), it sets the secrets itself;
* otherwise it prints them. Open **Settings → Secrets and variables → Actions → New repository
  secret** (https://github.com/mjsn800403/KGKG/settings/secrets/actions) and add each one:

| Name | Value |
|---|---|
| `DEPLOY_HOST` | the tunnel hostname, `ssh-ci.kgtechvault.com` |
| `DEPLOY_KNOWN_HOSTS` | this server's host key line, so the runner knows it reached this server |
| `DEPLOY_SSH_KEY` | the private key, from `-----BEGIN` to `-----END`, both lines included |
| `DEPLOY_CF_ACCESS_CLIENT_ID` | the service token's Client ID |
| `DEPLOY_CF_ACCESS_CLIENT_SECRET` | the service token's Client Secret |

### 3. Run CI
Re-run the failed `stage` job, or push to `work`.

The script is safe to re-run. `--rotate` replaces the key (paste the new one into `DEPLOY_SSH_KEY`),
`--print` prints instead of using `gh`. The secrets can also come from the environment instead of
being typed: `CF_TUNNEL_TOKEN`, `CF_ACCESS_CLIENT_ID`, `CF_ACCESS_CLIENT_SECRET`.

### Without the tunnel: direct SSH
`bash /root/setup_ci_access.sh` (no `--tunnel`) sets up the same key for a direct connection to the
server's public address instead. Port 22 must then accept connections from anywhere (GitHub's
runners use changing addresses), so turn password logins off first (`PasswordAuthentication no`;
the script warns if they are on) and use `ufw limit 22/tcp`. Delete the two
`DEPLOY_CF_ACCESS_CLIENT_*` secrets if you switch from the tunnel to this.

## When the `stage` job fails
`ops/deploy/ci_ssh.sh` turns each failure into an error on the run page. The common ones:

| CI says | Fix |
|---|---|
| missing repository secret(s) | Run `setup_ci_access.sh` as above. |
| holds a public key / not a usable private key | Paste the private key file, BEGIN and END lines included. |
| refused DEPLOY_SSH_KEY | The secret and the server disagree. Compare the fingerprint CI prints with the one the script printed; re-run the script and paste again. |
| host key does not match | The server was rebuilt or its host keys changed: re-run the script for the new `DEPLOY_KNOWN_HOSTS`. |
| Cloudflare Access refused the service token | The token expired or was revoked: create a new one (Cloudflare step 3), add it to the policy, re-run the script. |
| sent the runner to a login page | The Access application's policy is not *Service Auth* with this token. |
| reached no running tunnel | The connector on the server is down: `systemctl status cloudflared`. |
| tunnel hostname does not resolve | The tunnel has no public hostname for `DEPLOY_HOST` (Cloudflare step 2). |
| cannot reach … port 22 | Direct mode only: a firewall. See "Without the tunnel" above, or switch to the tunnel. |
| closed the SSH connection before authentication | Direct mode only: fail2ban banned a runner, `fail2ban-client status sshd`. |
| could promote to production | The CI key is pinned to `kg-deploy-gate`. Re-run the script; it repins it to `kg-ci-gate`. |
| could not fetch origin/work | The server's own GitHub access: `git -C /opt/KGKG fetch origin work`. |

## Staging isolation (read-only vector data, own database)

Staging runs the commit under test against a sanitized copy of the portal database. It used to do so
with the **production** database login and with the production warehouses mounted read-write. It now
uses its own PostgreSQL role and read-only warehouse mounts, and it **refuses to start** if either is
missing or too wide.

| | production backend | staging backend |
|---|---|---|
| PostgreSQL login | `kgkg` (`.env.prod`) | `kgkg_stg`, from `/opt/KGKG_staging/isolation.env` (overrides `KG_PG_USER` / `KG_PG_PASSWORD`) |
| `kgkg_vec` (car manuals, RAG) | SELECT | SELECT only: no INSERT/UPDATE/DELETE/TRUNCATE, no CREATE |
| every other database (portal `kgkg`, QA, trial ...) | owner | no privileges |
| `kgkg_staging` (the sanitized copy) | n/a | owner (migrations, QA token, smoke tests) |
| `Database_warehouse`, `static_warehouse` | read-write | mounted `:ro`, confirmed with `docker inspect` after start |
| `/opt/KGKG/KG_backend/.env.prod` | mounted read-only | **not mounted**; `RAG_PGVEC_DSN`, `KG_CARDB_PG_DSN`, `KG_CARDB_ADMIN_DSN` are blanked so every connection is built from the staging login |

What this protects against: a *mistake* in the code under test (a wrong database name, a write path nobody
expected). It does not contain *malicious* test code: the container still runs as root on the host network,
still receives the rest of `.env.prod` as environment (secret key, admin token) and can reach loopback
services. The QA stack (`qa/stack.sh`) shares `containers.sh` and is not changed by this.

What staging genuinely writes: its own database copy, `/data/db` (feedback store, logs, the `kgkg_staging`
SQLite files) and `/tmp` (the rate-limit store). It never needs to write the vector database or the
warehouses: the code that does (`cardb_pg.adopt`, the `pgcar` pipeline stage) is started through the
host-job spool, and staging's spool is one nobody serves.

**One-time setup** (as root on the server; changes the database, so it is an operator action):

    cd /opt/KGKG && bash ops/deploy/staging_isolation.sh setup      # --rotate for a new password
    bash ops/deploy/staging_isolation.sh check                      # read-only, any time

`setup` runs `staging_role.sql` (idempotent), writes `/opt/KGKG_staging/isolation.env` (root, mode 600)
and runs the same check `deploy.sh --staging` runs. A new car needs no re-run: default privileges give
the role SELECT on whatever the loader (`root`) creates. PostgreSQL 14 and older let PUBLIC create in
schema `public`; run `REVOKE CREATE ON SCHEMA public FROM PUBLIC` in each database there (the check
reports it). Production runs 16, where that is already the default. The clone runs `CREATE EXTENSION`
as the staging role, so every extension in the portal database must be a *trusted* one (today it has
only `plpgsql`).

**Activation order.** The live tree's `deploy.sh` runs staging *and* the staging step of every full
promote, so the new logic goes live when a release containing it is promoted, and from then on **both
refuse to run until the setup below has been done**:

1. `staging_isolation.sh setup` on the server, **before** promoting the release that contains this.
2. Merge the change to `work`. CI stages it with the *old* `deploy.sh`; nothing changes yet.
3. `kgkg-promote <sha>`. The next staging run uses the isolated path.
4. Watch the first staging run (`kg-deploy-gate status`, the `stage` job). If the check, the clone or the
   read-only mounts fail it, staging stops and production is untouched.

**Rollback.** `kgkg-promote <older sha>` does not work: the promote only fast-forwards. Use
`bash /opt/KGKG/ops/deploy/deploy.sh --rollback` (resets the live tree to the previous release and swaps
the containers back; the old `deploy.sh` ignores `isolation.env`), or revert the change and promote the
revert. To remove the role as well, in this order:

    psql -d postgres -c 'DROP DATABASE IF EXISTS kgkg_staging'
    psql -d kgkg_vec -c 'DROP OWNED BY kgkg_stg'
    psql -d postgres -c 'DROP ROLE kgkg_stg'
    rm /opt/KGKG_staging/isolation.env

`bash ops/deploy/test_staging_isolation.sh` proves the access rules on a throwaway local cluster
(needs PostgreSQL server binaries; it skips without them).

## Note on `main`
GitHub runs `workflow_run` workflows from the default branch. `main` still carries the old
`.github/workflows/deploy.yml` (deleted on `work`), so it fires after every CI run on `work`.
Merge `work` into `main` to retire it.
