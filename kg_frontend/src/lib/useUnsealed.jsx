'use client';
// Open an SSR-sealed prop (utils/shieldServer.js) in the browser.
// Returns `plain` when nothing was sealed, undefined while opening, and null
// if it could not be opened (callers show a reload notice).
import { useEffect, useState } from 'react';
import { unseal } from '@/lib/shield';

export default function useUnsealed(sealed, plain) {
  // Result is keyed by the blob it came from, so a new blob reads as
  // "opening" (undefined) without a synchronous reset inside the effect.
  const [opened, setOpened] = useState({ blob: null, value: undefined });
  useEffect(() => {
    if (!sealed) return undefined;
    let live = true;
    unseal(sealed).then((value) => { if (live) setOpened({ blob: sealed, value }); },
      () => { if (live) setOpened({ blob: sealed, value: null }); });
    return () => { live = false; };
  }, [sealed]);
  if (!sealed) return plain;
  return opened.blob === sealed ? opened.value : undefined;
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
