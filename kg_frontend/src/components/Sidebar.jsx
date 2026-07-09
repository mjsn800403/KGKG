'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import Icon from './Icon';
import { portalLogout } from '../utils/api';

// Dashboard sidebar — exact prototype markup, with a proper icon per section.
// "Active vehicles" is highlighted across the whole browsing area.
export default function Sidebar() {
  const pathname = usePathname() || '';
  const onSettings = pathname.startsWith('/settings');
  const onAssistant = pathname.startsWith('/assistant');
  const onFleet = !onSettings && !onAssistant;

  return (
    <aside className="sidebar">
      <Link className="sb-brand" href="/browse">
        <img src="/logo.png" alt="KGtechvault" />
        <span>KGtechvault</span>
      </Link>
      <Link className={`sb-link${onFleet ? ' active' : ''}`} href="/browse" data-tour="nav-fleet">
        <Icon name="car" /> خودروهای فعال
      </Link>
      <Link className={`sb-link${onAssistant ? ' active' : ''}`} href="/assistant" data-tour="nav-assistant">
        <Icon name="bot" /> دستیار هوشمند
      </Link>
      <Link className={`sb-link${onSettings ? ' active' : ''}`} href="/settings" data-tour="nav-settings">
        <Icon name="gear" /> تنظیمات حساب
      </Link>
      <div className="sb-logout-wrap">
        <Link className="sb-link" href="/" onClick={() => portalLogout()}>
          <Icon name="logout" /> خروج از حساب
        </Link>
      </div>
    </aside>
  );
}
