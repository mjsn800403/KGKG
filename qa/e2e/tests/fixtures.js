// Shared helpers: seeded accounts and session cookies from qa/stack.sh.
const fs = require('fs');
const base = require('@playwright/test');

const FIXTURES = process.env.QA_FIXTURES || '/qa/fixtures.json';
const data = JSON.parse(fs.readFileSync(FIXTURES, 'utf8'));
const car = data.car;
const carPath = `/${car.brand.toLowerCase()}/${car.year}/${car.model.toLowerCase().replace(/\s+/g, '-')}`;

// Reproduces the state a real login leaves behind: the backend's HttpOnly
// session cookie plus the user snapshot the UI keeps in localStorage
// (utils/api.jsx setPortalSession). Only the Turnstile step is skipped.
async function signIn(context, baseURL, who) {
  const token = data.tokens[who];
  if (!token) throw new Error(`no seeded token for ${who}`);
  const { hostname } = new URL(baseURL);
  await context.addCookies([{ name: 'kg_portal_token', value: token, domain: hostname,
    path: '/', httpOnly: true, sameSite: 'Lax' }]);
  const me = await context.request.get('/kg-api/api/auth/me/', {
    headers: { Authorization: `Bearer ${token}` } });
  if (me.status() !== 200) throw new Error(`seeded session for ${who} rejected: ${me.status()}`);
  const user = (await me.json()).user;
  await context.addInitScript((u) => {
    try { localStorage.setItem('kg_portal_user', JSON.stringify(u)); } catch { /* storage off */ }
  }, user);
  return token;
}

const test = base.test.extend({});
module.exports = { test, expect: base.expect, data, car, carPath, signIn };
