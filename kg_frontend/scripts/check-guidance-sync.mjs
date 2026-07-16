#!/usr/bin/env node
// ---------------------------------------------------------------------------
// Guidance ↔ docs synchronization check.
// ---------------------------------------------------------------------------
// Gives the "living documentation" promise teeth: every docRef in the guidance
// content must point at a docs file that exists, and if a referenced doc file
// was modified more recently than the guidance was last `reviewed`, we flag it
// as possibly stale so a maintainer re-checks the user-facing copy.
//
// Zero dependencies. Run from kg_frontend/:  node scripts/check-guidance-sync.mjs
// Exit code 1 on a broken reference (CI-friendly); staleness is a warning only.
// ---------------------------------------------------------------------------
import { readFileSync, readdirSync, statSync, existsSync } from 'node:fs';
import { join, dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const FRONTEND = resolve(here, '..');
const REPO = resolve(FRONTEND, '..');
const DOCS = join(REPO, 'docs');
const GUIDE = join(FRONTEND, 'src', 'guidance');

function guidanceFiles() {
  return readdirSync(GUIDE)
    .filter((f) => f.endsWith('.js') || f.endsWith('.jsx'))
    .map((f) => join(GUIDE, f));
}

const DOCREF_RE = /docRef:\s*['"]([^'"]+)['"]/g;
const REVIEWED_RE = /REVIEWED\s*=\s*['"](\d{4}-\d{2}-\d{2})['"]/;

let reviewed = null;
const refs = [];
for (const file of guidanceFiles()) {
  const src = readFileSync(file, 'utf8');
  const rev = src.match(REVIEWED_RE);
  if (rev) reviewed = rev[1];
  let m;
  while ((m = DOCREF_RE.exec(src)) !== null) refs.push({ ref: m[1], file });
}

const missing = [];
const docFiles = new Set();
for (const { ref, file } of refs) {
  const rel = ref.split('#')[0]; // strip anchor
  const abs = join(REPO, rel);
  docFiles.add(rel);
  if (!existsSync(abs)) missing.push({ ref, file: file.replace(REPO + '/', '') });
}

const stale = [];
if (reviewed) {
  const reviewedMs = new Date(reviewed + 'T23:59:59Z').getTime();
  for (const rel of docFiles) {
    const abs = join(REPO, rel);
    if (existsSync(abs)) {
      const mtime = statSync(abs).mtimeMs;
      if (mtime > reviewedMs) stale.push(rel);
    }
  }
}

console.log(`guidance docRefs: ${refs.length} (referencing ${docFiles.size} doc files)`);
console.log(`guidance last reviewed: ${reviewed || 'unknown'}`);

if (missing.length) {
  console.error(`\n✗ ${missing.length} docRef(s) point at a missing docs file:`);
  for (const m of missing) console.error(`   ${m.ref}   (in ${m.file})`);
  console.error('\nFix the docRef or restore the doc, then re-run.');
  process.exit(1);
}
console.log('✓ every docRef resolves to an existing docs file.');

if (stale.length) {
  console.warn(`\n⚠ ${stale.length} referenced doc file(s) changed after the last guidance review (${reviewed}).`);
  console.warn('  Re-check the matching articles in src/guidance/content.js and bump REVIEWED:');
  for (const s of [...new Set(stale)]) console.warn(`   ${s}`);
} else {
  console.log('✓ no referenced doc file is newer than the last guidance review.');
}
