'use client';

import Link from 'next/link';
import { useEffect } from 'react';
import Icon from '@/components/Icon';

// Route-level error boundary. It renders inside the root layout, so it follows
// the site's theme; app/global-error.tsx covers the case where the layout
// itself failed. The technical message stays in the console — the reader gets
// a plain Persian explanation and a way forward.
export default function RouteError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => { console.error(error); }, [error]);

  return (
    <div className="status-page">
      <div className="status-card">
        <span className="status-code" aria-hidden="true">۵۰۰</span>
        <h1>این صفحه بارگذاری نشد</h1>
        <p>
          در دریافت اطلاعات از سامانه مشکلی پیش آمد. یک‌بار دیگر تلاش کنید؛
          اگر باز هم تکرار شد، با پشتیبانی تماس بگیرید.
        </p>
        <div className="status-actions">
          <button type="button" className="btn btn-accent" onClick={reset}><Icon name="refresh" />تلاش دوباره</button>
          <Link className="btn" href="/browse">خودروهای فعال</Link>
        </div>
        {error?.digest && (
          <p className="status-ref">کد پیگیری خطا: <bdi dir="ltr">{error.digest}</bdi></p>
        )}
      </div>
    </div>
  );
}
