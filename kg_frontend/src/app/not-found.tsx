import Link from 'next/link';
import Icon from '@/components/Icon';

// Shown for an address that matches nothing — including a first path segment
// that is not a brand (see app/[brand]/page.jsx). Rendered inside the root
// layout, so it follows the site's theme instead of a hard-coded dark slab.
export default function NotFound() {
  return (
    <div className="status-page">
      <div className="status-card">
        <span className="status-code" aria-hidden="true">۴۰۴</span>
        <h1>این صفحه پیدا نشد</h1>
        <p>
          نشانی‌ای که باز کرده‌اید وجود ندارد، یا صفحه‌ای که دنبالش بودید جابه‌جا شده است.
          از فهرست خودروهای فعال شروع کنید یا به صفحهٔ اصلی برگردید.
        </p>
        <div className="status-actions">
          <Link className="btn btn-accent" href="/browse"><Icon name="car" />خودروهای فعال</Link>
          <Link className="btn" href="/">صفحهٔ اصلی</Link>
        </div>
      </div>
    </div>
  );
}
