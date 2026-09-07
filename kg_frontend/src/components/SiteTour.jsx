'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { usePathname } from 'next/navigation';

// Lightweight first-visit walkthrough — no external library (works offline).
// Targets are marked with data-tour attributes around the app. Runs once
// automatically on the landing page (localStorage 'kg-tour-done'), and can be
// re-launched any time from the floating "؟" button or via:
//   window.dispatchEvent(new CustomEvent('kg:tour'))

const STEPS = {
  '/': [
    {
      sel: '[data-tour="login-btn"]',
      title: 'خوش آمدید 👋',
      body: 'به KGtechvault خوش آمدید! از اینجا وارد حساب کاربری می‌شوید و به مستندات فنی خودروها دسترسی پیدا می‌کنید.',
    },
    {
      sel: '[data-tour="doc-layers"]',
      title: 'چهار لایه مستند',
      body: 'برای هر خودرو چهار نوع مستند داریم: فهرست قطعات، منوال تعمیر، زمان استاندارد و ابزار مخصوص.',
    },
    {
      sel: '[data-tour="vin-box"]',
      title: 'بررسی پوشش خودرو',
      body: 'شماره شاسی (VIN) خودرو را اینجا وارد کنید تا ببینید چه مستنداتی برای آن موجود است.',
    },
    {
      sel: '[data-tour="support"]',
      title: 'پشتیبانی',
      body: 'راه‌های تماس با ما — تلفن و ایمیل پشتیبانی — همیشه پایین صفحه در دسترس است.',
    },
  ],
  '/browse': [
    {
      sel: '[data-tour="nav-fleet"]',
      title: 'خودروهای فعال',
      body: 'فهرست خودروهایی که مستندات آن‌ها فعال است. با کلیک روی هر خودرو وارد مستنداتش می‌شوید.',
    },
    {
      sel: '[data-tour="model-filter"]',
      title: 'فیلتر مدل',
      body: 'با این دکمه‌ها خودروها را بر اساس مدل فیلتر کنید — مثلاً همه bZ4X ها یا همه Land Cruiser ها با هم.',
    },
    {
      sel: '[data-tour="nav-assistant"]',
      title: 'دستیار هوشمند',
      body: 'سؤال تعمیراتی یا کد خطا (DTC) دارید؟ دستیار هوشمند بر اساس دفترچه‌های رسمی پاسخ می‌دهد.',
    },
    {
      sel: '[data-tour="nav-purchase"]',
      title: 'درخواست خرید مستندات',
      body: 'اگر مستندات خودروی دیگری لازم دارید، از این فرم درخواست بدهید تا کارشناسان ما تماس بگیرند.',
    },
    {
      sel: '[data-tour="nav-settings"]',
      title: 'تنظیمات',
      body: 'حالت روشن/تاریک، اعلان‌ها و راه‌اندازی مجدد همین راهنما از بخش تنظیمات در دسترس است.',
    },
  ],
};

function stepsFor(pathname) {
  if (pathname === '/') return STEPS['/'];
  if (pathname.startsWith('/browse')) return STEPS['/browse'];
  return null;
}

export default function SiteTour() {
  const pathname = usePathname() || '/';
  const [idx, setIdx] = useState(-1);          // -1 => tour off
  const [rect, setRect] = useState(null);
  const [tipPos, setTipPos] = useState(null);
  const tipRef = useRef(null);
  const steps = stepsFor(pathname);
  const active = idx >= 0 && steps && idx < steps.length;

  const measure = useCallback(() => {
    if (!steps || idx < 0 || idx >= steps.length) return;
    const el = document.querySelector(steps[idx].sel);
    if (!el) { setRect(null); return; }
    const r = el.getBoundingClientRect();
    const pad = 8;
    const ring = {
      top: r.top - pad, left: r.left - pad,
      width: r.width + pad * 2, height: r.height + pad * 2,
    };
    setRect(ring);
    // Tip below the target if there's room, else above; clamped to viewport.
    const tipH = tipRef.current?.offsetHeight || 190;
    const tipW = Math.min(330, window.innerWidth - 32);
    const below = ring.top + ring.height + 14;
    const top = below + tipH < window.innerHeight - 12 ? below : Math.max(12, ring.top - tipH - 14);
    let left = ring.left + ring.width / 2 - tipW / 2;
    left = Math.max(16, Math.min(left, window.innerWidth - tipW - 16));
    setTipPos({ top, left });
  }, [steps, idx]);

  // Scroll the target into view, then measure (after the smooth scroll settles).
  useEffect(() => {
    if (!active) return;
    const el = document.querySelector(steps[idx].sel);
    if (el) el.scrollIntoView({ block: 'center', behavior: 'smooth' });
    const t1 = setTimeout(measure, 80);
    const t2 = setTimeout(measure, 420);
    const onWin = () => measure();
    window.addEventListener('resize', onWin);
    window.addEventListener('scroll', onWin, true);
    return () => {
      clearTimeout(t1); clearTimeout(t2);
      window.removeEventListener('resize', onWin);
      window.removeEventListener('scroll', onWin, true);
    };
  }, [active, idx, steps, measure]);

  // Auto-start once for brand-new visitors, on the landing page only.
  useEffect(() => {
    let done = '1';
    try { done = localStorage.getItem('kg-tour-done') || ''; } catch { /* ignore */ }
    if (!done && pathname === '/') {
      const t = setTimeout(() => setIdx(0), 1400);
      return () => clearTimeout(t);
    }
  }, [pathname]);

  // Manual (re)start: settings page / help button dispatch kg:tour.
  useEffect(() => {
    const onStart = () => setIdx(0);
    window.addEventListener('kg:tour', onStart);
    return () => window.removeEventListener('kg:tour', onStart);
  }, []);

  function finish() {
    setIdx(-1);
    try { localStorage.setItem('kg-tour-done', '1'); } catch { /* ignore */ }
  }
  const next = () => (idx + 1 < steps.length ? setIdx(idx + 1) : finish());
  const prev = () => idx > 0 && setIdx(idx - 1);

  if (!steps) return null;

  return (
    <>
      {!active && (
        <button
          className="tour-help-btn"
          title="راهنمای سایت"
          aria-label="شروع راهنمای سایت"
          onClick={() => setIdx(0)}
        >
          ؟
        </button>
      )}
      {active && rect && (
        <div className="tour-layer">
          <div
            className="tour-ring"
            style={{ top: rect.top, left: rect.left, width: rect.width, height: rect.height }}
          />
          <div className="tour-tip" ref={tipRef} style={tipPos ? { top: tipPos.top, left: tipPos.left } : { opacity: 0 }}>
            <div className="tt-step">{idx + 1} / {steps.length}</div>
            <h5>{steps[idx].title}</h5>
            <p>{steps[idx].body}</p>
            <div className="tour-nav">
              {idx > 0 && <button className="btn" onClick={prev}>قبلی</button>}
              <button className="btn btn-accent" onClick={next}>
                {idx + 1 === steps.length ? 'پایان' : 'بعدی'}
              </button>
              <button className="tour-skip" onClick={finish}>رد کردن راهنما</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
