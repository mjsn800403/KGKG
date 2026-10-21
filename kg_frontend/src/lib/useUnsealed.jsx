'use client';
// Open an SSR-sealed prop (utils/shieldServer.js) in the browser.
// Returns `plain` when nothing was sealed, undefined while opening, and null
// if it could not be opened (callers show a reload notice).
import { useEffect, useState } from 'react';
import { unseal } from '@/lib/shield';

export default function useUnsealed(sealed, plain) {
  const [value, setValue] = useState(sealed ? undefined : plain);
  useEffect(() => {
    if (!sealed) { setValue(plain); return undefined; }
    let live = true;
    setValue(undefined);
    unseal(sealed).then((v) => { if (live) setValue(v); }, () => { if (live) setValue(null); });
    return () => { live = false; };
  }, [sealed, plain]);
  return value;
}

export function SealedNotice({ value }) {
  if (value === undefined) return <div className="empty-state">در حال بارگذاری…</div>;
  return (
    <div className="error-box">
      <p>نمایش این صفحه ناموفق بود.</p>
      <button type="button" className="back-link" onClick={() => window.location.reload()}>بارگذاری دوباره</button>
    </div>
  );
}
