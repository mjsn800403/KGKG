#!/usr/bin/env node
// npm audit gate.
//
// `npm audit` has no allowlist of its own: it is all-or-nothing, which in
// practice means teams stop running it. This reads `npm audit --json` and
// fails only on advisories at or above the configured severity that are not
// listed in ops/security/npm-audit-allow.json.
//
//   node ops/security/npm_audit_gate.mjs            # audits kg_frontend
//   node ops/security/npm_audit_gate.mjs --json x.json
//
// Exit 0 = clean or fully allowlisted, 1 = blocking advisories, 2 = the audit
// itself could not run (a broken gate must never look like a pass).
import { readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, '../..');
const ALLOW_FILE = resolve(HERE, 'npm-audit-allow.json');
const RANK = { info: 0, low: 1, moderate: 2, high: 3, critical: 4 };

const argJson = process.argv.indexOf('--json');

let allow;
try {
  allow = JSON.parse(readFileSync(ALLOW_FILE, 'utf8'));
} catch (err) {
  console.error(`cannot read ${ALLOW_FILE}: ${err.message}`);
  process.exit(2);
}
const floor = RANK[allow.minSeverity ?? 'high'];
if (floor === undefined) {
  console.error(`npm-audit-allow.json: unknown minSeverity ${allow.minSeverity}`);
  process.exit(2);
}

let report;
try {
  const raw = argJson !== -1
    ? readFileSync(process.argv[argJson + 1], 'utf8')
    : execFileSync('npm', ['audit', '--omit=dev', '--package-lock-only', '--json'], {
        cwd: resolve(REPO, 'kg_frontend'),
        encoding: 'utf8',
        maxBuffer: 64 * 1024 * 1024,
        // npm exits non-zero when it finds anything; that is data, not failure.
        stdio: ['ignore', 'pipe', 'inherit'],
      });
  report = JSON.parse(raw);
} catch (err) {
  // execFileSync throws on a non-zero exit, but still carries stdout.
  if (err.stdout) {
    try { report = JSON.parse(err.stdout); } catch { /* fall through */ }
  }
  if (!report) {
    console.error(`npm audit did not produce parseable JSON: ${err.message}`);
    process.exit(2);
  }
}

const vulns = report.vulnerabilities ?? {};
const blocking = [];
const allowed = [];

for (const [pkg, node] of Object.entries(vulns)) {
  for (const via of node.via ?? []) {
    if (typeof via !== 'object') continue;          // a string via = transitive pointer
    const sev = via.severity ?? node.severity;
    if ((RANK[sev] ?? 0) < floor) continue;
    const id = (via.url ?? '').split('/').pop() || via.source || 'unknown';
    const row = { pkg, id, sev, title: (via.title ?? '').slice(0, 90), range: node.range };
    (Object.hasOwn(allow.allow ?? {}, id) ? allowed : blocking).push(row);
  }
}

const fmt = (r) => `  ${r.sev.padEnd(8)} ${r.pkg.padEnd(18)} ${r.id.padEnd(24)} ${r.title}`;

if (allowed.length) {
  console.log(`allowlisted (${allowed.length}):`);
  for (const r of allowed) console.log(`${fmt(r)}\n           reason: ${allow.allow[r.id]}`);
}

if (!blocking.length) {
  const m = report.metadata?.vulnerabilities ?? {};
  console.log(`npm audit gate: PASS (severity >= ${allow.minSeverity}; raw counts ${JSON.stringify(m)})`);
  process.exit(0);
}

console.error(`npm audit gate: FAIL — ${blocking.length} advisory/advisories at or above ${allow.minSeverity}:`);
for (const r of blocking) console.error(fmt(r));
console.error(`
Fix the dependency, or add the id to ops/security/npm-audit-allow.json with a
blocker, a reachability argument and a review date (ops/security/README.md).`);
process.exit(1);
