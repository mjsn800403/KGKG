// Signed-out journeys: what any visitor (and any crawler or attacker) sees.
const { test, expect } = require('./fixtures');

test.describe('public pages', () => {
  test('landing renders the product and links to pricing and login', async ({ page }) => {
    const res = await page.goto('/');
    expect(res.status()).toBe(200);
    await expect(page).toHaveTitle(/KGTechVault|KG/i);
    await expect(page.locator('body')).toContainText('KGTechVault');
    await expect(page.locator('a[href="/login"]').first()).toBeVisible();
    await expect(page.locator('a[href*="/purchase"]').first()).toBeAttached();
  });

  test('pricing page loads with plans', async ({ page }) => {
    const res = await page.goto('/purchase');
    expect(res.status()).toBe(200);
    await expect(page.locator('#main')).toContainText(/اشتراک|پلن|ماهانه|سالانه/);
  });

  test('unknown page is a real 404 with a way back', async ({ page }) => {
    const res = await page.goto('/this-page-does-not-exist-qa');
    expect(res.status()).toBe(404);
    await expect(page.getByRole('heading', { level: 1 })).toContainText('این صفحه پیدا نشد');
  });

  test('pages carry a per-request CSP nonce and anti-framing headers', async ({ page }) => {
    const a = await page.goto('/login');
    const b = await page.goto('/login');
    const cspA = a.headers()['content-security-policy'] || '';
    const cspB = b.headers()['content-security-policy'] || '';
    expect(cspA).toContain("frame-ancestors 'none'");
    expect(cspA).toMatch(/'nonce-[A-Za-z0-9+/=]+'/);
    expect(cspA).not.toContain("'unsafe-eval'");
    expect(cspA).not.toBe(cspB);                       // nonce is per request
    expect(a.headers()['x-frame-options']).toBe('DENY');
    expect(a.headers()['x-content-type-options']).toBe('nosniff');
    expect(a.headers()['x-powered-by']).toBeUndefined();
  });

  test('no uncaught script errors on the landing page', async ({ page }) => {
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    expect(errors).toEqual([]);
  });
});
