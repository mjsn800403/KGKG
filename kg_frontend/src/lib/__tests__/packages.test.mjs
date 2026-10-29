// Document packages, roles and the purchase-form selection rules.
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import {
  PACKAGES, PACKAGE_MAP, BASE_PACKAGE_IDS, ALL_PACKAGE_IDS, ROLES, AI_REQUIRES,
  packageLabel, roleWithDepartment, userHasAiEligibility,
  toggleDocumentSelection, selectAllDocuments, emptySeatPlanRow,
} from '../packages.js';

const sorted = (a) => [...a].sort();

describe('catalogue integrity', () => {
  test('every package id is unique and present in PACKAGE_MAP', () => {
    const ids = PACKAGES.map((p) => p.id);
    assert.equal(new Set(ids).size, ids.length);
    assert.deepEqual(sorted(ALL_PACKAGE_IDS), sorted(ids));
    for (const id of ALL_PACKAGE_IDS) assert.equal(PACKAGE_MAP[id].id, id);
  });

  test('full_spec is the only add-on; base set excludes it', () => {
    assert.ok(!BASE_PACKAGE_IDS.includes('full_spec'));
    assert.deepEqual(PACKAGES.filter((p) => p.priceNote !== 'پایه').map((p) => p.id), ['full_spec']);
  });

  test('roles have unique ids and strictly increasing levels', () => {
    assert.equal(new Set(ROLES.map((r) => r.id)).size, ROLES.length);
    ROLES.forEach((r, i) => assert.equal(r.level, i + 1));
  });
});

describe('toggleDocumentSelection', () => {
  test('selecting full_spec selects every document', () => {
    assert.deepEqual(sorted(toggleDocumentSelection([], 'full_spec')), sorted(ALL_PACKAGE_IDS));
  });

  test('deselecting full_spec keeps the base documents', () => {
    const out = toggleDocumentSelection(ALL_PACKAGE_IDS, 'full_spec');
    assert.deepEqual(sorted(out), sorted(BASE_PACKAGE_IDS));
  });

  test('dropping any base document also drops full_spec', () => {
    for (const id of BASE_PACKAGE_IDS) {
      const out = toggleDocumentSelection(ALL_PACKAGE_IDS, id);
      assert.ok(!out.includes(id));
      assert.ok(!out.includes('full_spec'), `after dropping ${id}`);
    }
  });

  test('boundary: 3 of 4 base docs -> no full_spec; 4th one auto-adds full_spec', () => {
    const three = BASE_PACKAGE_IDS.slice(0, 3);
    let sel = [];
    for (const id of three) sel = toggleDocumentSelection(sel, id);
    assert.ok(!sel.includes('full_spec'));
    sel = toggleDocumentSelection(sel, BASE_PACKAGE_IDS[3]);
    assert.deepEqual(sorted(sel), sorted(ALL_PACKAGE_IDS));
  });

  test('does not mutate the input and de-duplicates', () => {
    const input = ['manual', 'manual'];
    const out = toggleDocumentSelection(input, 'parts');
    assert.deepEqual(input, ['manual', 'manual']);
    assert.deepEqual(sorted(out), ['manual', 'parts']);
  });

  test('selectAllDocuments returns a fresh copy', () => {
    const a = selectAllDocuments();
    a.pop();
    assert.equal(selectAllDocuments().length, ALL_PACKAGE_IDS.length);
  });
});

describe('labels and eligibility', () => {
  test('packageLabel: known id -> Persian label, unknown id -> id', () => {
    assert.equal(packageLabel('manual'), 'راهنمای تعمیرات');
    assert.equal(packageLabel('nope'), 'nope');
  });

  test('roleWithDepartment swaps the department only when a different one is given', () => {
    const label = 'مدیر خدمات پس از فروش';
    assert.equal(roleWithDepartment(label, ''), label);
    assert.equal(roleWithDepartment(label, undefined), label);
    assert.equal(roleWithDepartment(label, 'خدمات پس از فروش'), label);
    assert.equal(roleWithDepartment(label, 'گارانتی'), 'مدیر گارانتی');
  });

  test('AI assistant requires the repair-manual package', () => {
    assert.equal(AI_REQUIRES, 'manual');
    assert.equal(userHasAiEligibility(['manual']), true);
    assert.equal(userHasAiEligibility(['parts', 'full_spec']), false);
    assert.equal(userHasAiEligibility([]), false);
    assert.equal(userHasAiEligibility(), false);
  });

  test('emptySeatPlanRow returns an independent row each call', () => {
    const a = emptySeatPlanRow();
    a.count = 99;
    assert.equal(emptySeatPlanRow().count, 1);
    assert.equal(emptySeatPlanRow().role, 'after_sales_specialist');
  });
});
