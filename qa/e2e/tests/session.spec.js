// Signed-in journeys with a session seeded into the QA database copy.
const { test, expect, data, car, carPath, signIn } = require('./fixtures');

test.describe('signed-in manager', () => {
  test.beforeEach(async ({ context, baseURL }) => { await signIn(context, baseURL, 'manager'); });

  test('profile API identifies the right account and company', async ({ page }) => {
    const r = await page.request.get('/kg-api/api/auth/me/');
    expect(r.status()).toBe(200);
    const me = await r.json();
    expect(JSON.stringify(me)).toContain('qa_e2e_manager');
    expect(JSON.stringify(me)).toContain('QA-E2E-A');
  });

  test('fleet view lists the granted vehicle', async ({ page }) => {
    await page.goto('/browse');
    await expect(page.getByRole('heading', { level: 1 })).toContainText('پنل دسترسی');
    await expect(page.locator('body')).toContainText(new RegExp(car.model, 'i'));
  });

  test('opening the vehicle from the fleet loads its manual', async ({ page }) => {
    await page.goto('/browse');
    await page.getByRole('link', { name: new RegExp(car.model, 'i') }).first().click();
    await expect(page).toHaveURL(new RegExp(`/${car.year}/`));
    await expect(page.locator('body')).not.toContainText('ناموفق بود', { timeout: 20_000 });
    // The table of contents renders as links into the manual.
    await expect(page.locator('main a, [role="tree"] a, nav a').nth(3)).toBeVisible({ timeout: 20_000 });
  });

  test('manual content API is sealed against scraping (content shield)', async ({ page }) => {
    // Content responses are only issued to the app's own client, which first
    // fetches a per-session shield key; a bare API client is refused. Search
    // escaping and SQL metacharacters are covered at integration level
    // (KG_backend/api/test_qa_catalog.py).
    const r = await page.request.get(
      `/kg-api/${car.brand}/${car.year}/${encodeURIComponent(car.model)}/?q=oil`);
    expect(r.status()).toBe(403);
    expect(await r.json()).toMatchObject({ error: 'shield' });
  });

  test('retrieval assistant answers from the manuals without the LLM', async ({ page }) => {
    const r = await page.request.post('/kg-api/api/assist/', {
      data: { query: 'engine oil capacity', brand: car.brand, model: car.model },
    });
    expect(r.status()).toBe(200);
    const body = await r.json();
    expect(Array.isArray(body.hits)).toBe(true);
    expect(body.hits.length).toBeGreaterThan(0);
    for (const h of body.hits.slice(0, 3)) expect(h).toHaveProperty('score');
  });

  test('settings page shows the account', async ({ page }) => {
    await page.goto('/settings');
    await expect(page).toHaveURL(/\/settings/);
    await expect(page.locator('body')).toContainText(/تنظیمات|حساب/);
  });
});

test.describe('logout', () => {
  test('UI logout ends the session server-side', async ({ page, context, baseURL }) => {
    const token = await signIn(context, baseURL, 'manager_logout');
    await page.goto('/browse');
    await page.getByRole('link', { name: /خروج از حساب/ }).last().click();
    await expect.poll(async () => (await context.cookies()).some((c) => c.name === 'kg_portal_token'))
      .toBe(false);
    const r = await page.request.get('/kg-api/api/auth/me/', {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(r.status()).toBe(401);                        // token revoked, not just forgotten
    await page.goto('/browse');
    await expect(page).toHaveURL(/\/login/);
  });
});
