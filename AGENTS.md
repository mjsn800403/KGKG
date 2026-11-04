# Agents: start here

Read [`docs/AGENTS.md`](docs/AGENTS.md) first. It is the entry point for AI coding agents and new engineers: how to read the
evidence tags, which document answers which task, the rules that are easy to break, and how to re-verify claims.

Three rules that apply before you open anything else:

1. Branch from `origin/work` and open the pull request to `work`; the PR must reference an issue.
2. Do not read or print secrets (`.env*`, keys); do not deploy, restart or change the production host without the owner's explicit go-ahead.
3. Docs ship with the change. If you add a model, command, module, env var or `ops/` file, run
   `python3 ops/governance/gen_inventory.py` and describe it in the matching doc; CI compares against the target branch.

Docs index: [`docs/README.md`](docs/README.md). Generated code inventory: [`docs/generated/inventory.md`](docs/generated/inventory.md).
