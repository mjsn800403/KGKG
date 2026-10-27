// Authentication boundaries as a browser experiences them.
const { test, expect, carPath } = require('./fixtures');

// The login button stays disabled until Cloudflare Turnstile issues a token.
// Automation must not solve a CAPTCHA, so the widget is replaced by a stub that
// hands out a token the server cannot verify: the test proves the server
// rejects it (fail-closed), not that the check can be skipped.
async function stubTurnstile(page) {
  await page.route('https://challenges.cloudflare.com/**', (route) => route.fulfill({
    contentType: 'application/javascript',
    body: `window.turnstile = { render: (el, o) => { setTimeout(() => o.callback('qa-unverifiable-token'), 50); return 'w1'; },
                                reset() {}, remove() {} };`,
  }));
}

test.describe('authentication', () => {
  for (const path of ['/browse', '/assistant', '/settings', '/team', carPath]) {
    test(`signed-out visit to ${path} is redirected to login with next=`, async ({ page }) => {
      await page.goto(path);
      await expect(page).toHaveURL(/\/login\?next=/);
      const next = new URL(page.url()).searchParams.get('next');
      expect(next.toLowerCase()).toBe(path.toLowerCase());
      await expect(page.locator('#login-username')).toBeVisible();
    });
  }

  test('login cannot be submitted before the bot check passes', async ({ page }) => {
    await page.route('https://challenges.cloudflare.com/**', (r) => r.abort());
    await page.goto('/login');
    await page.locator('#login-username').fill('qa_e2e_manager');
    await page.locator('#login-password').fill('irrelevant-password');
    await expect(page.getByRole('button', { name: /ادامه/ })).toBeDisabled();
  });

  test('server rejects a bot-check token it cannot verify (fail-closed)', async ({ page, context }) => {
    await stubTurnstile(page);
    await page.goto('/login');
    await page.locator('#login-username').fill('qa_e2e_manager');
    await page.locator('#login-password').fill('wrong-or-right-does-not-matter');
    const button = page.getByRole('button', { name: /ادامه/ });
    await expect(button).toBeEnabled();
    const [resp] = await Promise.all([
      page.waitForResponse((r) => r.url().includes('/api/auth/login/')),
      button.click(),
    ]);
    expect(resp.status()).toBe(403);
    await expect(page.locator('.pform-error')).toBeVisible();
    await expect(page).toHaveURL(/\/login/);
    const cookies = await context.cookies();
    expect(cookies.find((c) => c.name === 'kg_portal_token')).toBeUndefined();
  });

  test('a forged session cookie is not accepted', async ({ page, context, baseURL }) => {
    await context.addCookies([{ name: 'kg_portal_token', value: 'f'.repeat(64),
      domain: new URL(baseURL).hostname, path: '/' }]);
    const r = await page.request.get('/kg-api/api/auth/me/');
    expect(r.status()).toBe(401);
  });
});
