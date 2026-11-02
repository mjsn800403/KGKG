// Presentation rules for the support desk: how an SLA state, a due date, a
// channel and a duration are shown to a reader. Pure functions, because the
// interesting part is the rule, not the markup — and a wrong rule here would
// tell a customer their ticket is on time when it is late.
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import {
  SLA_STATES, slaTone, slaLabel, dueText, sourceLabel, canRate, nextStatuses,
  fmtMinutes, fmtHours, csatFace, ratio,
} from '../support.js';

describe('slaTone / slaLabel', () => {
  test('every state the API can return has a tone and a Persian label', () => {
    for (const s of SLA_STATES) {
      assert.ok(slaTone(s), `no tone for ${s}`);
      assert.match(slaLabel(s), /[؀-ۿ]/, `label for ${s} is not Persian`);
    }
  });

  test('met is good, breached is bad, pending is neutral', () => {
    assert.equal(slaTone('met'), 'ok');
    assert.equal(slaTone('breached'), 'bad');
    assert.equal(slaTone('pending'), 'info');
  });

  test('an unknown or absent state has no tone, so nothing is rendered', () => {
    assert.equal(slaTone(null), null);
    assert.equal(slaTone('untracked'), null);
    assert.equal(slaTone('nonsense'), null);
    assert.equal(slaLabel(null), '');
  });
});

describe('dueText', () => {
  const now = new Date('2026-10-30T12:00:00Z');

  test('a future due date reads as time remaining', () => {
    const d = dueText('2026-10-30T14:30:00Z', now);
    assert.equal(d.overdue, false);
    assert.match(d.text, /مانده/);
  });

  test('a past due date reads as time elapsed and is flagged overdue', () => {
    const d = dueText('2026-10-30T09:00:00Z', now);
    assert.equal(d.overdue, true);
    assert.match(d.text, /گذشته/);
  });

  test('minutes below an hour are shown in minutes, not "0 hours"', () => {
    assert.match(dueText('2026-10-30T12:40:00Z', now).text, /دقیقه/);
  });

  test('more than a day is shown in days', () => {
    assert.match(dueText('2026-11-02T12:00:00Z', now).text, /روز/);
  });

  test('no due date and junk input yield null rather than throwing', () => {
    assert.equal(dueText(null, now), null);
    assert.equal(dueText('not-a-date', now), null);
    assert.equal(dueText(undefined, now), null);
  });
});

describe('sourceLabel', () => {
  test('each channel the backend defines has a Persian label', () => {
    for (const s of ['portal', 'phone', 'email', 'sms', 'in_person']) {
      assert.match(sourceLabel(s), /[؀-ۿ]/, s);
    }
  });

  test('an unknown channel falls back to its own key, never to empty', () => {
    assert.equal(sourceLabel('carrier_pigeon'), 'carrier_pigeon');
    assert.equal(sourceLabel(''), '');
  });
});

describe('canRate', () => {
  test('a closed, unrated ticket filed by this user can be rated', () => {
    const req = { status: 'completed', csat: null, created_by: { id: 7 } };
    assert.equal(canRate(req, { id: 7 }), true);
  });

  test('an open ticket cannot be rated', () => {
    assert.equal(canRate({ status: 'in_progress', csat: null, created_by: { id: 7 } },
                         { id: 7 }), false);
  });

  test('an already rated ticket cannot be rated again', () => {
    assert.equal(canRate({ status: 'completed', csat: { score: 4 }, created_by: { id: 7 } },
                         { id: 7 }), false);
  });

  test('a colleague who did not file it cannot rate it — the server agrees', () => {
    assert.equal(canRate({ status: 'completed', csat: null, created_by: { id: 7 } },
                         { id: 8 }), false);
  });

  test('a ticket logged by the platform side has no filer; a manager may rate it', () => {
    const req = { status: 'completed', csat: null, created_by: null };
    assert.equal(canRate(req, { id: 8, can_manage_team: true }), true);
    assert.equal(canRate(req, { id: 8, can_manage_team: false }), false);
  });

  test('a rejected ticket is closed, so it can be rated', () => {
    assert.equal(canRate({ status: 'rejected', csat: null, created_by: { id: 1 } },
                         { id: 1 }), true);
  });

  test('a missing ticket or viewer is false, not an exception', () => {
    assert.equal(canRate(null, { id: 1 }), false);
    assert.equal(canRate({ status: 'completed', csat: null, created_by: { id: 1 } }, null),
                 false);
  });
});

describe('nextStatuses', () => {
  test('the transitions an agent is offered match the lifecycle', () => {
    assert.deepEqual(nextStatuses('pending').map((x) => x[0]), ['in_progress', 'rejected']);
    assert.deepEqual(nextStatuses('in_progress').map((x) => x[0]), ['completed', 'rejected']);
    assert.deepEqual(nextStatuses('completed').map((x) => x[0]), ['in_progress']);
    assert.deepEqual(nextStatuses('rejected').map((x) => x[0]), ['in_progress']);
  });

  test('a status is never offered as a transition to itself', () => {
    for (const s of ['pending', 'in_progress', 'completed', 'rejected']) {
      assert.ok(!nextStatuses(s).some((x) => x[0] === s), s);
    }
  });

  test('an unknown status offers nothing instead of throwing', () => {
    assert.deepEqual(nextStatuses('nonsense'), []);
    assert.deepEqual(nextStatuses(undefined), []);
  });
});

describe('fmtMinutes / fmtHours', () => {
  test('null stays an em dash, so "no measurement" never reads as zero', () => {
    assert.equal(fmtMinutes(null), '—');
    assert.equal(fmtHours(null), '—');
    assert.equal(fmtMinutes(undefined), '—');
  });

  test('zero is a measurement and is shown as one', () => {
    assert.notEqual(fmtMinutes(0), '—');
  });

  test('minutes roll up into hours and days', () => {
    assert.match(fmtMinutes(45), /دقیقه/);
    assert.match(fmtMinutes(150), /ساعت/);
    assert.match(fmtMinutes(60 * 30), /روز/);
  });

  test('hours roll up into days', () => {
    assert.match(fmtHours(5), /ساعت/);
    assert.match(fmtHours(50), /روز/);
  });
});

describe('ratio', () => {
  test('a rate is shown as a percentage', () => {
    assert.equal(ratio(0.5), '۵۰٪');
    assert.equal(ratio(1), '۱۰۰٪');
  });

  test('null is an em dash, never 0٪ — the distinction the API preserves', () => {
    assert.equal(ratio(null), '—');
    assert.equal(ratio(undefined), '—');
  });

  test('zero is a real rate', () => {
    assert.equal(ratio(0), '۰٪');
  });
});

describe('csatFace', () => {
  test('each score 1..5 has a distinct face', () => {
    const faces = [1, 2, 3, 4, 5].map(csatFace);
    assert.equal(new Set(faces).size, 5);
  });

  test('out of range is empty rather than a wrong face', () => {
    assert.equal(csatFace(0), '');
    assert.equal(csatFace(6), '');
    assert.equal(csatFace(null), '');
  });
});
