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
