import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Don't advertise the framework in an x-powered-by header.
  poweredByHeader: false,
  // ops/deploy/deploy.sh builds each release into its own .next-<sha> and
  // swaps the .next symlink, so a build never overwrites the files the live
  // server is reading. Unset (dev, CI, next start) it is the usual .next.
  distDir: process.env.KG_NEXT_DIST || '.next',

  // Local development only. In production nginx serves Django under /kg-api on
  // the same origin, which is what the client bundle asks for and what the CSP
  // in src/proxy.ts allows (connect-src 'self'). Without an equivalent on a dev
  // machine the browser cannot reach the backend at all: a cross-origin
  // NEXT_PUBLIC_API_BASE is refused by that CSP. Set KG_DEV_API_PROXY to the
  // local Django origin to get the same shape here:
  //
  //   KG_DEV_API_PROXY=http://127.0.0.1:8000 npm run dev
  //
  // Unset — which is every deployed environment — this adds nothing.
  // Next normalises a trailing slash with a 308 before a rewrite runs, which
  // would turn every Django URL (they all end in '/') into a redirect loop.
  // Only disabled when the dev proxy is in use, so deployed behaviour is
  // untouched.
  skipTrailingSlashRedirect: Boolean(process.env.KG_DEV_API_PROXY),

  async rewrites() {
    const target = process.env.KG_DEV_API_PROXY;
    if (!target) return [];
    const origin = target.replace(/\/+$/, '');
    // Two rules, because ':path*' does not keep a trailing slash and every
    // Django URL ends in one — without the first rule the backend sees
    // '/api/health' and answers with its api catch-all 404.
    return [
      { source: '/kg-api/:path*/', destination: `${origin}/:path*/` },
      { source: '/kg-api/:path*', destination: `${origin}/:path*` },
    ];
  },
};

export default nextConfig;
