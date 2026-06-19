// utils/api.js
const API_BASE = 'http://127.0.0.1:8000';

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
    const res = await fetch(`${API_BASE}/`);
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
    const res = await fetch(`${API_BASE}/${encodeURIComponent(brand)}/`);
    console.log(res)
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
    const res = await fetch(`${API_BASE}/${encodeURIComponent(brand)}/${year}/`);
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
    
    const res = await fetch(url);
    
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
// hash fragment) to the title-path segments of the node it points to.
export async function resolveHref(brand, year, model, filename) {
  const encodedBrand = encodeURIComponent(brand);
  const encodedModel = encodeURIComponent(model);
  const url = `${API_BASE}/${encodedBrand}/${year}/${encodedModel}/?href=${encodeURIComponent(filename)}`;

  const res = await fetch(url);
  if (!res.ok) {
    const errorText = await res.text();
    console.error('resolveHref error response:', errorText);
    throw new Error(`Failed to resolve link: ${res.status}`);
  }
  const data = await res.json();
  return data.segments;
}

export async function fetchModels(brand, year, model) {
  try {
    const res = await fetch(`${API_BASE}/${encodeURIComponent(brand)}/${year}/${encodeURIComponent(model)}/`);
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