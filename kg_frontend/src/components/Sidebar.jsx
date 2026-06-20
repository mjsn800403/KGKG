'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

// Dashboard sidebar — exact prototype markup. "Active vehicles" is highlighted
// across the whole browsing area; "Account settings" on /settings.
export default function Sidebar() {
  const pathname = usePathname() || '';
  const onSettings = pathname.startsWith('/settings');
  const onFleet = !onSettings;

  return (
    <aside className="sidebar">
      <Link className="sb-brand" href="/browse">
        <img src="/logo.png" alt="KGtechvault" />
        <span>KGtechvault</span>
      </Link>
      <Link className={`sb-link${onFleet ? ' active' : ''}`} href="/browse">
        <span className="dot"></span> خودروهای فعال
      </Link>
      <Link className="sb-link" href="/browse">
        <span className="dot"></span> سفارش‌ها و خریدها
      </Link>
      <Link className={`sb-link${onSettings ? ' active' : ''}`} href="/settings">
        <span className="dot"></span> تنظیمات حساب
      </Link>
      <div style={{ marginTop: 'auto', paddingTop: 30 }}>
        <Link className="sb-link" href="/">
          <span className="dot"></span> خروج از حساب
        </Link>
      </div>
    </aside>
  );
}
