// Subscription pricing rules (agreed model 2026-09-22): graduated seats,
// annual = 10 x monthly, AI allowance per seat, single-seat demo/pass.
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import {
  BASE_MONTHLY, LIST_MONTHLY, LIST_SEATS, MAX_LISTED_SEATS, ANNUAL_MONTHS_PAID, PLANS, PLAN_DAYS,
  teamMultiplier, monthlyPrice, quote, faNum, faMillion, latinDigits,
  PLAN_REQUEST_BRAND, isPlanRequest, planIdFromCode, initialSelection,
} from '../pricing.js';

const close = (a, b, msg) => assert.ok(Math.abs(a - b) < 1e-9, `${msg ?? ''} ${a} != ${b}`);

describe('teamMultiplier (graduated seat tiers)', () => {
  test('tier boundaries: 100% / 60% / 50% / 40% (4-10) / 35% (11-50)', () => {
    close(teamMultiplier(1), 1);
    close(teamMultiplier(2), 1.6);
    close(teamMultiplier(3), 2.1);
    close(teamMultiplier(4), 2.5);
    close(teamMultiplier(10), 2.1 + 0.4 * 7);
    close(teamMultiplier(11), 4.9 + 0.35);
    close(teamMultiplier(50), 4.9 + 0.35 * 40);
  });

  test('no further discount tier above 50 seats (multiplier is capped)', () => {
    close(teamMultiplier(51), teamMultiplier(50));
    close(teamMultiplier(1000), teamMultiplier(50));
  });

  test('zero / negative / fractional seats clamp to whole seats >= 1', () => {
    close(teamMultiplier(0), 1);
    close(teamMultiplier(-5), 1);
    close(teamMultiplier(2.9), 1.6);
  });

  test('each additional seat never costs more than the previous one', () => {
    let prevStep = Infinity;
    for (let n = 2; n <= 50; n++) {
      const step = teamMultiplier(n) - teamMultiplier(n - 1);
      assert.ok(step > 0 && step <= prevStep + 1e-9, `seat ${n}`);
      prevStep = step;
    }
  });
});

describe('monthlyPrice', () => {
  test('listed team sizes use the public list price', () => {
    for (const s of LIST_SEATS) assert.equal(monthlyPrice(s), LIST_MONTHLY[s]);
    assert.equal(monthlyPrice(1), BASE_MONTHLY);
  });

  test('unlisted sizes use the formula rounded to the nearest million', () => {
    assert.equal(monthlyPrice(4), 30);          // 12 * 2.5
    assert.equal(monthlyPrice(7), 44);          // 12 * 3.7 = 44.4
    assert.equal(monthlyPrice(11), 63);         // 12 * 5.25
    assert.equal(monthlyPrice(49), 223);        // 12 * 18.55 = 222.6
  });

  test('list prices stay within rounding distance (<= 2.5M) of the formula', () => {
    for (const s of LIST_SEATS) {
      const formula = BASE_MONTHLY * teamMultiplier(s);
      assert.ok(Math.abs(LIST_MONTHLY[s] - formula) <= 2.5, `seats ${s}: ${LIST_MONTHLY[s]} vs ${formula}`);
    }
  });

  test('a bigger team never pays less in total (1..50)', () => {
    for (let n = 2; n <= MAX_LISTED_SEATS; n++) {
      assert.ok(monthlyPrice(n) > monthlyPrice(n - 1), `total at ${n}`);
    }
  });

  test('DEFECT probe: a bigger team never pays more per seat (1..50)', {
    skip: 'DEFECT (needs business sign-off): pricing.js:25 list price for 30 seats (145) sits above the formula (142.8), so per-seat '
      + 'rises 29->30 seats (139/29=4.79M -> 145/30=4.83M per seat)',
  }, () => {
    for (let n = 2; n <= MAX_LISTED_SEATS; n++) {
      assert.ok(monthlyPrice(n) / n <= monthlyPrice(n - 1) / (n - 1) + 1e-9, `per-seat at ${n}`);
    }
  });
});

describe('quote', () => {
  test('demo: free, forced to one seat, 5 AI questions', () => {
    const q = quote('demo', 25);
    assert.equal(q.total, 0);
    assert.equal(q.seats, 1);
    assert.equal(q.ai, 5);
    assert.equal(q.custom, false);
  });

  test('2-day pass: single seat only, 3M per seat, 20 AI questions', () => {
    const q = quote('pass', 10);
    assert.equal(q.seats, 1);
    assert.equal(q.total, 3);
    assert.equal(q.ai, 20);
  });

  test('monthly: list price, per-seat and AI allowance scale with seats', () => {
    const q = quote('monthly', 5);
    assert.equal(q.total, 35);
    close(q.perSeat, 7);
    assert.equal(q.ai, 5 * 150);
    assert.equal(q.savings, 0);
  });

  test('annual = 10 x monthly for every team size 1..50; savings = 2 months', () => {
    for (let n = 1; n <= 50; n++) {
      const m = monthlyPrice(n);
      const q = quote('annual', n);
      assert.equal(q.total, m * ANNUAL_MONTHS_PAID, `seats ${n}`);
      assert.equal(q.savings, m * 2, `seats ${n}`);
      close(q.monthlyEquivalent, q.total / 12);
      close(q.perSeat, q.total / 12 / n);
      assert.ok(q.total < quote('monthly', n).total * 12);
    }
  });

  test('annual AI allowance per seat exceeds monthly (200 vs 150)', () => {
    assert.equal(quote('annual', 3).aiPerSeat, PLANS.annual.aiPerSeat);
    assert.ok(PLANS.annual.aiPerSeat > PLANS.monthly.aiPerSeat);
    assert.equal(quote('annual', 3).ai, 600);
  });

  test('boundary: 50 seats is priced, 51 seats goes to sales (custom, no total)', () => {
    const at = quote('annual', 50);
    assert.equal(at.custom, false);
    assert.equal(at.total, 2250);
    const over = quote('monthly', 51);
    assert.equal(over.custom, true);
    assert.equal(over.total, null);
    assert.equal(over.perSeat, null);
    assert.equal(over.ai, 51 * 150);
  });

  test('invalid seat counts normalise to 1; fractions floor', () => {
    for (const s of [0, -3, NaN, undefined, 'abc', null]) {
      assert.equal(quote('monthly', s).seats, 1, `seats=${String(s)}`);
    }
    assert.equal(quote('monthly', 2.7).seats, 2);
  });

  test('unknown plan id falls back to annual (never a free plan)', () => {
    const q = quote('free-forever', 2);
    assert.equal(q.plan.id, 'annual');
    assert.equal(q.total, 190);
  });

  test('plan access windows cover their period', () => {
    assert.equal(PLAN_DAYS.demo, 1);
    assert.equal(PLAN_DAYS.pass, 2);
    assert.ok(PLAN_DAYS.monthly >= 31);
    assert.ok(PLAN_DAYS.annual >= 366);
  });
});

describe('formatting', () => {
  test('faNum uses Persian digits and separators', () => {
    assert.equal(faNum(60), '۶۰');
    assert.equal(faNum(1450), '۱٬۴۵۰');
    assert.equal(faNum(7.916, 1), '۷٫۹');
  });

  test('faMillion: one decimal below 10M, whole millions from 10M up', () => {
    assert.equal(faMillion(7.916), '۷٫۹ میلیون تومان');
    assert.equal(faMillion(3), '۳ میلیون تومان');
    assert.equal(faMillion(60), '۶۰ میلیون تومان');
    assert.equal(faMillion(10.6), '۱۱ میلیون تومان');
    assert.equal(faMillion(9.96), '۱۰ میلیون تومان');
    assert.equal(faMillion(60, { unit: false }), '۶۰');
  });

  test('latinDigits converts Persian and Arabic-Indic digits, leaves the rest', () => {
    assert.equal(latinDigits('۰۹۱۲۳۴۵۶۷۸۹'), '09123456789');
    assert.equal(latinDigits('٠١٢٣'), '0123');
    assert.equal(latinDigits('a۱-٢b3'), 'a1-2b3');
    assert.equal(latinDigits(null), '');
    assert.equal(latinDigits(0), '');
  });
});

describe('plan-request encoding', () => {
  test('isPlanRequest needs the marker brand AND a known plan code', () => {
    for (const year of ['demo', '2day', 'monthly', 'annual', 'custom']) {
      assert.equal(isPlanRequest({ brand: PLAN_REQUEST_BRAND, year }), true, year);
    }
    assert.equal(isPlanRequest({ brand: PLAN_REQUEST_BRAND, year: '2024' }), false);
    assert.equal(isPlanRequest({ brand: 'Toyota', year: 'annual' }), false);
    assert.equal(isPlanRequest(null), false);
    assert.equal(isPlanRequest(undefined), false);
  });

  test('planIdFromCode maps public codes; anything else is annual', () => {
    assert.equal(planIdFromCode('demo'), 'demo');
    assert.equal(planIdFromCode('2day'), 'pass');
    assert.equal(planIdFromCode('monthly'), 'monthly');
    assert.equal(planIdFromCode('annual'), 'annual');
    assert.equal(planIdFromCode('custom'), 'annual');
    assert.equal(planIdFromCode(undefined), 'annual');
  });
});

describe('initialSelection (URL query)', () => {
  test('accepts plan id or public code', () => {
    assert.deepEqual(initialSelection({ plan: 'monthly', seats: '5' }), { plan: 'monthly', seats: 5 });
    assert.deepEqual(initialSelection({ plan: '2day' }), { plan: 'pass', seats: 1 });
  });

  test('single-seat plans ignore the requested seat count', () => {
    assert.deepEqual(initialSelection({ plan: 'pass', seats: '9' }), { plan: 'pass', seats: 1 });
    assert.deepEqual(initialSelection({ plan: 'demo', seats: '9' }), { plan: 'demo', seats: 1 });
  });

  test('unknown/missing plan defaults to annual; repeated params use the first', () => {
    assert.deepEqual(initialSelection({}), { plan: 'annual', seats: 1 });
    assert.deepEqual(initialSelection({ plan: '<script>' }), { plan: 'annual', seats: 1 });
    assert.deepEqual(initialSelection({ plan: ['monthly', 'demo'], seats: ['3', '40'] }), { plan: 'monthly', seats: 3 });
  });

  test('seats clamp to 1..1000', () => {
    assert.equal(initialSelection({ seats: '0' }).seats, 1);
    assert.equal(initialSelection({ seats: '-4' }).seats, 1);
    assert.equal(initialSelection({ seats: 'abc' }).seats, 1);
    assert.equal(initialSelection({ seats: '1000' }).seats, 1000);
    assert.equal(initialSelection({ seats: '5000' }).seats, 1000);
  });
});
