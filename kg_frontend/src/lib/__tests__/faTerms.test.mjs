// faTerms in degraded mode (no TERMS_JSON_PATH): the built-in dictionary.
// Each test file runs in its own process, so module state is fresh here.
import { test, describe, before } from 'node:test';
import assert from 'node:assert/strict';
import { normFa, faTitle, faTitleBoth, collectPairs, faTermsSet } from '../faTerms.js';

before(() => { delete process.env.TERMS_JSON_PATH; });

describe('normFa', () => {
  test('unifies Arabic letter forms with Persian ones', () => {
    assert.equal(normFa('كيك'), 'کیک');
    assert.equal(normFa('آب أ إ ة ۀ ؤ'), 'اب ا ا ه ه و');
  });

  test('ZWNJ/tatweel become spaces, diacritics are removed, whitespace collapsed', () => {
    assert.equal(normFa('کمک‌فنر'), 'کمک فنر');
    assert.equal(normFa('مـوتور'), 'م وتور');
    assert.equal(normFa('مُوَتور'), 'موتور');
    assert.equal(normFa('  a \t\n  B  '), 'a b');
  });

  test('falsy input yields an empty string', () => {
    assert.equal(normFa(''), '');
    assert.equal(normFa(null), '');
    assert.equal(normFa(undefined), '');
  });
});

describe('faTitle (fallback dictionary)', () => {
  test('longest phrase wins over its prefix word', () => {
    assert.equal(faTitle('Brake Pad'), 'لنت ترمز');
    assert.equal(faTitle('Brake'), 'ترمز');
    assert.equal(faTitle('Cabin Air Filter'), 'فیلتر کابین');
    assert.equal(faTitle('Air Filter'), 'فیلتر هوا');
  });

  test('matching is case-insensitive and keeps untranslated text in place', () => {
    assert.equal(faTitle('FRONT Brake Pad Replacement (2AR-FE)'), 'جلو لنت ترمز تعویض (2AR-FE)');
  });

  test('whole-token only: "Engineering" is not "engine"', () => {
    assert.equal(faTitle('Engineering Notes'), 'Engineering Notes');
  });

  test('phrase words may be joined by a space or hyphen, not by other punctuation', () => {
    assert.equal(faTitle('Brake-Pad'), 'لنت ترمز');
    assert.equal(faTitle('Brake, Pad'), 'ترمز, Pad');
    assert.equal(faTitle('Brake  Pad'), 'ترمز  Pad');
  });

  test('falsy input is returned as-is', () => {
    assert.equal(faTitle(''), '');
    assert.equal(faTitle(null), null);
    assert.equal(faTitle(undefined), undefined);
  });
});

describe('faTitleBoth', () => {
  test('translated Latin title -> «فارسی (English)»', () => {
    assert.equal(faTitleBoth('Engine Oil'), 'روغن موتور (Engine Oil)');
  });

  test('no change, no Latin, or > 80 chars -> plain translation only', () => {
    assert.equal(faTitleBoth('Xyzzy'), 'Xyzzy');
    assert.equal(faTitleBoth('ترمز'), 'ترمز');
    const long = `Engine ${'x'.repeat(80)}`;
    assert.equal(faTitleBoth(long), faTitle(long));
    assert.ok(!faTitleBoth(long).includes('('));
  });
});

describe('collectPairs', () => {
  test('distinct pairs found in the texts, longest English first', () => {
    const out = collectPairs(['Brake Pad replacement', 'engine and ENGINE', null, '']);
    assert.deepEqual(out, [['replacement', 'تعویض'], ['brake pad', 'لنت ترمز'], ['engine', 'موتور']]);
  });

  test('cap limits the result; empty input yields []', () => {
    assert.equal(collectPairs(['brake pad replacement engine oil sensor'], 2).length, 2);
    assert.deepEqual(collectPairs(null), []);
    assert.deepEqual(collectPairs([]), []);
  });
});

describe('faTermsSet', () => {
  test('contains normalised Persian terms of the dictionary', () => {
    const s = faTermsSet();
    assert.ok(s.has('لنت ترمز'));
    assert.ok(s.has('کمک فنر'), 'ZWNJ form normalised');
    assert.ok(!s.has('کمک‌فنر'));
  });
});
