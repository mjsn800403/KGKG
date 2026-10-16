# Deploying KGKG

Manual: `bash /opt/KGKG/ops/deploy/deploy.sh work` (also `--staging`, `--rollback`, `--reload`, `--status`).

## Push-to-deploy setup (repo owner)

Repository: https://github.com/mjsn800403/KGKG

## 1. Add the secrets
Go to **Settings → Secrets and variables → Actions → New repository secret**.

| Name | Value |
|---|---|
| `DEPLOY_HOST` | `103.75.197.155` |
| `DEPLOY_KNOWN_HOSTS` | On the server, run `ssh-keyscan -t ed25519 103.75.197.155` and paste the single line it prints. |
| `DEPLOY_SSH_KEY` | On the server, run `cat /root/.ssh/gh-deploy` and paste the whole private key, BEGIN and END lines included. Don't share this key anywhere else. |

## 2. Require an approval
1. Go to **Settings → Environments → production**.
2. Tick **Required reviewers** and add yourself.
3. Save.

## Result
1. Push to `work`.
2. CI runs.
3. Once CI passes, the `deploy` job waits for your approval.
4. The server runs the gated deploy, with automatic rollback if it fails.

The key can't open a shell. It only deploys commits that are on `origin/work`.
