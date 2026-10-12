'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import Icon from './Icon';
import Switch from './Switch';
import { applyTheme } from './ThemeToggle';
import { getPortalUser, updateBrowseMode, updateOtpEnabled, updateNotifyPrefs, portalRefreshMe } from '../utils/api';

// Interactive account settings: working tabs, a theme picker (light/dark) wired
// to the same persisted store as the header toggle, and a "restart site tour"
// action. Account details now reflect the real signed-in user + company.
export default function SettingsView() {
  const [tab, setTab] = useState('account');
  const [theme, setTheme] = useState('dark');
  const [me, setMe] = useState(null);
  const [mode, setMode] = useState('modern');
  const [otpErr, setOtpErr] = useState('');
  const [otpBusy, setOtpBusy] = useState(false);

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
    // Cached user may predate fields like has_phone/otp_enabled: reload live.
    portalRefreshMe().then((u) => { if (u) { setMe(u); } }).catch(() => {});
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

  const hasPhone = !!me?.has_phone;
  const otpOn = hasPhone && me?.otp_enabled !== false;
  const toggleOtp = async (next) => {
    if (!hasPhone || otpBusy) return;
    setOtpErr(''); setOtpBusy(true);
    try { setMe(await updateOtpEnabled(next)); }
    catch (e) { setOtpErr(e.message || 'ذخیره ناموفق بود.'); }
    finally { setOtpBusy(false); }
  };

  const [notifErr, setNotifErr] = useState('');
  const setNotify = async (field, on) => {
    if (!hasPhone) return;
    setNotifErr('');
    setMe((m) => ({ ...m, [field]: on }));   // optimistic
    try { setMe(await updateNotifyPrefs({ [field]: on })); }
    catch (e) { setNotifErr(e.message || 'ذخیره ناموفق بود.'); setMe(getPortalUser()); }
  };
  const notifRow = (field, title, desc) => (
    <div className="notif-item" style={{ opacity: hasPhone ? 1 : 0.55 }}>
      <div><div className="t">{title}</div><div className="d">{desc}</div></div>
      <span style={{ pointerEvents: hasPhone ? 'auto' : 'none' }}>
        <Switch checked={hasPhone && me?.[field] !== false} onChange={(v) => setNotify(field, v)} />
      </span>
    </div>
  );

  return (
    <div className="settings-grid">
      <div className="settings-tabs" role="tablist" aria-label="بخش‌های تنظیمات">
        {[
          { id: 'account', icon: 'user', label: 'اطلاعات حساب' },
          { id: 'notif', icon: 'bell', label: 'اعلان‌ها' },
          { id: 'security', icon: 'shield', label: 'امنیت و دسترسی' },
        ].map((t) => (
          <button
            key={t.id} type="button" role="tab" aria-selected={tab === t.id}
            className={`stab${tab === t.id ? ' active' : ''}`} onClick={() => setTab(t.id)}
          >
            <Icon name={t.icon} /> {t.label}
          </button>
        ))}
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
              <div className="acct-row">
                <span className="k">پشتیبانی</span>
                <span className="v">
                  <a href="tel:+982192001404"><bdi dir="ltr">021 9200 1404</bdi></a>
                  <small style={{ color: 'var(--text-faint)' }}> · داخلی ۳۰۴</small>
                </span>
              </div>
            </div>

            {me?.can_view_team && (
              <div className="acct-card">
                <h3><Icon name="users" /> تیم شما</h3>
                <div className="acct-row"><span className="k">مدیریت کارکنان</span>
                  <Link className="btn btn-accent" href="/team">مدیریت تیم ←</Link></div>
                {me?.can_view_team && (
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
            {notifRow('notify_manual_update', 'اعلان به‌روزرسانی منوال تعمیر', 'پیامک هنگام به‌روزرسانی محتوای خودروهایی که به آن‌ها دسترسی دارید')}
            {notifRow('notify_new_device', 'اعلان ورود از دستگاه جدید', 'پیامک هشدار امنیتی هنگام ورود به حساب از دستگاه ناشناس')}
            {!hasPhone && <div style={{ fontSize: '0.8rem', opacity: 0.7, marginTop: 8 }}>برای این حساب شماره موبایل ثبت نشده است؛ اعلان‌های پیامکی غیرفعال‌اند.</div>}
            {notifErr && <div style={{ fontSize: '0.8rem', color: '#e5484d', marginTop: 8 }}>{notifErr}</div>}
          </>
        )}

        {tab === 'security' && (
          <div className="acct-card">
            <h3><Icon name="shield" /> امنیت و دسترسی</h3>
            <div className="acct-row"><span className="k">آخرین ورود</span>
              <span className="v"><bdi dir="ltr" style={{ unicodeBidi: 'isolate' }}>{me?.last_login_at ? new Date(me.last_login_at).toLocaleString('fa-IR', { timeZone: 'Asia/Tehran' }) : '—'}</bdi></span></div>
            <div className="acct-row"><span className="k">وضعیت حساب</span>
              <span className="v">{me?.locked ? 'قفل‌شده' : (me?.active === false ? 'غیرفعال' : 'فعال')}</span></div>
            <div className="acct-row" style={{ borderBottom: 'none', alignItems: 'center' }}>
              <span className="k">
                ورود دو مرحله‌ای (کد پیامکی)
                <div style={{ fontSize: '0.8rem', opacity: 0.7, marginTop: 4 }}>
                  {hasPhone
                    ? (otpOn ? 'فعال — هنگام ورود کد به موبایل شما پیامک می‌شود.' : 'غیرفعال — ورود فقط با رمز عبور.')
                    : 'غیرفعال — برای این حساب شماره موبایل ثبت نشده است. برای فعال‌سازی با مدیر حساب تماس بگیرید.'}
                </div>
                {otpErr && <div style={{ fontSize: '0.8rem', color: '#e5484d', marginTop: 4 }}>{otpErr}</div>}
              </span>
              <span className="v" style={{ opacity: hasPhone ? 1 : 0.45, pointerEvents: hasPhone && !otpBusy ? 'auto' : 'none' }}>
                <Switch checked={otpOn} onChange={toggleOtp} />
              </span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
