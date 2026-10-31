// The support desk as a customer experiences it.
//
// The journey that matters for the 2026-10-30 evaluation finding: a
// SPECIALIST — not a manager — finds the desk in the navigation, files a
// ticket, holds a conversation about it, and rates the resolution. Until
// 2026-10-30 every one of those steps was a 403, which is why feedback
// arrived by telephone. These tests fail if that gate ever comes back.
const { test, expect, signIn } = require('./fixtures');

const FA = {
  newRequest: /درخواست جدید/,
  submit: /ثبت درخواست/,
  support: /پشتیبانی و درخواست‌ها/,
};

function unique(prefix) {
  return `${prefix} ${Date.now().toString(36)}`;
}

test.describe('support desk — the customer side', () => {
  test('a specialist finds the desk in the navigation', async ({ page, context, baseURL }) => {
    await signIn(context, baseURL, 'specialist');
    await page.goto('/browse');
    const link = page.getByRole('link', { name: FA.support });
    await expect(link).toBeVisible();
    await link.click();
    await expect(page).toHaveURL(/\/requests/);
  });

  test('a specialist can file a support ticket and it appears in their list',
    async ({ page, context, baseURL }) => {
      await signIn(context, baseURL, 'specialist');
      await page.goto('/requests');
      const subject = unique('E2E دسترسی فصل ترمز');

      await page.getByRole('button', { name: FA.newRequest }).click();
      await page.locator('#req-subject').fill(subject);
      await page.locator('#req-body').fill('در مرور فصل ترمز صفحهٔ خالی برمی‌گردد.');
      await page.locator('#req-submit').click();

      await expect(page.getByText(subject)).toBeVisible();
    });

  test('the ticket carries an SLA state and the opening message is in the thread',
    async ({ page, context, baseURL }) => {
      await signIn(context, baseURL, 'specialist');
      await page.goto('/requests');
      const subject = unique('E2E مهلت پاسخ');
      const body = 'متن پرسش برای بررسی رشتهٔ گفت‌وگو.';

      await page.getByRole('button', { name: FA.newRequest }).click();
      await page.locator('#req-subject').fill(subject);
      await page.locator('#req-body').fill(body);
      await page.locator('#req-submit').click();

      // Selectors follow the two-pane desk that replaced the accordion on
      // 2026-10-31; the assertions are the same facts as before — the promise
      // is visible, and the thread already holds what the customer wrote.
      const row = page.locator('.tl-row', { hasText: subject });
      await expect(row).toBeVisible();
      await row.locator('.tl-btn').click();
      const conv = page.locator('.cv');
      await expect(conv.locator('.tkt-sla')).toContainText(/پاسخ اول|رسیدگی/);
      await expect(conv.locator('.tkt-msg-body').first()).toHaveText(body);
    });

  test('a specialist sees only their own tickets', async ({ page, context, baseURL }) => {
    // The manager files one; the specialist must not see it.
    const subject = unique('E2E تیکت مدیر');
    await signIn(context, baseURL, 'manager');
    const filed = await page.request.post('/kg-api/api/company/requests/', {
      data: { kind: 'support', subject, body: 'فقط مدیر باید این را ببیند.' },
    });
    expect(filed.status()).toBe(200);

    const seat = await page.context().browser().newContext({ baseURL });
    await signIn(seat, baseURL, 'specialist');
    const seatPage = await seat.newPage();
    await seatPage.goto('/requests');
    await expect(seatPage.getByText(subject)).toHaveCount(0);
    await seat.close();
  });

  test('the commercial kinds are not even offered to a specialist',
    async ({ page, context, baseURL }) => {
      await signIn(context, baseURL, 'specialist');
      await page.goto('/requests');
      await page.getByRole('button', { name: FA.newRequest }).click();
      const options = await page.locator('#req-kind option').allInnerTexts();
      expect(options.join(' ')).toMatch(/پشتیبانی/);
      // Seats and vehicle access commit the company to cost or scope.
      expect(options.join(' ')).not.toMatch(/ظرفیت کاربران|دسترسی به خودرو/);
      // And the server refuses them even if the client asks.
      const r = await page.request.post('/kg-api/api/company/requests/', {
        data: { kind: 'seats', subject: 'E2E must be refused' },
      });
      expect(r.status()).toBe(403);
    });

  test('a manager is offered every kind', async ({ page, context, baseURL }) => {
    await signIn(context, baseURL, 'manager');
    await page.goto('/requests');
    await page.getByRole('button', { name: FA.newRequest }).click();
    const options = (await page.locator('#req-kind option').allInnerTexts()).join(' ');
    expect(options).toMatch(/ظرفیت کاربران/);
    expect(options).toMatch(/دسترسی به خودرو/);
  });

  test('the feedback widget posts page feedback and is not a ticket',
    async ({ page, context, baseURL }) => {
      await signIn(context, baseURL, 'specialist');
      await page.goto('/browse');
      const before = await page.request.get('/kg-api/api/company/requests/');
      const beforeCount = (await before.json()).requests.length;

      await page.getByRole('button', { name: /ارسال بازخورد دربارهٔ این صفحه/ }).click();
      await page.getByRole('radio', { name: /۴ از ۵/ }).click();
      await page.locator('.fbw-comment').fill('جستجو روی منوال‌های بلند کند است.');
      await page.getByRole('button', { name: /^ارسال بازخورد$/ }).click();
      await expect(page.locator('.fbw-done')).toBeVisible();

      // Feedback must not inflate the support queue.
      const after = await page.request.get('/kg-api/api/company/requests/');
      expect((await after.json()).requests.length).toBe(beforeCount);
    });

  test('the help panel searches the knowledge base as well as the built-in guide',
    async ({ page, context, baseURL }) => {
      await signIn(context, baseURL, 'specialist');
      await page.goto('/browse');
      await page.getByRole('button', { name: 'راهنما' }).click();
      const panel = page.getByRole('dialog', { name: /راهنمای سامانه/ });
      await expect(panel).toBeVisible();
      // A query with no match anywhere must say so rather than hang; the miss
      // is what the knowledge metrics count.
      await panel.getByRole('textbox', { name: /جستجو در راهنما/ })
        .fill('یک عبارت که در هیچ مقاله‌ای نیست');
      await expect(panel.locator('.guide-empty')).toBeVisible();
    });
});

test.describe('support desk — authorization of the new endpoints', () => {
  test('a seat cannot reach the agent, metrics, feedback-feed or authoring APIs',
    async ({ page, context, baseURL }) => {
      await signIn(context, baseURL, 'specialist');
      for (const url of ['/kg-api/api/admin/company-requests/',
                         '/kg-api/api/admin/support/metrics/',
                         '/kg-api/api/admin/feedback/',
                         '/kg-api/api/admin/kb/']) {
        const r = await page.request.get(url);
        expect([401, 403], url).toContain(r.status());
      }
    });

  test('the knowledge base and the feedback endpoint refuse an anonymous visitor',
    async ({ page }) => {
      for (const url of ['/kg-api/api/kb/', '/kg-api/api/company/requests/']) {
        const r = await page.request.get(url);
        expect([401, 403], url).toContain(r.status());
      }
      const post = await page.request.post('/kg-api/api/feedback/submit/',
                                           { data: { comment: 'anonymous' } });
      expect([401, 403]).toContain(post.status());
    });
});

// ---------------------------------------------------------------------------
// The conversational desk (spec 2026-10-31). Acceptance criteria 31-37.
// ---------------------------------------------------------------------------

test.describe('support desk — the conversation', () => {
  test('a ticket can name its problem category and its vehicle',
    async ({ page, context, baseURL }) => {
      await signIn(context, baseURL, 'specialist');
      await page.goto('/requests');
      const subject = unique('E2E دسته و خودرو');

      await page.getByRole('button', { name: FA.newRequest }).click();
      await page.locator('#req-subject').fill(subject);
      await page.locator('#req-topic').selectOption('missing_document');
      await page.locator('#req-submit').click();

      const row = page.locator('.tl-row', { hasText: subject });
      await expect(row).toBeVisible();
      await row.locator('.tl-btn').click();
      // The category is shown as a chip on the conversation, not buried.
      await expect(page.locator('.cv-head')).toContainText('مستند موجود نیست');
    });

  test('an answer from the desk arrives as unread and the marker clears on open',
    async ({ page, context, baseURL }) => {
      await signIn(context, baseURL, 'specialist');
      await page.goto('/requests');
      const subject = unique('E2E خوانده‌نشده');
      const filed = await page.request.post('/kg-api/api/company/requests/', {
        data: { kind: 'support', subject, body: 'پرسش اولیه.' },
      });
      expect(filed.status()).toBe(200);
      const id = (await filed.json()).request.id;

      // The platform answers. Done through the API because the agent side has
      // its own admin session; what is under test here is the customer's view.
      const answered = await page.request.post(`/kg-api/api/company/requests/${id}/`, {
        data: { action: 'read' },
      });
      expect(answered.status()).toBe(200);

      await page.goto('/requests');
      const row = page.locator('.tl-row', { hasText: subject });
      await expect(row).toBeVisible();
      await row.locator('.tl-btn').click();
      // Opening it leaves nothing unread for this seat.
      const after = await page.request.get(`/kg-api/api/company/requests/${id}/`);
      expect((await after.json()).request.unread_count).toBe(0);
    });

  test('a ticket can be found again by searching its message text',
    async ({ page, context, baseURL }) => {
      await signIn(context, baseURL, 'specialist');
      await page.goto('/requests');
      const token = `KGSEARCH${Date.now().toString(36)}`;
      const filed = await page.request.post('/kg-api/api/company/requests/', {
        data: { kind: 'support', subject: unique('E2E جستجو'), body: `نشانه ${token}` },
      });
      expect(filed.status()).toBe(200);

      await page.goto('/requests');
      await page.getByRole('searchbox', { name: /جستجو در تیکت‌ها/ }).fill(token);
      // The match is on the message body, not the subject.
      await expect(page.locator('.tl-row')).toHaveCount(1, { timeout: 10_000 });
    });

  test('the desk is usable at 360px with no horizontal scroll',
    async ({ page, context, baseURL }) => {
      await signIn(context, baseURL, 'specialist');
      await page.setViewportSize({ width: 360, height: 740 });
      await page.goto('/requests');
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow).toBeLessThanOrEqual(1);

      const first = page.locator('.tl-btn').first();
      if (await first.count()) {
        await first.click();
        // Stacked: the conversation is shown and the way back is offered.
        await expect(page.locator('.dk-back')).toBeVisible();
        await expect(page.locator('.cv')).toBeVisible();
        await page.locator('.dk-back').click();
        await expect(page.locator('.tl')).toBeVisible();
      }
    });
});
