'use client';

// Chrome shared by the public pages (landing, plans): wordmark, header icon
// buttons and the footer. Styles live in landing.css (.lp-* namespace).
import { useSyncExternalStore } from 'react';
import Link from 'next/link';
import { applyTheme } from '@/components/ThemeToggle';
import Icon from '@/components/Icon';
import { fa } from './landing-data';

export const BRAND_LINE = 'پلتفرم هوشمند دانش و مستندات فنی خدمات گستر سپهر گیتی';
export const PLANS_HREF = '/purchase';

/** Latin run inside Persian copy — isolated so punctuation never flips sides. */
export function L({ children, mono = false, className = '' }: { children: React.ReactNode; mono?: boolean; className?: string }) {
  return <bdi dir="ltr" className={`${mono ? 'lp-code' : 'lp-latin'} ${className}`.trim()}>{children}</bdi>;
}

export function Wordmark() {
  return (
    <Link className="lp-brand" href="/" aria-label="KGTechVault — صفحهٔ اصلی">
      <img className="lp-brand-mark" src="/brand/logo-mark.png" alt="" width={48} height={37} />
      <bdi dir="ltr" className="lp-brand-name">KG<span>techvault</span></bdi>
    </Link>
  );
}

function subscribeTheme(cb: () => void) {
  window.addEventListener('kg:theme', cb);
  return () => window.removeEventListener('kg:theme', cb);
}
const readTheme = () => (document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark');

// Opens the global help panel through its own "?" shortcut, so the page can
// host the entry point in the header instead of a floating button.
export function HelpButton({ onOpen }: { onOpen?: () => void }) {
  return (
    <button
      type="button"
      className="lp-iconbtn"
      aria-label="راهنما"
      title="راهنما"
      onClick={() => { onOpen?.(); window.dispatchEvent(new KeyboardEvent('keydown', { key: '?' })); }}
    >
      <Icon name="question" />
    </button>
  );
}

export function ThemeButton() {
  const theme = useSyncExternalStore(subscribeTheme, readTheme, () => 'dark' as const);
  function toggle() {
    const root = document.documentElement;
    root.classList.add('lp-theming');
    applyTheme(theme === 'dark' ? 'light' : 'dark');
    window.setTimeout(() => root.classList.remove('lp-theming'), 320);
  }
  const next = theme === 'dark' ? 'روشن' : 'تاریک';
  return (
    <button type="button" className="lp-iconbtn" onClick={toggle} aria-label={`تغییر به حالت ${next}`} title={`حالت ${next}`}>
      <Icon name={theme === 'dark' ? 'sun' : 'moon'} />
    </button>
  );
}

export function LoginButton() {
  return (
    <Link className="lp-btn lp-btn-ghost lp-login" href="/login" data-tour="login-btn">
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4" /><path d="M10 17l-5-5 5-5" /><path d="M5 12h12" /></svg>
      <span>ورود</span>
    </Link>
  );
}

/** Site footer. `coverageHref` differs between the landing (#coverage) and other pages (/#coverage). */
export function Footer({ coverageHref = '/#coverage' }: { coverageHref?: string }) {
  return (
    <footer className="lp-footer">
      <div className="lp-wrap lp-footer-grid">
        <div className="lp-footer-about">
          <Wordmark />
          <h3>محتوا و داده</h3>
          <p>محتوای این پلتفرم از دیتابیس‌های فنی معتبر تأمین می‌شود تا اطلاعات فنی قابل‌اتکا و دقیق در اختیار کاربران قرار گیرد.</p>
          <p className="lp-footer-credit">
            <span>توسعه و گردآوری:</span>
            تیم تحقیق و توسعه، خدمات گستر سپهر گیتی
          </p>
        </div>
        <div data-tour="support">
          <h3>پشتیبانی فنی</h3>
          <p className="lp-footer-dim">برای مشکلات دسترسی، پرسش دربارهٔ خرید اشتراک یا مشکلات فنی پلتفرم، از طریق بخش درخواست‌های پورتال یا راه‌های زیر با ما در ارتباط باشید:</p>
          <ul className="lp-contact">
            <li>
              <Icon name="phone" />
              <span className="lp-footer-dim">تلفن:</span>
              <a href="tel:+982192001404"><bdi dir="ltr">+98 21 9200 1404</bdi></a>
            </li>
            <li>
              <span className="lp-contact-pad" aria-hidden="true" />
              <span className="lp-footer-dim">داخلی:</span>
              <span className="lp-contact-v">{fa(304)}</span>
            </li>
            <li>
              <Icon name="mail" />
              <span className="lp-footer-dim">ایمیل:</span>
              <a href="mailto:mj.salimi@khadamatgostar.com"><L>mj.salimi@khadamatgostar.com</L></a>
            </li>
          </ul>
        </div>
        <div>
          <h3>دسترسی سریع</h3>
          <ul className="lp-links">
            <li><a href={coverageHref}>پوشش خودروها</a></li>
            <li><Link href={PLANS_HREF}>پلن‌ها و خرید اشتراک</Link></li>
            <li><Link href="/login">ورود به پورتال</Link></li>
          </ul>
        </div>
      </div>
      <div className="lp-wrap">
        <div className="lp-footer-bottom">
          <span>© <L>KGTechVault</L> — {BRAND_LINE}</span>
        </div>
      </div>
    </footer>
  );
}
