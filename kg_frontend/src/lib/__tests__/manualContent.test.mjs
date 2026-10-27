// manualContent: groupBySection (pure). enhanceManualRoot needs a real DOM
// (querySelectorAll with :not/:is, classList) and is not covered here.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { groupBySection, enhanceManualRoot } from '../manualContent.js';

test('consecutive items with the same parent segment form one group', () => {
  const items = [
    { id: 1, segments: ['Car', 'Brakes', 'Caution'] },
    { id: 2, segments: ['Car', 'Brakes', 'Notice'] },
    { id: 3, segments: ['Car', 'Engine', 'Hint'] },
    { id: 4, segments: ['Car', 'Brakes', 'Hint'] },
  ];
  const g = groupBySection(items);
  assert.deepEqual(g.map((x) => [x.parent, x.items.map((i) => i.id)]),
    [['Brakes', [1, 2]], ['Engine', [3]], ['Brakes', [4]]]);
});

test('items with 0-1 segments share the empty parent', () => {
  const g = groupBySection([{ id: 1 }, { id: 2, segments: ['Only'] }, { id: 3, segments: [] }]);
  assert.equal(g.length, 1);
  assert.equal(g[0].parent, '');
  assert.equal(g[0].items.length, 3);
});

test('empty / default input yields no groups', () => {
  assert.deepEqual(groupBySection([]), []);
  assert.deepEqual(groupBySection(), []);
});

test('enhanceManualRoot is a no-op on a missing root', () => {
  assert.doesNotThrow(() => enhanceManualRoot(null));
  assert.doesNotThrow(() => enhanceManualRoot(undefined));
});
