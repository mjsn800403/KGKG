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

  test('a mismatched brand cannot unlock another vehicle\'s content', async ({ page, context, baseURL }) => {
    // Regression: the per-car gate looked cars up by name AND brand, so a wrong
    // brand skipped the check while the name still selected the vehicle.
    await signIn(context, baseURL, 'other');          // company B, no vehicle granted
    for (const brand of [car.brand, 'Nope']) {
      const d = await page.request.get('/kg-api/api/diagnose/', {
        params: { q: 'P0300', car: car.model, brand } });
      expect(d.status(), `diagnose brand=${brand}`).toBe(403);
      const a = await page.request.post('/kg-api/api/assist/', {
        data: { query: 'engine oil capacity', car: car.model, brand } });
      expect(a.status(), `assist brand=${brand}`).toBe(403);
    }
  });

  test('metrics endpoint is never exposed through the public origin', async ({ request }) => {
    const r = await request.get('/kg-api/api/metrics/');
    expect(r.status()).toBe(403);
  });
});
