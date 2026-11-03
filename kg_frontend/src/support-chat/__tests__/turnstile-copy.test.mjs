import test from 'node:test';
import assert from 'node:assert/strict';

import { createTurnstile, DEFAULT_SITEKEY } from '../turnstile.js';
import { COPY, LABELS } from '../copy.fa.js';

function env({ blocked = false, auto = true } = {}) {
  const listeners = {};
  const state = { api: null, rendered: null, appended: 0, removed: 0, calls: [] };
  const script = {
    setAttribute() {}, addEventListener: (t, fn) => { listeners[t] = fn; },
    remove() { state.removed += 1; },
  };
  const doc = {
    querySelector: () => null,
    createElement: () => script,
    head: {
      appendChild() {
        state.appended += 1;
        setTimeout(() => {
          if (blocked) return listeners.error?.();
          state.api = {
            render: (_el, opts) => { state.rendered = opts; return 'w1'; },
            reset: (id) => state.calls.push(['reset', id]),
            execute: (id) => { state.calls.push(['execute', id]); if (auto) setTimeout(() => state.rendered.callback('tok-1'), 0); },
            remove: (id) => state.calls.push(['remove', id]),
          };
          listeners.load?.();
        }, 0);
      },
    },
  };
  return { doc, state, make: () => createTurnstile({ doc, getApi: () => state.api, mount: () => ({}) }) };
}

test('nothing is loaded until prepare or execute is called', () => {
  const e = env();
  e.make();
  assert.equal(e.state.appended, 0);
});

test('execute loads once, renders the invisible widget with the support_chat action and returns a token', async () => {
  const e = env();
  const t = e.make();
  assert.equal(await t.execute(), 'tok-1');
  assert.equal(await t.execute(), 'tok-1');
  assert.equal(e.state.appended, 1);
  assert.equal(e.state.rendered.action, 'support_chat');
  assert.equal(e.state.rendered.appearance, 'interaction-only');
  assert.equal(e.state.rendered.execution, 'execute');
  assert.equal(e.state.rendered.sitekey, DEFAULT_SITEKEY);
});

test('a blocked script rejects with kind blocked and can be retried', async () => {
  const e = env({ blocked: true });
  const t = e.make();
  await assert.rejects(t.execute(), { kind: 'blocked' });
  await assert.rejects(t.execute(), { kind: 'blocked' });
  assert.equal(e.state.appended, 2);
  assert.equal(e.state.removed, 2);        // each failed element is dropped so the next try is fresh
});

test('an error callback rejects with kind failed', async () => {
  const e = env({ auto: false });
  const t = e.make();
  const p = t.execute();
  await new Promise((r) => setTimeout(r, 20));
  e.state.rendered['error-callback']();
  await assert.rejects(p, { kind: 'failed' });
});

test('dispose removes the widget and is safe to call twice', async () => {
  const e = env();
  const t = e.make();
  await t.execute();
  t.dispose();
  t.dispose();
  assert.deepEqual(e.state.calls.filter((c) => c[0] === 'remove'), [['remove', 'w1']]);
});

const FORBIDDEN = [/تایپ/, /در حال نوشتن/, /ظرف\s*\d+\s*(ثانیه|ساعت)/, /ظرف\s*[۰-۹]+\s*(ثانیه|ساعت)/];

test('copy: generic staff label, no typing indicator, no promised time unless configured', () => {
  assert.equal(LABELS.staff, 'پشتیبانی');
  assert.equal(LABELS.system, 'سامانه');
  const flat = JSON.stringify(COPY) + COPY.replyWithin(5);
  const noConfigured = JSON.stringify({ ...COPY, replyWithin: undefined });
  for (const re of FORBIDDEN) assert.doesNotMatch(noConfigured, re);
  assert.match(flat, /ظرف 5 دقیقه/);
});

test('copy: the privacy line names security and quality use, not "only to answer"', () => {
  assert.doesNotMatch(COPY.privacyNotice, /فقط برای پاسخ/);
  assert.match(COPY.privacyNotice, /امنیت/);
});

test('copy: four starters map to the four server intents', () => {
  assert.deepEqual(COPY.starters.map((s) => s.intent), ['sales', 'demo', 'technical', 'other']);
});
