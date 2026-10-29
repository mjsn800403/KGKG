// Browser E2E suite. Target: the isolated QA stack (qa/stack.sh), never
// production. QA_ORIGIN is the stack's single-origin proxy.
const { defineConfig, devices } = require('@playwright/test');

const origin = process.env.QA_ORIGIN || 'http://127.0.0.1:8130';
if (/kgtechvault\.com|:8000\b|:3000\b/.test(origin)) {
  throw new Error(`refusing to run E2E against production (${origin})`);
}

module.exports = defineConfig({
  testDir: './tests',
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,       // journeys share seeded accounts; keep order deterministic
  workers: 1,
  retries: 0,                 // a flaky test is a finding, not something to retry away
  reporter: [
    ['list'],
    ['junit', { outputFile: 'results/junit.xml' }],
    ['json', { outputFile: 'results/results.json' }],
    ['html', { outputFolder: 'results/html', open: 'never' }],
  ],
  use: {
    baseURL: origin,
    locale: 'fa-IR',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'firefox', use: { ...devices['Desktop Firefox'] }, testMatch: /public\.spec/ },
    { name: 'mobile', use: { ...devices['Pixel 7'] }, testMatch: /public\.spec/ },
  ],
});
