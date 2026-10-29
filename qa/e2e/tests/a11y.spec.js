// Automated accessibility scan (axe-core, WCAG 2.1 A/AA rules). Every
// violation is attached to the report; critical and serious ones fail the test.
const AxeBuilder = require('@axe-core/playwright').default;
const { test, expect } = require('./fixtures');

for (const path of ['/', '/login', '/purchase', '/recover']) {
  test(`accessibility scan of ${path}`, async ({ page }, info) => {
    // Third-party bot-check widget is outside our code and never settles headless.
    await page.route('https://challenges.cloudflare.com/**', (r) => r.abort());
    await page.goto(path, { waitUntil: 'load' });
    const r = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
    const summary = r.violations.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length, help: v.help }));
    await info.attach('axe-violations.json', { body: JSON.stringify(summary, null, 2), contentType: 'application/json' });
    expect(r.violations.filter((v) => v.impact === 'critical' || v.impact === 'serious')).toEqual([]);
  });
}
