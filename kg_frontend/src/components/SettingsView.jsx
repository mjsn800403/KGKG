'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import Icon from './Icon';
import Switch from './Switch';
import { applyTheme } from './ThemeToggle';
import { getPortalUser, updateBrowseMode } from '../utils/api';

// Interactive account settings: working tabs, a theme picker (light/dark) wired
// to the same persisted store as the header toggle, and a "restart site tour"
// action. Account details now reflect the real signed-in user + company.
export default function SettingsView() {
  const [tab, setTab] = useState('account');
  const [theme, setTheme] = useState('dark');
  const [me, setMe] = useState(null);
  const [mode, setMode] = useState('modern');

  useEffect(() => {
    setTheme(document.documentElement.getAttribute('data-theme') || 'dark');
    const u0 = getPortalUser();
    setMe(u0);
    setMode(u0?.browse_mode === 'classic' ? 'classic' : 'modern');
    const onTheme = (e) => setTheme(e.detail);
    const onMe = () => {
      const u = getPortalUser();
      setMe(u);
      setMode(u?.browse_mode === 'classic' ? 'classic' : 'modern');
    };
    window.addEventListener('kg:theme', onTheme);
    window.addEventListener('kg:me', onMe);
    return () => {
      window.removeEventListener('kg:theme', onTheme);
      window.removeEventListener('kg:me', onMe);
    };
  }, []);

  const restartTour = () => window.dispatchEvent(new CustomEvent('kg:tour'));

  const chooseMode = async (m) => {
    if (m === mode) return;
    setMode(m); // optimistic; onMe reconciles from the saved user
    try { await updateBrowseMode(m); } catch { setMode(getPortalUser()?.browse_mode === 'classic' ? 'classic' : 'modern'); }
  };

  return (
    <div className="settings-grid">
      <div className="settings-tabs">
        <div className={`stab${tab === 'account' ? ' active' : ''}`} onClick={() => setTab('account')}>
          <Icon name="user" /> اطلاعات حساب
        </div>
        <div className={`stab${tab === 'notif' ? ' active' : ''}`} onClick={() => setTab('notif')}>
          <Icon name="bell" /> اعلان‌ها
        </div>
        <div className={`stab${tab === 'security' ? ' active' : ''}`} onClick={() => setTab('security')}>
          <Icon name="shield" /> امنیت و دسترسی
        </div>
      </div>

      <div>
        {tab === 'account' && (
          <>
            <div className="acct-card">
              <h3><Icon name="building" /> مشخصات حساب</h3>
              <div className="acct-row"><span className="k">نام شرکت</span><span className="v">{me?.company || '—'}</span></div>
              <div className="acct-row"><span className="k">کاربر</span><span className="v">{me?.display_name || me?.username || '—'}</span></div>
              <div className="acct-row"><span className="k">نقش سازمانی</span><span className="v">{me?.role_label || '—'}</span></div>
              {me?.email && <div className="acct-row"><span className="k">ایمیل</span><span className="v ltr">{me.email}</span></div>}
              <div className="acct-row"><span className="k">پشتیبانی</span><span className="v ltr">021-92001404</span></div>
            </div>

            {me?.can_manage_team && (
              <div className="acct-card">
                <h3><Icon name="users" /> تیم شما</h3>
                <div className="acct-row"><span className="k">مدیریت کارکنان</span>
                  <Link className="btn btn-accent" href="/team">مدیریت تیم ←</Link></div>
                {me?.can_view_analytics && (
                  <div className="acct-row" style={{ borderBottom: 'none' }}><span className="k">گزارش استفاده</span>
                    <Link className="btn" href="/team/analytics">مشاهده تحلیل‌ها</Link></div>
                )}
              </div>
            )}

            <div className="acct-card">
              <h3><Icon name="sun" /> نمایش و ظاهر</h3>
              <div className="theme-pick">
                <button className={theme === 'light' ? 'active' : ''} onClick={() => applyTheme('light')}>
                  <Icon name="sun" /> حالت روشن
                </button>
                <button className={theme === 'dark' ? 'active' : ''} onClick={() => applyTheme('dark')}>
                  <Icon name="moon" /> حالت تاریک
                </button>
              </div>
            </div>
            <div className="acct-card">
              <h3><Icon name="catalog" /> شیوه مرور محتوا</h3>
              <p style={{ margin: '0 0 0.75rem', fontSize: '0.85rem', opacity: 0.75, lineHeight: 1.7 }}>
                انتخاب کنید صفحه‌های محتوای خودرو چگونه نمایش داده شوند.
              </p>
              <div className="theme-pick">
                <button className={mode === 'modern' ? 'active' : ''} onClick={() => chooseMode('modern')}>
                  <Icon name="catalog" /> نوین (نوار کناری + صفحه یکپارچه)
                </button>
                <button className={mode === 'classic' ? 'active' : ''} onClick={() => chooseMode('classic')}>
                  <Icon name="manual" /> کلاسیک (پیمایش کارتی مرحله‌به‌مرحله)
                </button>
              </div>
            </div>

            <div className="acct-card">
              <h3><Icon name="question" /> راهنما</h3>
              <div className="acct-row" style={{ borderBottom: 'none' }}>
                <span className="k">راهنمای گام‌به‌گام سایت</span>
                <button className="btn" onClick={restartTour}>شروع دوبارهٔ راهنما</button>
              </div>
            </div>
          </>
        )}

        {tab === 'notif' && (
          <>
            <div className="notif-item"><div><div className="t">اعلان خرید مستند جدید</div><div className="d">با هر خرید موفق مستند، اعلان دریافت کنید</div></div><Switch on /></div>
            <div className="notif-item"><div><div className="t">اعلان به‌روزرسانی منوال تعمیر</div><div className="d">هنگام به‌روزرسانی محتوای مستندات خریداری‌شده</div></div><Switch on /></div>
            <div className="notif-item"><div><div className="t">اعلان ورود از دستگاه جدید</div><div className="d">هشدار امنیتی برای ورود از دستگاه ناشناس</div></div><Switch on /></div>
            <div className="notif-item"><div><div className="t">خلاصه هفتگی فعالیت</div><div className="d">ایمیل خلاصه فعالیت‌های حساب هر هفته</div></div><Switch /></div>
          </>
        )}

        {tab === 'security' && (
          <div className="acct-card">
            <h3><Icon name="shield" /> امنیت و دسترسی</h3>
            <div className="acct-row"><span className="k">آخرین ورود</span>
              <span className="v ltr">{me?.last_login_at ? new Date(me.last_login_at).toLocaleString('fa-IR') : '—'}</span></div>
            <div className="acct-row"><span className="k">وضعیت حساب</span>
              <span className="v">{me?.locked ? 'قفل‌شده' : (me?.active === false ? 'غیرفعال' : 'فعال')}</span></div>
            <div className="acct-row" style={{ borderBottom: 'none' }}><span className="k">ورود دو مرحله‌ای</span>
              <span className="v">به‌زودی</span></div>
          </div>
        )}
      </div>
    </div>
  );
}
