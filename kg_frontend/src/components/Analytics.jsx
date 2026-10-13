'use client';
// Sends one Umami page view per client-side route change (see utils/analytics.js
// for why auto-track is off and how URLs are redacted).
import { useEffect } from 'react';
import { usePathname } from 'next/navigation';
import { redact, withUmami } from '@/utils/analytics';

export default function Analytics() {
  const pathname = usePathname();
  useEffect(() => {
    const url = redact(pathname);
    // External referrers keep only their origin (where visitors come from);
    // internal ones go through the same redaction as the page URL.
    let referrer = '';
    try {
      if (document.referrer) {
        const r = new URL(document.referrer);
        referrer = r.origin === location.origin ? redact(r.pathname) : r.origin;
      }
    } catch { /* malformed referrer */ }
    withUmami((u) => u.track((props) => ({ ...props, url, referrer })));
  }, [pathname]);
  return null;
}
