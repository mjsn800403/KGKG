// Cross-role and cross-tenant boundaries.
const { test, expect, car, carPath, signIn } = require('./fixtures');

test.describe('authorization', () => {
  test('specialist without a grant cannot read the vehicle manual', async ({ page, context, baseURL }) => {
    await signIn(context, baseURL, 'specialist');
    const r = await page.request.get(`/kg-api/${car.brand}/${car.year}/${encodeURIComponent(car.model)}/`);
    expect([401, 403, 404]).toContain(r.status());
    await page.goto(carPath);
    await expect(page.locator('body')).not.toContainText('Engine Mechanical');
  });

  test('specialist cannot reach admin or team-management APIs', async ({ page, context, baseURL }) => {
    await signIn(context, baseURL, 'specialist');
    for (const url of ['/kg-api/api/admin/users/', '/kg-api/api/admin/companies/',
                       '/kg-api/api/team/analytics/', '/kg-api/api/org/nodes/']) {
      const r = await page.request.get(url);
      expect([401, 403], url).toContain(r.status());
    }
  });

  test('another company cannot see QA-E2E-A data', async ({ page, context, baseURL }) => {
    await signIn(context, baseURL, 'other');
    const me = await (await page.request.get('/kg-api/api/auth/me/')).json();
    expect(JSON.stringify(me)).not.toContain('QA-E2E-A');
    const graph = await page.request.get('/kg-api/api/org/graph/');
    if (graph.status() === 200) {
      const g = JSON.stringify(await graph.json());
      expect(g).not.toContain('qa_e2e_manager');
      expect(g).not.toContain('qa_e2e_specialist');
    } else {
      expect([401, 403]).toContain(graph.status());
    }
    const manual = await page.request.get(`/kg-api/${car.brand}/${car.year}/${encodeURIComponent(car.model)}/`);
    expect([401, 403, 404]).toContain(manual.status());
  });

  test('metrics endpoint is never exposed through the public origin', async ({ request }) => {
    const r = await request.get('/kg-api/api/metrics/');
    expect(r.status()).toBe(403);
  });
});
