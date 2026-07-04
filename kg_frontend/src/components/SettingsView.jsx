'use client';

import { useEffect, useState } from 'react';
import Icon from './Icon';
import Switch from './Switch';
import { applyTheme } from './ThemeToggle';

// Interactive account settings: working tabs, a theme picker (light/dark) wired
// to the same persisted store as the header toggle, and a "restart site tour"
// action. The old page only showed a static notifications list.
export default function SettingsView() {
  const [tab, setTab] = useState('account');
  const [theme, setTheme] = useState('dark');

  useEffect(() => {
    setTheme(document.documentElement.getAttribute('data-theme') || 'dark');
    const onTheme = (e) => setTheme(e.detail);
    window.addEventListener('kg:theme', onTheme);
    return () => window.removeEventListener('kg:theme', onTheme);
  }, []);

  const restartTour = () => window.dispatchEvent(new CustomEvent('kg:tour'));

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
              <div className="acct-row"><span className="k">نام شرکت</span><span className="v">KGTECHVAULT Company</span></div>
              <div className="acct-row"><span className="k">نوع حساب</span><span className="v">شخص حقوقی</span></div>
              <div className="acct-row"><span className="k">پشتیبانی</span><span className="v ltr">021-92001404</span></div>
              <div className="acct-row"><span className="k">ایمیل</span><span className="v ltr">mj.salimi@khadamatgostar.com</span></div>
            </div>

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
            <div className="acct-row"><span className="k">ورود دو مرحله‌ای</span><Switch on /></div>
            <div className="acct-row"><span className="k">نمایش تاریخچهٔ ورود</span><span className="v">فعال</span></div>
            <div className="acct-row" style={{ borderBottom: 'none' }}><span className="k">خروج از سایر دستگاه‌ها</span><button className="btn">خروج همه</button></div>
          </div>
        )}
      </div>
    </div>
  );
}
