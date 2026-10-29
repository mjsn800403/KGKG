// faTerms with a generated terminology artifact (TERMS_JSON_PATH): load,
// hot-reload on mtime change, and keep last good data when the file breaks.
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { faTitle, faTermsSet } from '../faTerms.js';

let dir;
let file;
const realNow = Date.now;
let offset = 0;

const write = (obj, mtimeSec) => {
  fs.writeFileSync(file, typeof obj === 'string' ? obj : JSON.stringify(obj));
  fs.utimesSync(file, mtimeSec, mtimeSec);
};
const advance = () => { offset += 61_000; };   // past the 60 s reload check

before(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), 'faterms-'));
  file = path.join(dir, 'terms_en_fa.json');
  write({ entries: [['Caliper Bracket', 'براکت کالیپر'], ['caliper', 'کالیپر'], ['', 'x'], ['bad']],
    fa_terms: ['براکت كالیپر'] }, 1_000_000);
  process.env.TERMS_JSON_PATH = file;
  Date.now = () => realNow() + offset;
});

after(() => {
  Date.now = realNow;
  delete process.env.TERMS_JSON_PATH;
  fs.rmSync(dir, { recursive: true, force: true });
});

test('artifact entries replace the built-in dictionary (no fallback mixing)', () => {
  assert.equal(faTitle('Front Caliper Bracket'), 'Front براکت کالیپر');
  assert.equal(faTitle('Caliper'), 'کالیپر');
  assert.equal(faTitle('Brake'), 'Brake', 'fallback-only term must not be used');
});

test('fa_terms (normalised) feed the follow-up term set', () => {
  const s = faTermsSet();
  assert.ok(s.has('براکت کالیپر'));
  assert.equal(s.size, 1);
});

test('within the 60 s window a changed file is not re-read', () => {
  write({ entries: [['caliper', 'کالیپر جدید']] }, 2_000_000);
  assert.equal(faTitle('Caliper'), 'کالیپر');
});

test('after the window a new mtime is hot-reloaded', () => {
  advance();
  assert.equal(faTitle('Caliper'), 'کالیپر جدید');
});

test('a broken artifact keeps the last good dictionary', () => {
  write('{not json', 3_000_000);
  advance();
  assert.equal(faTitle('Caliper'), 'کالیپر جدید');
  write({ entries: [] }, 4_000_000);
  advance();
  assert.equal(faTitle('Caliper'), 'کالیپر جدید');
});
