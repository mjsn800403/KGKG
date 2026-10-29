// Multi-turn follow-up detection and retrieval-query rewriting.
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { isFollowUp, contextualize } from '../contextualize.js';

const FA = new Set(['ترمز', 'لنت ترمز', 'گشتاور']);

describe('isFollowUp', () => {
  test('empty input is never a follow-up', () => {
    assert.equal(isFollowUp('', FA), false);
    assert.equal(isFollowUp('   ', FA), false);
    assert.equal(isFollowUp(null, FA), false);
  });

  test('a DTC code makes the message self-contained', () => {
    assert.equal(isFollowUp('P0301', FA), false);
    assert.equal(isFollowUp('کد B1234-12 چیه', FA), false);
  });

  test('Persian anaphoric starters mark a follow-up', () => {
    assert.equal(isFollowUp('و گشتاورش چقدره؟', FA), true);
    assert.equal(isFollowUp('چرا؟', FA), true);
  });

  test('a substantive English word (>= 4 letters, not a function word) is self-contained', () => {
    assert.equal(isFollowUp('alternator replacement', FA), false);
  });

  test('short English follow-up made of 3-letter function words is a follow-up', () => {
    assert.equal(isFollowUp('why?', FA), true);
    assert.equal(isFollowUp('how?', FA), true);
  });

  test('regression: 4-5 letter English follow-up words ("how long?", "again?") are follow-ups', () => {
    assert.equal(isFollowUp('how long?', FA), true);
    assert.equal(isFollowUp('again?', FA), true);
    assert.equal(isFollowUp('how much time?', FA), true);
  });

  test('a known domain term anchors a message of >= 3 tokens', () => {
    assert.equal(isFollowUp('لنت ترمز جلو', FA), false);       // bigram
    assert.equal(isFollowUp('مقدار گشتاور پیچ', FA), false);   // unigram
  });

  test('boundary: a 1-2 token bare term is still a follow-up (answer to a clarifying question)', () => {
    assert.equal(isFollowUp('از ترمز', FA), true);
    assert.equal(isFollowUp('ترمز', FA), true);
  });

  test('boundary: without a starter, < 6 tokens is a follow-up, 6-7 is not, >= 8 never', () => {
    assert.equal(isFollowUp('یک دو سه چهار پنج', null), true);
    assert.equal(isFollowUp('یک دو سه چهار پنج شش', null), false);
    assert.equal(isFollowUp('و دو سه چهار پنج شش هفت', null), true);       // starter, 7 tokens
    assert.equal(isFollowUp('و دو سه چهار پنج شش هفت هشت', null), false);  // starter, 8 tokens
  });

  test('Arabic letter forms are normalised before matching starters/terms', () => {
    // «اين» with Arabic yeh == «این»
    assert.equal(isFollowUp('اين چيه', null), true);
    assert.equal(isFollowUp('لنت ترمز عقب', new Set(['لنت ترمز'])), false);
  });
});

describe('contextualize', () => {
  const hist = [
    { role: 'user', content: 'تعویض لنت ترمز جلو کمری' },
    { role: 'ai', content: 'پاسخ' },
    { role: 'user', content: '   ' },
  ];

  test('self-contained message is returned as-is', () => {
    assert.deepEqual(contextualize('لنت ترمز جلو', hist, [], FA), { query: 'لنت ترمز جلو', contextualized: false });
  });

  test('follow-up without any previous user turn is returned as-is', () => {
    assert.deepEqual(contextualize('چرا؟', [{ role: 'ai', content: 'x' }], [], FA),
      { query: 'چرا؟', contextualized: false });
    assert.deepEqual(contextualize('چرا؟', null, null, FA), { query: 'چرا؟', contextualized: false });
  });

  test('follow-up is joined with the last non-blank USER turn and the top source title', () => {
    const r = contextualize('و گشتاورش؟', hist, ['', 'Front Brake Pad Replacement', 'other'], FA);
    assert.equal(r.contextualized, true);
    assert.equal(r.query, 'تعویض لنت ترمز جلو کمری — و گشتاورش؟ (Front Brake Pad Replacement)');
  });

  test('anchor title is skipped when it would push the query past 260 chars', () => {
    const long = [{ role: 'user', content: 'x'.repeat(250) }];
    const r = contextualize('چرا؟', long, ['A'.repeat(20)], FA);
    assert.equal(r.contextualized, true);
    assert.doesNotMatch(r.query, /A/);
  });

  test('query is hard-capped at 300 characters', () => {
    const long = [{ role: 'user', content: 'y'.repeat(1000) }];
    const r = contextualize('چرا؟', long, [], FA);
    assert.equal(r.query.length, 300);
  });
});
