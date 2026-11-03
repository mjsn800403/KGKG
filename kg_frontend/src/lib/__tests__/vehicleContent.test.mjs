// "Parts Catalog" chip rule: shown only for vehicles whose sole content is the
// parts catalog, derived strictly from the backend's has_manual/has_parts flags.
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { isPartsOnly } from '../vehicleContent.js';

describe('isPartsOnly', () => {
  test('parts catalog only -> label', () => {
    assert.equal(isPartsOnly({ has_parts: true, has_manual: false }), true);
  });

  test('other documentation, no parts catalog -> no label', () => {
    assert.equal(isPartsOnly({ has_parts: false, has_manual: true }), false);
  });

  test('both parts catalog and other documentation -> no label', () => {
    assert.equal(isPartsOnly({ has_parts: true, has_manual: true }), false);
  });

  test('neither -> no label', () => {
    assert.equal(isPartsOnly({ has_parts: false, has_manual: false }), false);
  });

  test('older payload without has_manual never guesses', () => {
    assert.equal(isPartsOnly({ has_parts: true }), false);
    assert.equal(isPartsOnly({}), false);
    assert.equal(isPartsOnly(null), false);
  });
});
