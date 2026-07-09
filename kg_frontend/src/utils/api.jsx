// utils/api.js
// Backend origin. Set NEXT_PUBLIC_API_BASE at build/run time for any non-local
// deploy (it's inlined into the client bundle, hence the NEXT_PUBLIC_ prefix).
// Falls back to localhost for dev. Trailing slash is stripped so callers can
// safely concatenate `${API_BASE}/path`.
const API_BASE = (process.env.NEXT_PUBLIC_API_BASE || 'http://127.0.0.1:8000').replace(/\/+$/, '');

// The backend returns node content with image references as relative
// "/media/..." paths (it doesn't know its own public-facing host/port -
// that's our concern, same as every other endpoint). Rewrite them to
// absolute URLs against API_BASE before the content is injected into the
// page, otherwise the browser resolves them against the frontend's own
// origin instead of the backend's.
function withAbsoluteMediaUrls(nodes) {
  for (const node of nodes) {
    if (node?.content) {
      node.content = node.content.replaceAll('="/media/', `="${API_BASE}/media/`);
    }
  }
  return nodes;
}

// For /  (distinct list of brand names across all cars)
export async function fetchAllBrands() {
  try {
    const res = await fetch(`${API_BASE}/`, { cache: 'no-store' });
    if (!res.ok) {
      throw new Error(`Failed to fetch brand list: ${res.status}`);
    }
    return res.json();
  } catch (error) {
    console.error('fetchAllBrands error:', error);
    throw error;
  }
}

// For /brand/
export async function fetchBrands(brand) {
  try {
    const res = await fetch(`${API_BASE}/${encodeURIComponent(brand)}/`, { cache: 'no-store' });
    // console.log(res)
    if (!res.ok) {
      const error = await res.json().catch(() => ({}));
      throw new Error(error.error || `Failed to fetch brands: ${res.status}`);
    }
    return res.json();
  } catch (error) {
    console.error('fetchBrands error:', error);
    throw error;
  }
}

// For /brand/year/
export async function fetchYearData(brand, year) {
  try {
    const res = await fetch(`${API_BASE}/${encodeURIComponent(brand)}/${year}/`, { cache: 'no-store' });
    if (!res.ok) {
      throw new Error(`Failed to fetch year data: ${res.status}`);
    }
    return res.json();
  } catch (error) {
    console.error('fetchYearData error:', error);
    throw error;
  }
}

// utils/api.js - Update fetchNodes
export async function fetchNodes(brand, year, model, pathSegments = []) {
  try {
    const encodedBrand = encodeURIComponent(brand);
    const encodedModel = encodeURIComponent(model);

    // Path segments are sent as repeated "seg" query params, not joined into
    // the URL path. A node title can contain a literal "/" (e.g.
    // "Service Data [11/2022 - ]"), and a WSGI server decodes %2F in the URL
    // path into a real "/" before Django ever sees it, making it
    // indistinguishable from an actual segment separator. Query string values
    // don't have this problem - "/" has no special meaning there.
    const qs = new URLSearchParams();
    pathSegments.filter(Boolean).forEach((seg) => qs.append('seg', seg));
    const query = qs.toString();

    const url = query
      ? `${API_BASE}/${encodedBrand}/${year}/${encodedModel}/?${query}`
      : `${API_BASE}/${encodedBrand}/${year}/${encodedModel}/`;

    console.log('Fetching URL:', url);
    
    const res = await fetch(url, { cache: 'no-store' });
    
    if (!res.ok) {
      const errorText = await res.text();
      console.error('API Error Response:', errorText);
      throw new Error(`Failed to fetch: ${res.status}`);
    }
    
    return withAbsoluteMediaUrls(await res.json());
  } catch (error) {
    console.error('fetchNodes error:', error);
    throw error;
  }
}
// Resolve a manual cross-reference link (e.g. "pages/40738.html", with no
// hash fragment) to the node it points to. The link may belong to a
// different vehicle variant than the one currently being viewed (e.g. a
// "Land Cruiser Base" page pointing at a "Land Cruiser 1958" page), so the
// backend searches every registered car, not just the current one - the
// response tells us which car the target actually belongs to.
export async function resolveHref(brand, year, model, filename) {
  const encodedBrand = encodeURIComponent(brand);
  const encodedModel = encodeURIComponent(model);
  const url = `${API_BASE}/${encodedBrand}/${year}/${encodedModel}/?href=${encodeURIComponent(filename)}`;

  const res = await fetch(url);
  if (!res.ok) {
    const error = await res.json().catch(() => ({}));
    const err = new Error(error.error || `Failed to resolve link: ${res.status}`);
    err.notFound = res.status === 404;
    throw err;
  }
  return res.json(); // { brand, year, model, segments }
}

// Fetch the raw HTML content of a manual page that has no node (an orphan
// cross-link target served straight from the car's source folder).
// Returns { title, content } or null if the page doesn't exist.
export async function fetchRawPage(brand, year, model, filename) {
  const encodedBrand = encodeURIComponent(brand);
  const encodedModel = encodeURIComponent(model);
  const url = `${API_BASE}/${encodedBrand}/${year}/${encodeURIComponent(model)}/?page=${encodeURIComponent(filename)}`;

  const res = await fetch(url);
  if (!res.ok) return null;
  const data = await res.json();
  if (data?.content) {
    data.content = data.content.replaceAll('="/media/', `="${API_BASE}/media/`);
  }
  return data; // { title, content }
}

// Cross-lingual semantic search over a car's manual (backend /api/search/, which
// rides the RAG retriever). A Persian OR English query matches the English data —
// the old per-car SQL LIKE this replaces was English-only. Returns the same
// lightweight navigation shape as before ([{ title, path, segments, ... }]), so
// build a result's app URL from its `segments` exactly like node navigation.
export async function searchNodes(brand, year, model, q, limit = 30) {
  try {
    const params = new URLSearchParams({ q, car: model, limit: String(limit) });
    if (brand) params.set('brand', brand);
    const url = `${API_BASE}/api/search/?${params.toString()}`;
    const res = await fetch(url, { cache: 'no-store' });
    if (!res.ok) return [];
    return res.json();
  } catch (error) {
    console.error('searchNodes error:', error);
    return [];
  }
}

// Build the in-app navigation URL for a search result from its segment chain.
export function buildNodeHref(brand, year, model, segments = []) {
  const base = `/${encodeURIComponent(brand)}/${year}/${encodeURIComponent(model)}`;
  if (!segments.length) return base;
  return `${base}/${segments.map(encodeURIComponent).join('/')}`;
}

export async function fetchModels(brand, year, model) {
  try {
    const res = await fetch(`${API_BASE}/${encodeURIComponent(brand)}/${year}/${encodeURIComponent(model)}/`, { cache: 'no-store' });
    if (!res.ok) {
      const error = await res.json().catch(() => ({}));
      throw new Error(error.error || `Failed to fetch models: ${res.status}`);
    }
    return withAbsoluteMediaUrls(await res.json());
  } catch (error) {
    console.error('fetchModels error:', error);
    throw error;
  }
}

// --- purchase request ------------------------------------------------------
// Legal-entity documentation purchase requests. Stored server-side so the sales
// team can follow up. Returns { ok: true, id } on success; throws on failure so
// the form can surface an error instead of a false "we'll contact you".
export async function submitPurchaseRequest(payload) {
  const res = await fetch(`${API_BASE}/api/purchase-request/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data?.error || `ثبت درخواست ناموفق بود: ${res.status}`);
  return data;
}

// --- portal auth (company seats issued by the admin) ------------------------
// Token + user snapshot live in localStorage so the dashboard can show the
// company name and filter the fleet by granted cars.
const PORTAL_TOKEN_KEY = 'kg_portal_token';
const PORTAL_USER_KEY = 'kg_portal_user';

export function getPortalToken() {
  try { return localStorage.getItem(PORTAL_TOKEN_KEY) || ''; } catch { return ''; }
}

export function getPortalUser() {
  try { return JSON.parse(localStorage.getItem(PORTAL_USER_KEY) || 'null'); } catch { return null; }
}

export function setPortalSession(token, user) {
  try {
    if (token) localStorage.setItem(PORTAL_TOKEN_KEY, token);
    else localStorage.removeItem(PORTAL_TOKEN_KEY);
    if (user) localStorage.setItem(PORTAL_USER_KEY, JSON.stringify(user));
    else localStorage.removeItem(PORTAL_USER_KEY);
  } catch { /* storage unavailable */ }
}

export async function portalLogin(username, password) {
  const res = await fetch(`${API_BASE}/api/auth/login/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data?.error || `ورود ناموفق بود: ${res.status}`);
  setPortalSession(data.token, data.user);
  return data;
}

/** Refresh the logged-in portal user from the server (picks up admin grant/revoke). */
export async function portalRefreshMe() {
  const token = getPortalToken();
  if (!token) return null;
  const res = await fetch(`${API_BASE}/api/auth/me/`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: 'no-store',
  });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401) {
    setPortalSession('', null);
    const err = new Error('unauthorized');
    err.unauthorized = true;
    throw err;
  }
  if (!res.ok) throw new Error(data?.error || `me: ${res.status}`);
  setPortalSession(token, data.user);
  return data.user;
}

/** Cars this portal seat may open — always read live from the backend. */
export async function fetchGrantedFleet() {
  const token = getPortalToken();
  if (!token) return [];
  const res = await fetch(`${API_BASE}/api/auth/fleet/`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: 'no-store',
  });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401) {
    setPortalSession('', null);
    const err = new Error('unauthorized');
    err.unauthorized = true;
    throw err;
  }
  if (!res.ok) throw new Error(data?.error || `fleet: ${res.status}`);
  return data.items || [];
}

export async function portalLogout() {
  const token = getPortalToken();
  setPortalSession('', null);
  if (!token) return;
  try {
    await fetch(`${API_BASE}/api/auth/logout/`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    });
  } catch { /* best-effort */ }
}

// Best-effort usage signal for the admin's activity report.
export async function logActivity(action, detail = '') {
  const token = getPortalToken();
  if (!token) return;
  try {
    await fetch(`${API_BASE}/api/activity/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ action, detail }),
    });
  } catch { /* never block the UI on telemetry */ }
}

// --- admin panel API ---------------------------------------------------------
// All gated server-side by KG_ADMIN_TOKEN (Bearer). Uses the same stored token
// as the review queue below.
async function adminFetch(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...adminHeaders(),
      ...(options.headers || {}),
    },
  });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 || res.status === 503) {
    const err = new Error(data?.error || 'unauthorized');
    err.unauthorized = true;
    throw err;
  }
  if (!res.ok) throw new Error(data?.error || `admin api: ${res.status}`);
  return data;
}

export async function adminLogin(username, password) {
  const res = await fetch(`${API_BASE}/api/admin/login/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data?.error || `ورود ادمین ناموفق بود: ${res.status}`);
  setAdminToken(data.token, data.admin);
  return data;
}

export const adminApi = {
  overview: () => adminFetch('/api/admin/overview/'),
  packages: () => adminFetch('/api/admin/packages/'),
  requests: () => adminFetch('/api/admin/requests/'),
  setRequestStatus: (id, status) =>
    adminFetch(`/api/admin/requests/${id}/status/`, { method: 'POST', body: JSON.stringify({ status }) }),
  cars: () => adminFetch('/api/admin/cars/'),
  companies: () => adminFetch('/api/admin/companies/'),
  createCompany: (payload) =>
    adminFetch('/api/admin/companies/', { method: 'POST', body: JSON.stringify(payload) }),
  companyDetail: (id) => adminFetch(`/api/admin/companies/${id}/`),
  updateCompany: (id, payload) =>
    adminFetch(`/api/admin/companies/${id}/`, { method: 'POST', body: JSON.stringify(payload) }),
  setCompanyAccess: (id, accesses) =>
    adminFetch(`/api/admin/companies/${id}/access/`, { method: 'POST', body: JSON.stringify({ accesses }) }),
  users: (companyId) =>
    adminFetch(`/api/admin/users/${companyId ? `?company_id=${companyId}` : ''}`),
  createUser: (payload) =>
    adminFetch('/api/admin/users/', { method: 'POST', body: JSON.stringify(payload) }),
  updateUser: (id, payload) =>
    adminFetch(`/api/admin/users/${id}/`, { method: 'POST', body: JSON.stringify(payload) }),
  deleteUser: (id) =>
    adminFetch(`/api/admin/users/${id}/`, { method: 'POST', body: JSON.stringify({ delete: true }) }),
  setUserAccess: (id, accesses, overridePurchase = true) =>
    adminFetch(`/api/admin/users/${id}/access/`, {
      method: 'POST',
      body: JSON.stringify({ accesses, override_purchase: overridePurchase }),
    }),
  activity: (params = {}) => {
    const qs = new URLSearchParams(params).toString();
    return adminFetch(`/api/admin/activity/${qs ? `?${qs}` : ''}`);
  },
};

// --- admin auth (review queue + pin) ---------------------------------------
// The pin and review-queue endpoints are admin-gated server-side (KG_ADMIN_TOKEN).
// The token is typed by the admin at runtime and kept only in sessionStorage —
// it is NEVER baked into the client bundle. Sent as a Bearer header, which the
// Django gate (api/ratelimit.require_admin_token) verifies.
const ADMIN_TOKEN_KEY = 'kg_admin_token';
const ADMIN_USER_KEY = 'kg_admin_user';

export function getAdminToken() {
  try { return sessionStorage.getItem(ADMIN_TOKEN_KEY) || ''; } catch { return ''; }
}

export function getAdminUser() {
  try { return JSON.parse(sessionStorage.getItem(ADMIN_USER_KEY) || 'null'); } catch { return null; }
}

export function setAdminToken(token, admin = null) {
  try {
    if (token) sessionStorage.setItem(ADMIN_TOKEN_KEY, token);
    else sessionStorage.removeItem(ADMIN_TOKEN_KEY);
    if (admin) sessionStorage.setItem(ADMIN_USER_KEY, JSON.stringify(admin));
    else if (!token) sessionStorage.removeItem(ADMIN_USER_KEY);
  } catch { /* sessionStorage unavailable */ }
}

export function adminLogout() {
  setAdminToken('', null);
}

function adminHeaders() {
  const t = getAdminToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

// Human-in-the-loop: record a 👍/👎 verdict on an assistant answer. Best-effort
// (never blocks the UI). The backend turns these into a guarded ranking boost.
export async function rateAnswer({ query, verdict, mode, topBlobs, blobId, reason, comment, brand, model, car }) {
  try {
    await fetch(`${API_BASE}/api/feedback/rate/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, verdict, mode, top_blobs: topBlobs,
                             blob_id: blobId, reason, comment, brand, model, car }),
    });
    return true;
  } catch (error) {
    console.error('rateAnswer error:', error);
    return false;
  }
}

// Expert action: pin a verified source for a query pattern. The backend embeds
// pattern_query so future near-matches surface this source at the top, tagged
// expert_verified. Returns true on success.
export async function pinFeedback({ patternQuery, appUrl, blobId, title, note, by }) {
  try {
    const res = await fetch(`${API_BASE}/api/feedback/pin/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...adminHeaders() },
      body: JSON.stringify({
        pattern_query: patternQuery, app_url: appUrl,
        blob_id: blobId, title, note, by,
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (res.status === 401 || res.status === 503) {
      const err = new Error(data.error || 'unauthorized');
      err.unauthorized = true;
      throw err;
    }
    if (!res.ok) throw new Error(data.error || `pin failed: ${res.status}`);
    return !!data.ok;
  } catch (error) {
    console.error('pinFeedback error:', error);
    throw error;
  }
}

// Admin review queue: recent 👎 verdicts (for an expert to inspect / pin a fix).
// Admin-gated: returns { unauthorized: true } if the token is missing/wrong so
// the page can prompt for it.
export async function fetchRecentFeedback(limit = 50) {
  try {
    const res = await fetch(`${API_BASE}/api/feedback/recent/?limit=${limit}`, {
      headers: { ...adminHeaders() },
    });
    if (res.status === 401 || res.status === 503) {
      return { count: 0, items: [], unauthorized: true };
    }
    if (!res.ok) throw new Error(`recent feedback: ${res.status}`);
    return res.json();
  } catch (error) {
    console.error('fetchRecentFeedback error:', error);
    return { count: 0, items: [] };
  }
}