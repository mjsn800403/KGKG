'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import Icon from './Icon';
import { getPortalUser, portalLogout } from '../utils/api';

// Dashboard sidebar. "Active vehicles" is highlighted across the browsing area.
// The Team + Analytics sections appear only for users whose capabilities allow
// them (company managers), read from the cached portal user on mount.
export default function Sidebar() {
  const pathname = usePathname() || '';
  const onSettings = pathname.startsWith('/settings');
  const onAssistant = pathname.startsWith('/assistant');
  const onRequests = pathname.startsWith('/requests');
  const onTeam = pathname.startsWith('/team') && !pathname.startsWith('/team/analytics');
  const onAnalytics = pathname.startsWith('/team/analytics');
  const onFleet = !onSettings && !onAssistant && !onTeam && !onAnalytics && !onRequests;

  // Capability flags come from the cached portal user (resolved after mount to
  // avoid an SSR hydration mismatch).
  const [caps, setCaps] = useState({ manage: false, analytics: false });
  useEffect(() => {
    const read = () => {
      const u = getPortalUser();
      setCaps({
        manage: !!u?.can_manage_team,
        analytics: !!(u?.can_view_analytics || u?.can_manage_team),
      });
    };
    read();
    window.addEventListener('kg:me', read);
    return () => window.removeEventListener('kg:me', read);
  }, []);

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
      {caps.manage && (
        <Link className={`sb-link${onTeam ? ' active' : ''}`} href="/team" data-tour="nav-team">
          <Icon name="users" /> تیم و کارکنان
        </Link>
      )}
      {caps.manage && (
        <Link className={`sb-link${onRequests ? ' active' : ''}`} href="/requests" data-tour="nav-requests">
          <Icon name="cart" /> درخواست‌ها
        </Link>
      )}
      {caps.analytics && (
        <Link className={`sb-link${onAnalytics ? ' active' : ''}`} href="/team/analytics" data-tour="nav-analytics">
          <Icon name="chart" /> تحلیل و گزارش‌ها
        </Link>
      )}
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
