'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import Icon from './Icon';
import { getPortalUser, portalLogout, teamApi } from '../utils/api';

const FA_DIGITS = '۰۱۲۳۴۵۶۷۸۹';
const fa = (n) => String(n).replace(/\d/g, (d) => FA_DIGITS[+d]);

// Dashboard sidebar, grouped by what the reader is doing: documents, the team
// (managers only), and their own account. The signed-in person and company sit
// at the bottom instead of competing with the breadcrumb in every top bar.
export default function Sidebar() {
  const pathname = usePathname() || '';
  const onSettings = pathname.startsWith('/settings');
  const onAssistant = pathname.startsWith('/assistant');
  const onRequests = pathname.startsWith('/requests');
  const onAnalytics = pathname.startsWith('/team/analytics');
  const onChats = pathname.startsWith('/team/chats');
  const onTeam = pathname.startsWith('/team') && !onAnalytics && !onChats;
  const onFleet = !onSettings && !onAssistant && !onTeam && !onAnalytics && !onChats && !onRequests;

  // Capability flags + identity come from the cached portal user (resolved
  // after mount to avoid an SSR hydration mismatch).
  const [me, setMe] = useState(null);
  const [openRequests, setOpenRequests] = useState(0);
  useEffect(() => {
    const read = () => setMe(getPortalUser());
    read();
    window.addEventListener('kg:me', read);
    return () => window.removeEventListener('kg:me', read);
  }, []);

  const manage = !!me?.can_manage_team;
  // Team page AND analytics are visible to everyone except a leaf on the org
  // graph — a non-leaf user gets reports for their own subtree (matches the
  // production rule these flags were changed to).
  const viewTeam = !!me?.can_view_team;
  const analytics = viewTeam;

  // Open tickets, badged so pending work is visible without opening the page.
  // Fetched for every seat, not only managers: the count the API returns is
  // already scoped to what the viewer may see (their own tickets, or the
  // company's for a manager).
  useEffect(() => {
    if (!me) return undefined;
    let cancelled = false;
    teamApi.requests()
      .then((d) => { if (!cancelled) setOpenRequests(d?.meta?.open_count || 0); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [me]);

  const name = me?.display_name || me?.username || '';
  const initials = name ? name.trim().slice(0, 2) : 'KG';

  // On a phone the sidebar collapses into a horizontal strip, which left the
  // account card and the logout link off-screen. They live in this menu there.
  const [accountOpen, setAccountOpen] = useState(false);
  const accountRef = useRef(null);
  useEffect(() => {
    if (!accountOpen) return undefined;
    const onDown = (e) => { if (!accountRef.current?.contains(e.target)) setAccountOpen(false); };
    const onKey = (e) => { if (e.key === 'Escape') setAccountOpen(false); };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey); };
  }, [accountOpen]);

  return (
    <aside className="sidebar">
      <Link className="sb-brand" href="/browse">
        <img src="/brand/logo-mark.png" alt="KGtechvault" />
        <span>KGtechvault</span>
      </Link>

      <div className="sb-group" role="group" aria-label="مستندات">
        <span className="sb-group-label">مستندات</span>
        <Link className={`sb-link${onFleet ? ' active' : ''}`} href="/browse" data-tour="nav-fleet">
          <Icon name="car" /> خودروهای فعال
        </Link>
        <Link className={`sb-link${onAssistant ? ' active' : ''}`} href="/assistant" data-tour="nav-assistant">
          <Icon name="bot" /> دستیار هوشمند
        </Link>
      </div>

      {/* Support is its own group and is shown to EVERY seat. While this link
          was manager-only, a specialist with a problem had no way into the desk
          even though the page would have served them — the navigation was the
          last part of the 403 that sent people to the telephone. */}
      <div className="sb-group" role="group" aria-label="پشتیبانی">
        <span className="sb-group-label">پشتیبانی</span>
        <Link className={`sb-link${onRequests ? ' active' : ''}`} href="/requests" data-tour="nav-requests">
          <Icon name="mail" /> پشتیبانی و درخواست‌ها
          {openRequests > 0 && (
            <span className="sb-badge" aria-label={`${fa(openRequests)} درخواست باز`}>{fa(openRequests)}</span>
          )}
        </Link>
      </div>

      {(manage || viewTeam) && (
        <div className="sb-group" role="group" aria-label="تیم">
          <span className="sb-group-label">تیم</span>
          {viewTeam && (
            <Link className={`sb-link${onTeam ? ' active' : ''}`} href="/team" data-tour="nav-team">
              <Icon name="users" /> تیم و کارکنان
            </Link>
          )}
          {analytics && (
            <Link className={`sb-link${onAnalytics ? ' active' : ''}`} href="/team/analytics" data-tour="nav-analytics">
              <Icon name="chart" /> تحلیل و گزارش‌ها
            </Link>
          )}
          {analytics && (
            <Link className={`sb-link${onChats ? ' active' : ''}`} href="/team/chats">
              <Icon name="bot" /> گفتگوهای دستیار
            </Link>
          )}
        </div>
      )}

      <div className="sb-group" role="group" aria-label="حساب">
        <span className="sb-group-label">حساب</span>
        <Link className={`sb-link${onSettings ? ' active' : ''}`} href="/settings" data-tour="nav-settings">
          <Icon name="gear" /> تنظیمات حساب
        </Link>
      </div>

      <div className="sb-account" ref={accountRef}>
        <button
          type="button" className={`sb-link sb-account-btn${accountOpen ? ' active' : ''}`}
          aria-expanded={accountOpen} aria-haspopup="menu"
          onClick={() => setAccountOpen((v) => !v)}
        >
          <span className="sb-user-avatar" aria-hidden="true">{initials}</span>
          <span>حساب من</span>
        </button>
        {accountOpen && (
          <div className="sb-account-menu" role="menu">
            {me && (
              <div className="sb-user">
                <span className="sb-user-avatar" aria-hidden="true">{initials}</span>
                <span className="sb-user-text"><b>{name}</b><small>{me.role_label || me.company}</small></span>
              </div>
            )}
            <Link className="sb-link" href="/settings" role="menuitem" onClick={() => setAccountOpen(false)}>
              <Icon name="gear" /> تنظیمات حساب
            </Link>
            <Link className="sb-link" href="/" role="menuitem" onClick={() => { setAccountOpen(false); portalLogout(); }}>
              <Icon name="logout" /> خروج از حساب
            </Link>
          </div>
        )}
      </div>

      <div className="sb-logout-wrap">
        {me && (
          <div className="sb-user" title={[name, me.company, me.role_label].filter(Boolean).join(' · ')}>
            <span className="sb-user-avatar" aria-hidden="true">{initials}</span>
            <span className="sb-user-text">
              <b>{name}</b>
              <small>{me.role_label || me.company}</small>
            </span>
          </div>
        )}
        <Link className="sb-link" href="/" onClick={() => portalLogout()}>
          <Icon name="logout" /> خروج از حساب
        </Link>
      </div>
    </aside>
  );
}
