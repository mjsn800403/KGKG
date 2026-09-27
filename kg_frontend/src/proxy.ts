import { NextResponse, type NextRequest } from 'next/server';

// Per-request CSP nonce, so script-src no longer needs 'unsafe-inline'.
// Next.js reads the nonce from the request's CSP header and stamps it on its
// own inline bootstrap scripts; the root layout passes it to THEME_BOOT.
// nginx only adds its static CSP when the upstream sent none (see the
// $kg_csp map in sites-available/kgkg), so this header is the one that applies.
// Signed-in-only pages. A visitor with no session cookie is redirected here,
// on the server, before any page shell renders (it used to flash the page and
// rely on client-side checks). Brand content routes (/Toyota/2023/...) count.
// /admin is not listed: its token lives in sessionStorage, checked client-side.
const PROTECTED = /^\/(browse|assistant|team|settings|requests|admin-review)(\/|$)/;
const BRAND_ROUTE = /^\/[A-Z][^/]*\/\d{4}(\/|$)/;

export function proxy(request: NextRequest) {
  const path = request.nextUrl.pathname;
  if ((PROTECTED.test(path) || BRAND_ROUTE.test(path)) &&
      !request.cookies.get(kg_portal_token)?.value) {
    const url = request.nextUrl.clone();
    url.pathname = /login;
    url.search = `?next=${encodeURIComponent(path + request.nextUrl.search)}`;
    return NextResponse.redirect(url);
  }
  const nonce = Buffer.from(crypto.randomUUID()).toString('base64');
  const dev = process.env.NODE_ENV !== 'production';
  const csp = [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' https://challenges.cloudflare.com https://static.cloudflareinsights.com${dev ? " 'unsafe-eval'" : ''}`,
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "img-src 'self' data: blob:",
    "font-src 'self' data: https://fonts.gstatic.com",
    "connect-src 'self' https://cloudflareinsights.com https://challenges.cloudflare.com",
    // 'self': the wiring-diagram section embeds the TIS EWD viewer from /kg-api/media.
    "frame-src 'self' https://challenges.cloudflare.com",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "object-src 'none'",
  ].join('; ');

  const headers = new Headers(request.headers);
  headers.set('x-nonce', nonce);
  // Lets server pages send a signed-out visitor to /login?next=<this page>.
  headers.set('x-pathname', request.nextUrl.pathname + request.nextUrl.search);
  headers.set('Content-Security-Policy', csp);
  const res = NextResponse.next({ request: { headers } });
  res.headers.set('Content-Security-Policy', csp);
  return res;
}

export const config = {
  matcher: [
    {
      source: '/((?!_next/static|_next/image|favicon.ico|brand/|fonts/|robots.txt|api/).*)',
      missing: [
        { type: 'header', key: 'next-router-prefetch' },
        { type: 'header', key: 'purpose', value: 'prefetch' },
      ],
    },
  ],
};
