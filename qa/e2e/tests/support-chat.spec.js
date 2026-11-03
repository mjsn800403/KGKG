// Visitor -> human -> visitor journey for the support chat (gate G1), run against
// the LOCAL throwaway stack from qa/e2e/local-support-chat-stack.ps1. It never
// targets production. Turnstile's browser script is faked here (the backend runs
// in DEBUG, which skips verification); everything else is the real stack: the
// Next build, the proxy, Django, the database and a real staff session.
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');
const { test, expect } = require('@playwright/test');
const AxeBuilder = require('@axe-core/playwright').default;

const FIX = process.env.SUPPORT_E2E_FIXTURES;
test.skip(!FIX || !fs.existsSync(FIX), 'needs the local support-chat stack (SUPPORT_E2E_FIXTURES)');
const fixtures = FIX && fs.existsSync(FIX) ? JSON.parse(fs.readFileSync(FIX, 'utf8')) : {};
const STACK = FIX ? path.dirname(FIX) : '';
const BACKEND = path.resolve(__dirname, '../../../KG_backend');
const PY = path.join(BACKEND, '.venv', 'Scripts', 'python.exe');

/** Run Python inside Django against the stack's database; returns parsed JSON. */
function dj(code) {
  const out = execFileSync(PY, ['manage.py', 'shell', '-c', code], {
    cwd: BACKEND,
    env: { ...process.env, DJANGO_DEBUG: 'true', KG_ADMIN_TOKEN: 'x', KG_DB_PATH: path.join(STACK, 'e2e.sqlite3'), KG_DATA_DIR: STACK },
    encoding: 'utf8',
  });
  return JSON.parse(out.trim().split('\n').pop());
}

const FAKE_TURNSTILE = `
window.turnstile = {
  render(el, opts) { window.__tsOpts = opts; return 'w1'; },
  execute() { setTimeout(() => window.__tsOpts.callback('fake-token'), 10); },
  reset() {}, remove() {},
};`;

async function fakeTurnstile(context) {
  await context.route('**/challenges.cloudflare.com/turnstile/v0/api.js*', (route) => route.fulfill({
    status: 200, contentType: 'application/javascript', body: FAKE_TURNSTILE }));
}

async function staffContext(browser, who = 'staff') {
  const context = await browser.newContext({ locale: 'fa-IR' });
  const s = fixtures[who];
  await context.addInitScript(([token, user]) => {
    try {
      sessionStorage.setItem('kg_admin_token', token);
      sessionStorage.setItem('kg_admin_user', JSON.stringify(user));
    } catch { /* storage off */ }
  }, [s.token, { id: s.id, username: s.username }]);
  return context;
}


/** Open the landing page, dismiss the first-visit guidance tour (it overlays the page), open the chat. */
async function openChat(page) {
  await page.goto('/');
  await page.getByRole('button', { name: 'رد کردن راهنما' }).click({ timeout: 6000 }).catch(() => {});
  await page.locator('button.sc-launcher').click();
}
const VISITOR_TEXT = 'سلام، قیمت اشتراک سالانه چند است؟ SECRET-VISITOR-TEXT-1';
const STAFF_TEXT = 'سلام، قیمت‌ها در صفحهٔ خرید است. SECRET-STAFF-TEXT-2';

test.describe.serial('support chat: visitor to human to visitor', () => {
  let staffCtx; let staff; let visitorCtx; let visitor; let threadId; let streamOpens = 0;

  test.beforeAll(async ({ browser }) => {
    dj(`
import json
from api.models import AuditLog
from api.support_chat.models import SupportThread
SupportThread.objects.all().delete()
AuditLog.objects.filter(action__startswith='support_chat.').delete()
print(json.dumps(1))`);
    staffCtx = await staffContext(browser);
    staff = await staffCtx.newPage();
    staff.on('request', (r) => { if (r.url().includes('/api/events/stream/')) streamOpens += 1; });
    await staff.goto('/admin#company-requests');
    await staff.getByRole('button', { name: 'رد کردن راهنما' }).click({ timeout: 6000 }).catch(() => {});
    await staff.getByRole('tab', { name: 'گفتگوهای زنده' }).click();
    await staff.getByRole('button', { name: 'آماده پاسخ' }).click();
    visitorCtx = await browser.newContext({ locale: 'fa-IR' });
    await fakeTurnstile(visitorCtx);
    visitor = await visitorCtx.newPage();
  });
  test.afterAll(async () => { await staffCtx?.close(); await visitorCtx?.close(); });

  test('S1 the panel is Persian RTL and offers the four starters; availability is live without a time promise', async () => {
    await openChat(visitor);
    const panel = visitor.getByRole('dialog', { name: 'گفتگو با پشتیبانی' });
    await expect(panel).toBeVisible();
    await expect(panel).toHaveAttribute('dir', 'rtl');
    await expect(panel.getByText('پشتیبانی آنلاین است')).toBeVisible();
    for (const label of ['قیمت و خرید اشتراک', 'درخواست دمو', 'پرسش یا مشکل فنی', 'سایر']) {
      await expect(panel.getByRole('button', { name: label })).toBeVisible();
    }
    const text = await panel.innerText();
    expect(text).not.toMatch(/ظرف\s*\S+\s*(دقیقه|ثانیه|ساعت)/);   // no promised reply time
    expect(text).not.toMatch(/در حال نوشتن|تایپ/);                  // no typing indicator
  });

  test('S2 accessibility of the open panel (axe, wcag a/aa)', async () => {
    const results = await new AxeBuilder({ page: visitor }).include('.sc-root')
      .withTags(['wcag2a', 'wcag2aa']).analyze();
    expect(results.violations.map((v) => `${v.id}: ${v.nodes.length}`)).toEqual([]);
  });

  test('S3 sending the first message creates one stored thread with no visitor IP or message text in audit', async () => {
    await visitor.getByRole('button', { name: 'قیمت و خرید اشتراک' }).click();
    await visitor.locator('.sc-composer textarea').fill(VISITOR_TEXT);
    await visitor.locator('.sc-send').click();
    await expect(visitor.locator('.sc-bubble', { hasText: 'SECRET-VISITOR-TEXT-1' })).toBeVisible();
    await expect(visitor.locator('.sc-meta[data-delivery="sent"]').first()).toBeVisible();
    const rec = dj(`
import json
from api.models import AuditLog
from api.support_chat.models import SupportThread, SupportMessage
t = SupportThread.objects.get()
print(json.dumps({'id': str(t.pk), 'intent': t.intent, 'status': t.status, 'page': t.source_page,
  'n': SupportMessage.objects.filter(thread=t).count(), 'threads': SupportThread.objects.count(),
  'audit': [str(a.detail) + a.action + str(a.actor_label) for a in AuditLog.objects.all()]}))`);
    threadId = rec.id;
    expect(rec).toMatchObject({ intent: 'sales', status: 'waiting_staff', page: '/', n: 1, threads: 1 });
    expect(rec.audit.join(' ')).not.toContain('SECRET-VISITOR-TEXT-1');
    expect(rec.audit.join(' ')).not.toMatch(/127\.0\.0\.1|::1/);
    // The visitor's browser holds the thread id and token; the message text is not in localStorage.
    const ls = await visitor.evaluate(() => JSON.stringify(localStorage));
    expect(ls).toContain(threadId);
    expect(ls).not.toContain('SECRET-VISITOR-TEXT-1');
  });

  test('S4 the staff inbox receives it as unread, masked, and opening it marks it seen', async () => {
    // No manual refresh and (in this stack) the fallback poll is switched off, so
    // only the event stream can have delivered it; 5 s is far under any poll.
    const row = staff.locator('.scx-row', { hasText: 'SECRET-VISITOR-TEXT-1' });
    await expect(row).toBeVisible({ timeout: 5000 });
    await expect(row.locator('.scx-dot')).toBeVisible();
    await row.click();
    await expect(staff.locator('.scx-msg-body', { hasText: 'SECRET-VISITOR-TEXT-1' })).toBeVisible();
    await expect(row.locator('.scx-dot')).toHaveCount(0);
  });

  test('S4b the admin page holds exactly one event stream for the tab', async () => {
    expect(streamOpens).toBe(1);
  });

  test('S5 the visitor sees the read receipt once staff opened the thread', async () => {
    await expect(visitor.locator('.sc-meta[data-delivery="read"]').first()).toBeVisible();
  });

  test('S6 an authorised agent takes ownership and replies; the visitor receives it as «پشتیبانی» without a name', async () => {
    await staff.getByRole('button', { name: 'برداشتن گفتگو' }).click();
    await expect(staff.getByRole('button', { name: /مسئول: e2e-staff/ })).toBeVisible();
    await staff.getByLabel('پاسخ به مشتری').fill(STAFF_TEXT);
    await staff.getByRole('button', { name: 'ارسال پاسخ' }).click();
    const bubble = visitor.locator('.sc-theirs .sc-bubble', { hasText: 'SECRET-STAFF-TEXT-2' });
    await expect(bubble).toBeVisible({ timeout: 20_000 });
    await expect(visitor.locator('.sc-who').first()).toHaveText('پشتیبانی');
    expect(await visitor.locator('.sc-root').innerText()).not.toContain('e2e-staff');
  });

  test('S7 the interaction is recorded and traceable by ids only', async () => {
    const rec = dj(`
import json
from api.models import AuditLog
from api.support_chat.models import SupportThread
t = SupportThread.objects.get()
rows = list(AuditLog.objects.filter(action__startswith='support_chat.').order_by('id'))
print(json.dumps({'status': t.status, 'assignee': t.assignee.username, 'seen': t.staff_seen_at is not None,
  'actions': [r.action for r in rows], 'blob': ' '.join(str(r.detail) + str(r.target_id) for r in rows)}))`);
    expect(rec.status).toBe('waiting_customer');
    expect(rec.assignee).toBe('e2e-staff');
    expect(rec.seen).toBe(true);
    expect(rec.actions).toEqual(expect.arrayContaining(['support_chat.assign', 'support_chat.reply']));
    expect(rec.blob).not.toContain('SECRET-STAFF-TEXT-2');
    expect(rec.blob).not.toContain('SECRET-VISITOR-TEXT-1');
  });

  test('S8 the visitor reloads and the conversation is restored from the stored thread', async () => {
    await visitor.reload();
    await visitor.getByRole('button', { name: 'رد کردن راهنما' }).click({ timeout: 6000 }).catch(() => {});
    await visitor.locator('button.sc-launcher').click();
    await expect(visitor.locator('.sc-bubble', { hasText: 'SECRET-VISITOR-TEXT-1' })).toBeVisible();
    await expect(visitor.locator('.sc-bubble', { hasText: 'SECRET-STAFF-TEXT-2' })).toBeVisible();
  });

  test('S9 contact is masked for staff until revealed, and revealing is audited without the value', async () => {
    await visitor.getByRole('button', { name: 'افزودن راه ارتباطی' }).click();   // live: one line until asked
    await visitor.getByPlaceholder('شمارهٔ موبایل').fill('09121234567');
    await visitor.getByRole('button', { name: 'ثبت' }).click();
    await expect(visitor.getByPlaceholder('شمارهٔ موبایل')).toHaveCount(0);       // saved, card gone
    await staff.reload();
    await staff.getByRole('tab', { name: 'گفتگوهای زنده' }).click();
    await staff.locator('.scx-row').first().click();
    const contact = staff.locator('.scx-contact');
    await expect(contact).toContainText('•');
    await expect(contact).not.toContainText('09121234567');
    await staff.getByRole('button', { name: 'نمایش اطلاعات تماس' }).click();
    await expect(staff.locator('.scx-contact')).toContainText('09121234567');
    const blob = dj(`
import json
from api.models import AuditLog
print(json.dumps([str(a.detail) + a.action for a in AuditLog.objects.filter(action='support_chat.reveal_contact')]))`);
    expect(blob.length).toBe(1);
    expect(blob.join('')).not.toContain('0912');
  });

  test('S10 closing shows the closed bar and rating to the visitor, and the visitor can continue', async () => {
    await staff.getByRole('button', { name: 'بستن', exact: true }).click();
    await expect(visitor.getByText('این گفتگو بسته شده است')).toBeVisible({ timeout: 20_000 });
    await visitor.getByRole('button', { name: 'عالی' }).click();
    await expect(visitor.getByText('ممنون از امتیاز شما')).toBeVisible();
    await visitor.getByRole('button', { name: 'ادامهٔ گفتگو' }).click();
    await expect(visitor.locator('.sc-composer textarea')).toBeVisible();
  });
});

test.describe('support chat failure and recovery', () => {
  test('F1 a blocked Turnstile script keeps the typed text, creates nothing, and a retry works', async ({ browser }) => {
    dj(`
import json
from api.support_chat.models import SupportThread
SupportThread.objects.all().delete()
print(json.dumps(1))`);
    const ctx = await browser.newContext({ locale: 'fa-IR' });
    await ctx.route('**/challenges.cloudflare.com/**', (route) => route.abort());
    const page = await ctx.newPage();
    await openChat(page);
    await page.getByRole('button', { name: 'سایر' }).click();
    await page.locator('.sc-composer textarea').fill('پیام نگه‌داشته‌شده');
    await page.locator('.sc-send').click();
    await expect(page.getByText('تأیید امنیتی بارگذاری نشد')).toBeVisible();
    await expect(page.locator('.sc-composer textarea')).toHaveValue('پیام نگه‌داشته‌شده');
    await expect(page.locator('.sc-bubble', { hasText: 'پیام نگه‌داشته‌شده' })).toBeVisible();   // marked failed, not lost
    expect(dj(`
import json
from api.support_chat.models import SupportThread
print(json.dumps(SupportThread.objects.count()))`)).toBe(0);
    await ctx.unroute('**/challenges.cloudflare.com/**');
    await fakeTurnstile(ctx);
    await page.getByRole('button', { name: 'تلاش دوباره' }).first().click();
    await expect(page.locator('.sc-meta[data-delivery="sent"]').first()).toBeVisible({ timeout: 20_000 });
    await ctx.close();
  });

  test('F2 a lost create response retries to the same thread and never duplicates the message', async ({ browser }) => {
    dj(`
import json
from api.support_chat.models import SupportThread
SupportThread.objects.all().delete()
print(json.dumps(1))`);
    const ctx = await browser.newContext({ locale: 'fa-IR' });
    await fakeTurnstile(ctx);
    const page = await ctx.newPage();
    let dropped = false;
    await ctx.route('**/kg-api/api/support-chat/threads/', async (route) => {
      if (route.request().method() === 'POST' && !dropped) {
        dropped = true;
        await route.fetch();            // the server stores it...
        await route.abort('failed');    // ...but the answer never arrives
        return;
      }
      await route.continue();
    });
    await openChat(page);
    await page.getByRole('button', { name: 'سایر' }).click();
    await page.locator('.sc-composer textarea').fill('یک پیام');
    await page.locator('.sc-send').click();
    await expect(page.getByText('ارسال نشد').first()).toBeVisible();
    await page.getByRole('button', { name: 'تلاش دوباره' }).first().click();
    await expect(page.locator('.sc-meta[data-delivery="sent"]').first()).toBeVisible({ timeout: 20_000 });
    expect(dj(`
import json
from api.support_chat.models import SupportThread, SupportMessage
print(json.dumps([SupportThread.objects.count(), SupportMessage.objects.count()]))`)).toEqual([1, 1]);
    await ctx.close();
  });

  test('F3 on a phone the open panel is a full-height sheet with no horizontal scroll', async ({ browser }) => {
    const ctx = await browser.newContext({ locale: 'fa-IR', viewport: { width: 375, height: 812 }, isMobile: true, hasTouch: true });
    await fakeTurnstile(ctx);
    const page = await ctx.newPage();
    await openChat(page);
    const box = await page.locator('.sc-panel').boundingBox();
    expect(box.width).toBeGreaterThanOrEqual(374);
    expect(box.height).toBeGreaterThanOrEqual(800);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    const targets = await page.locator('.sc-panel button').evaluateAll((els) => els.filter((e) => e.offsetParent)
      .map((e) => Math.min(e.getBoundingClientRect().width, e.getBoundingClientRect().height)));
    expect(Math.min(...targets)).toBeGreaterThanOrEqual(40);
    await ctx.close();
  });

  test('F4 staff endpoints refuse anonymous callers', async ({ request }) => {
    expect((await request.get('/kg-api/api/admin/support-chat/threads/')).status()).toBe(401);
  });
});
