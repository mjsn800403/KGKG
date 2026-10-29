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
CI needs three repository secrets. Only the server can create them, so run this there, as root:

```bash
bash /opt/KGKG/ops/deploy/setup_ci_access.sh
```

The first time, the script is not in the live release yet (promoting needs a staging run, and
staging needs this connection), so take it from `origin/work` without promoting anything:

```bash
git -C /opt/KGKG fetch origin work
git -C /opt/KGKG show origin/work:ops/deploy/setup_ci_access.sh > /root/setup_ci_access.sh
bash /root/setup_ci_access.sh
```

It creates a dedicated key (`/root/.ssh/kgkg-github-ci`), pins it to `kg-ci-gate` with `restrict`
(no shell, no forwarding), tests a real SSH login with it, and then:

* if `gh` is logged in on the server (`gh auth login`), sets the secrets itself;
* otherwise prints them. Open **Settings → Secrets and variables → Actions → New repository secret**
  (https://github.com/mjsn800403/KGKG/settings/secrets/actions) and add each one:

| Name | Value |
|---|---|
| `DEPLOY_HOST` | the server's public IP (not the domain: it points at Cloudflare, which does not carry SSH) |
| `DEPLOY_KNOWN_HOSTS` | the server's host key line, so the runner knows it is talking to this server |
| `DEPLOY_SSH_KEY` | the private key, from `-----BEGIN` to `-----END`, both lines included |
| `DEPLOY_PORT` | only if sshd is not on port 22 |

Then re-run the failed `stage` job, or push to `work`.

The script is safe to re-run. `--rotate` replaces the key (paste the new one into `DEPLOY_SSH_KEY`),
`--print` prints instead of using `gh`, `--host <ip>` overrides the address it detected.

## When the `stage` job fails
`ops/deploy/ci_ssh.sh` turns each failure into an error on the run page. The common ones:

| CI says | Fix |
|---|---|
| missing repository secret(s) | Run `setup_ci_access.sh` as above. |
| holds a public key / not a usable private key | Paste the private key file, BEGIN and END lines included. |
| refused DEPLOY_SSH_KEY | The secret and the server disagree. Compare the fingerprint CI prints with the one the script printed; re-run the script and paste again. |
| host key does not match | The server was rebuilt or its host keys changed: re-run the script for the new `DEPLOY_KNOWN_HOSTS`. |
| cannot reach … port 22 | Firewall. GitHub's runners use changing addresses, so SSH must accept any source. First make sure password logins are off (`PasswordAuthentication no` in `/etc/ssh/sshd_config`; the setup script warns if not), then `ufw limit 22/tcp`. The CI key itself can only stage. |
| closed the SSH connection before authentication | fail2ban banned a runner: `fail2ban-client status sshd`. |
| could promote to production | The CI key is pinned to `kg-deploy-gate`. Re-run the script; it repins it to `kg-ci-gate`. |
| could not fetch origin/work | The server's own GitHub access: `git -C /opt/KGKG fetch origin work`. |

## Note on `main`
GitHub runs `workflow_run` workflows from the default branch. `main` still carries the old
`.github/workflows/deploy.yml` (deleted on `work`), so it fires after every CI run on `work`.
Merge `work` into `main` to retire it.
