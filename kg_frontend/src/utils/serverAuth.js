// Server-only helper: read the portal session token from the request cookie so
// server components (SSR) can forward it to the paid content API. Importing
// `next/headers` keeps this out of any client bundle.
import { cookies } from 'next/headers';

export async function portalTokenCookie() {
  try {
    return (await cookies()).get('kg_portal_token')?.value || '';
  } catch {
    return '';
  }
}

// SSR mirror of the user's browsing-mode preference (source of truth is the DB
// field PortalUser.browse_mode; the cookie is refreshed from /auth/me on login
// and whenever the toggle is flipped). Returns 'classic' only when explicitly
// set, so any missing/unknown value falls back to the modern browser.
export async function browseModeCookie() {
  try {
    const v = (await cookies()).get('kg_browse_mode')?.value || '';
    return v === 'classic' ? 'classic' : 'modern';
  } catch {
    return 'modern';
  }
}
