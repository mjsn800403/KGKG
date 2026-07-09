'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import ThemeToggle from '@/components/ThemeToggle';
import Icon from '@/components/Icon';
import { showModal } from '@/components/Modal';

export default function Home() {
  const rigRef = useRef<HTMLDivElement>(null);
  const [menuOpen, setMenuOpen] = useState(false);

  // Hero "rig" parallax — follows the cursor exactly as in the prototype.
  useEffect(() => {
    function onMove(e: MouseEvent) {
      const rig = rigRef.current;
      if (!rig) return;
      const dx = (e.clientX / window.innerWidth - 0.5) * 18;
      const dy = (e.clientY / window.innerHeight - 0.5) * 12;
      rig.style.transform = `translate(calc(-50% + ${dx}px), calc(-46% + ${dy}px))`;
    }
    document.addEventListener('mousemove', onMove);
    return () => document.removeEventListener('mousemove', onMove);
  }, []);

  function checkVin() {
    const input = document.getElementById('vinInput') as HTMLInputElement | null;
    const v = (input?.value || '').trim();
    if (!v) {
      showModal('شماره شاسی الزامی است', 'لطفاً شماره شاسی (VIN) خودرو را وارد کنید تا بررسی پوشش انجام شود.', '!');
      return;
    }
    showModal('در حال بررسی پوشش', ' VIN: ' + v + ' — در نسخه نهایی، نتیجه به همراه فهرست مستندات موجود برای این خودرو نمایش داده می‌شود.', 'VIN');
  }

  return (
    <div className="screen fade" id="landing">
      <nav className={`topnav${menuOpen ? ' menu-open' : ''}`}>
        <Link className="brand" href="/">
          <img src="/logo.png" alt="KGtechvault" />
          <div className="name">KG<span>techvault</span></div>
        </Link>
        <div className="navlinks" onClick={() => setMenuOpen(false)}>
          <a href="#about">درباره ما</a>
          <a href="#coverage">پوشش خودرو</a>
          <a href="#how">روند کار</a>
          <Link href="/purchase">سفارش / خرید</Link>
        </div>
        <div className="nav-right">
          <ThemeToggle />
          <Link className="btn btn-accent nav-login" href="/login" data-tour="login-btn" aria-label="ورود به حساب کاربری">
            <span className="nav-login-text">ورود به حساب کاربری</span>
            <svg className="nav-login-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4" /><path d="M10 17l-5-5 5-5" /><path d="M5 12h12" /></svg>
          </Link>
          <button
            className="nav-burger"
            aria-label={menuOpen ? 'بستن منو' : 'باز کردن منو'}
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen(o => !o)}
          >
            {menuOpen ? (
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M6 6l12 12M18 6L6 18" /></svg>
            ) : (
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M4 7h16M4 12h16M4 17h16" /></svg>
            )}
          </button>
        </div>
      </nav>

      <div className="hero">
        <div className="rig" id="rig" ref={rigRef}>
          <svg viewBox="0 0 900 320" fill="none" xmlns="http://www.w3.org/2000/svg">
            <defs>
              <linearGradient id="rigGrad" x1="0" y1="0" x2="1" y2="0">
                <stop offset="0%" stopColor="var(--gold)" />
                <stop offset="55%" stopColor="var(--accent)" />
                <stop offset="100%" stopColor="var(--accent-2)" />
              </linearGradient>
            </defs>
            <path d="M60 220 L70 218 Q95 165 145 150 L210 132 Q260 110 330 108 L520 108 Q580 108 610 132 L660 152 Q700 165 740 195 L820 200 L840 218 L60 220 Z"
              stroke="url(#rigGrad)" strokeWidth="1.6" strokeLinejoin="round" />
            <path d="M225 150 Q280 118 345 116 L500 116 Q545 116 575 140" stroke="currentColor" strokeWidth="1" opacity=".55" />
            <line x1="395" y1="118" x2="395" y2="150" stroke="currentColor" strokeWidth="1" opacity=".4" />
            <circle cx="225" cy="222" r="38" stroke="url(#rigGrad)" strokeWidth="1.6" />
            <circle cx="225" cy="222" r="14" stroke="currentColor" strokeWidth="1" opacity=".5" />
            <circle cx="660" cy="222" r="38" stroke="url(#rigGrad)" strokeWidth="1.6" />
            <circle cx="660" cy="222" r="14" stroke="currentColor" strokeWidth="1" opacity=".5" />
            <line x1="60" y1="258" x2="840" y2="258" stroke="currentColor" strokeWidth="1" strokeDasharray="3 6" opacity=".4" />
            <line x1="60" y1="246" x2="60" y2="262" stroke="currentColor" strokeWidth="1" opacity=".4" />
            <line x1="840" y1="246" x2="840" y2="262" stroke="currentColor" strokeWidth="1" opacity=".4" />
            <text x="60" y="278" fill="currentColor" fontFamily="'IBM Plex Mono',monospace" fontSize="11" opacity=".55">L 4885 MM</text>
            <text x="745" y="278" fill="currentColor" fontFamily="'IBM Plex Mono',monospace" fontSize="11" opacity=".55">W 1730 MM</text>
            <circle cx="430" cy="108" r="3" fill="var(--accent)" />
            <line x1="430" y1="108" x2="430" y2="80" stroke="var(--accent)" strokeWidth="1" opacity=".5" />
            <text x="438" y="84" fill="var(--accent)" fontFamily="'IBM Plex Mono',monospace" fontSize="10" opacity=".8">ECU-REF-02</text>
          </svg>
        </div>
        <div className="eyebrow">سامانه مستندات فنی خودرو</div>
        <h1>دقتِ کارخانه،<br />در دستِ <em>تعمیرگاه</em>.</h1>
        <p>دسترسی مستقیم به منوال تعمیر، فهرست قطعات، زمان‌های استاندارد و ابزار مخصوص تعمیراتی — دقیقاً برای مدل، سال و آپشن خودروی شما. بدون تخمین، بدون حدس.</p>
        <div className="hero-actions">
          <Link className="btn btn-accent" href="/login">ورود به پورتال ←</Link>
          <a className="btn" href="#coverage">مشاهده پوشش خودروها</a>
        </div>
        <div className="vin-decode">VIN// در حال تجزیه شناسه خودرو<span className="cursor"></span></div>
        <div className="coord"><span><b>SYS</b> KGTV-02</span></div>
      </div>

      <section id="about">
        <div className="section-head">
          <h2>چهار لایه مستند، یک منبع واحد</h2>
          <div className="tag">// 01 — COVERAGE LAYERS</div>
        </div>
        <div className="grid4" data-tour="doc-layers">
          <div className="card glass"><div className="num"><Icon name="parts" />PT · 01</div><h3>فهرست قطعات</h3><p>کدهای فنی، شماره‌فنی اورجینال و دیاگرام انفجاری برای هر مجموعه، مطابق دقیق با سال ساخت و آپشن.</p></div>
          <div className="card glass"><div className="num"><Icon name="manual" />RM · 02</div><h3>منوال تعمیر</h3><p>رویه گام‌به‌گام کارخانه‌ای، گشتاورها، تلورانس‌ها و هشدارهای ایمنی — قابل اتصال به عکس ۳۶۰ درجه.</p></div>
          <div className="card glass"><div className="num"><Icon name="clock" />ST · 03</div><h3>زمان استاندارد</h3><p>زمان مرجع هر عملیات برای برآورد دقیق هزینه و زمان‌بندی تعمیرگاه، بر اساس داده کارخانه‌ای.</p></div>
          <div className="card glass"><div className="num"><Icon name="wrench" />SE · 04</div><h3>ابزار مخصوص تعمیراتی</h3><p>فهرست ابزارهای ویژه کارخانه‌ای لازم برای هر عملیات، با کد فنی و نحوه استفاده صحیح.</p></div>
        </div>

        <div style={{ marginTop: 60, color: 'var(--text-dim)', fontSize: '14.5px', lineHeight: 2, maxWidth: 760 }}>
          کلیه محتوای این سایت از دیتابیس‌های مرجع (مادر) تامین شده و صحت و درستی اطلاعات به دیتابیس مادر بستگی دارد. کلیه فرآیند استخراج، گردآوری، طراحی و تدوین این پلتفرم توسط واحد سیستم و روش شرکت خدمات گستر سپهر گیتی انجام شده است.
        </div>
      </section>

      <section id="coverage">
        <div className="section-head">
          <h2>بررسی پوشش خودرو با شماره شاسی</h2>
          <div className="tag">// 02 — VIN LOOKUP</div>
        </div>
        <p style={{ color: 'var(--text-dim)', maxWidth: 600, lineHeight: 1.9, fontSize: '14.5px' }}>شماره شاسی (VIN) خودرو را وارد کنید تا میزان پوشش مستندات فنی موجود برای آن مشخص شود.</p>
        <div className="vin-box glass" data-tour="vin-box">
          <input type="text" placeholder="مثلاً: JTHBE1GG0E5012345" id="vinInput" />
          <button className="btn btn-accent" onClick={checkVin}>بررسی پوشش</button>
        </div>
        <div className="not-found-note glass">
          <span>خودروی مورد نظر شما در فهرست نیست؟</span>
          <a href="#">با پشتیبانی برای گردآوری و تهیه دیتای آن در ارتباط باشید ←</a>
        </div>
      </section>

      <section id="how">
        <div className="section-head">
          <h2>روند ورود به اطلاعات خودرو</h2>
          <div className="tag">// 03 — ACCESS FLOW</div>
        </div>
        <div className="grid3">
          <div className="card glass"><div className="num">01</div><h3>انتخاب خودرو</h3><p>برند، مدل، سال و آپشن را از منوهای کشویی انتخاب می‌کنید.</p></div>
          <div className="card glass"><div className="num">02</div><h3>تطبیق خرید</h3><p>سامانه فقط مستنداتی را نشان می‌دهد که برای آن مدل خریداری شده است.</p></div>
          <div className="card glass"><div className="num">03</div><h3>مشاهده مستند</h3><p>ورود به منوال، قطعات، زمان استاندارد یا ابزار تعمیراتی، با امکان اتصال به عکس ۳۶۰.</p></div>
        </div>
      </section>

      <div className="cta-strip glass">
        <h3>دسترسی شما به مستندات فنی، آماده ورود است.</h3>
        <Link className="btn btn-accent" href="/login">ورود به پورتال ←</Link>
      </div>

      <footer>
        <div className="support-strip" data-tour="support">
          <div className="sblock">
            <h4><Icon name="phone" />پشتیبانی فنی</h4>
            <p>برای مشکلات دسترسی، خرید مستندات یا گزارش خرابی در سامانه با ما در ارتباط باشید.</p>
            <div className="contact-row">
              <Icon name="phone" />
              <a href="tel:+982192001404"><span className="ltr">021-92001404</span></a>
              <span style={{ color: 'var(--text-dim)' }}>داخلی ۱۷۲</span>
            </div>
            <div className="contact-row">
              <Icon name="mail" />
              <a href="mailto:mj.salimi@khadamatgostar.com"><span className="ltr">mj.salimi@khadamatgostar.com</span></a>
            </div>
          </div>
          <div className="sblock">
            <h4><Icon name="info" />درباره ما</h4>
            <p>کلیه محتوای سایت از دیتابیس‌های مرجع (مادر) تامین شده و صحت اطلاعات به دیتابیس مادر بستگی دارد. گردآوری، طراحی و تدوین: واحد سیستم و روش شرکت خدمات گستر سپهر گیتی.</p>
          </div>
          <div className="sblock">
            <h4><Icon name="arrow" />دسترسی سریع</h4>
            <p>
              <a style={{ display: 'block', marginBottom: 6 }} href="#coverage">بررسی پوشش خودرو</a>
              <Link style={{ display: 'block', marginBottom: 6 }} href="/purchase" className="quick-link">درخواست خرید مستندات</Link>
              <a style={{ display: 'block' }} href="#">شرایط استفاده</a>
            </p>
          </div>
        </div>
        <div className="foot-bottom">
          <span>© KGtechvault — سامانه مستندات فنی خودرو شرکت خدمات گستر سپهر گیتی</span>
          <span className="credit">طراحی و تدوین: محمد جواد سلیمی <span className="heart">♥</span> برای شرکت خدمات گستر سپهر گیتی</span>
        </div>
      </footer>
    </div>
  );
}
