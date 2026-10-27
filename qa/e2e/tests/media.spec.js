// Paid media is served by nginx after an auth_request to the backend gate.
// Regression for a confirmed bypass: dot-segment and double-slash paths were
// authorized as one folder and served from another (audit-evidence/07-security).
// Raw HTTP is used on purpose: a browser URL parser would normalize the path
// before sending it, which is exactly what an attacker's client does not do.
const http = require('http');
const { test, expect, data } = require('./fixtures');

const OTHER = '4Runner%20Platinum/GTY1268854.png';      // a car the manager is NOT granted

function rawGet(baseURL, path, token) {
  const u = new URL(baseURL);
  return new Promise((resolve, reject) => {
    const req = http.request({ host: u.hostname, port: u.port, path, method: 'GET',
      headers: { Cookie: `kg_portal_token=${token}` } }, (res) => {
      let n = 0;
      res.on('data', (c) => { n += c.length; });
      res.on('end', () => resolve({ status: res.statusCode, bytes: n }));
    });
    req.on('error', reject);
    req.end();
  });
}

test.describe('media gate', () => {
  test('signed-out request for paid media is refused', async ({ baseURL }) => {
    const r = await rawGet(baseURL, `/kg-api/media/${OTHER}`, 'none');
    expect(r.status).toBe(401);
  });

  test('a car outside the subscription is refused, however the path is spelled', async ({ baseURL }) => {
    const token = data.tokens.manager;
    for (const p of [`/kg-api/media/${OTHER}`,
                     `/kg-api/media/_parts_assets/../${OTHER}`,
                     `/kg-api/media/_parts_assets/%2e%2e/${OTHER}`,
                     `/kg-api/media/nonexistent/../${OTHER}`,
                     `/kg-api/media//${OTHER}`]) {
      const r = await rawGet(baseURL, p, token);
      expect(r.status, p).toBe(403);
    }
  });

  test('a cached allow for a shared folder does not leak to another car', async ({ baseURL }) => {
    const token = data.tokens.manager;
    const ok = await rawGet(baseURL, '/kg-api/media/_parts_assets/1e69cf78_336307C.gif', token);
    expect(ok.status).toBe(200);                         // primes the auth cache with a 204
    const r = await rawGet(baseURL, `/kg-api/media/_parts_assets/../${OTHER}`, token);
    expect(r.status).toBe(403);
  });
});
