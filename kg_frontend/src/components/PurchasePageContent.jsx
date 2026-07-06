'use client';

import { useState } from 'react';
import Link from 'next/link';
import Icon from '@/components/Icon';
import PurchaseForm from '@/components/PurchaseForm';
import { PACKAGES } from '@/lib/packages';

const FAQ = [
  {
    q: 'چه کسانی می‌توانند خرید کنند؟',
    a: 'مستندات فنی فقط به اشخاص حقوقی (شرکت‌ها و سازمان‌ها) عرضه می‌شود. پس از ثبت درخواست، کارشناسان ما با شما تماس می‌گیرند.',
  },
  {
    q: 'آیا می‌توانم فقط یک پکیج بخرم؟',
    a: 'بله. می‌توانید هر یک از پکیج‌ها را جداگانه یا ترکیبی از چند پکیج سفارش دهید. دسترسی کامل به همه پکیج‌ها نیز امکان‌پذیر است.',
  },
  {
    q: 'نسخه دمو چیست؟',
    a: 'نسخه دمو دسترسی محدود و آزمایشی برای ارزیابی سامانه قبل از خرید نهایی است. در فرم سفارش می‌توانید درخواست دمو را علامت بزنید.',
  },
  {
    q: 'دستیار هوش مصنوعی برای همه فعال است؟',
    a: 'خیر. دستیار AI فقط برای کاربرانی فعال می‌شود که پکیج راهنمای تعمیرات (یا ترکیبی شامل آن) را داشته باشند.',
  },
  {
    q: 'پس از ثبت سفارش چه می‌شود؟',
    a: 'درخواست شما در سامانه ثبت می‌شود. تیم فروش ظرف ۱ تا ۲ روز کاری با شما تماس می‌گیرد، پکیج‌ها را نهایی می‌کند و پس از تأیید، حساب کاربری صادر می‌شود.',
  },
];

const TOUR_STEPS = [
  { n: '01', title: 'پکیج را انتخاب کنید', text: 'یک یا چند پکیج مستندات (راهنما، قطعات، زمان استاندارد، ابزار) را بر اساس نیاز تعمیرگاه انتخاب کنید.' },
  { n: '02', title: 'خودرو و سازمان را مشخص کنید', text: 'برند، مدل، سال خودرو و اطلاعات حقوقی شرکت — به‌همراه تعداد پرسنل و صندلی‌های مورد نیاز — را وارد کنید.' },
  { n: '03', title: 'درخواست را ثبت کنید', text: 'پس از ثبت، کارشناسان ما با شما تماس می‌گیرند. پس از تأیید، ادمین دسترسی و کاربران را صادر می‌کند.' },
];

export default function PurchasePageContent({ cars }) {
  const [openFaq, setOpenFaq] = useState(-1);
  const [tourStep, setTourStep] = useState(0);

  return (
    <>
      <nav className="purchase-topnav">
        <Link href="/" className="purchase-back">→ بازگشت به صفحه اصلی</Link>
        <div className="userchip"><div className="avatar">KG</div> KGTECHVAULT Company</div>
      </nav>

      <header className="purchase-hero glass">
        <div className="page-sub">// SUBSCRIPTION_PACKAGES</div>
        <h1 className="page-title">سفارش و خرید مستندات فنی</h1>
        <p className="purchase-lead">
          پکیج‌های اشتراکی ماژولار — از راهنمای تعمیرات تا کاتالوگ قطعات — با امکان ترکیب
          دلخواه یا دسترسی کامل. قیمت‌گذاری پس از بررسی نیاز سازمان شما اعلام می‌شود.
        </p>
      </header>

      <section className="purchase-section">
        <div className="section-head">
          <h2>پکیج‌های اشتراک</h2>
          <div className="tag">// PACKAGE_CATALOG</div>
        </div>
        <div className="grid4 purchase-packages">
          {PACKAGES.map((p) => (
            <div key={p.id} className="card glass purchase-pkg">
              <div className="num"><Icon name={p.icon} />{p.labelEn.split(' ')[0]}</div>
              <h3>{p.label}</h3>
              <p>{p.description}</p>
              <span className="purchase-price-tag">{p.priceNote} — تماس برای قیمت</span>
            </div>
          ))}
        </div>
      </section>

      <section className="purchase-section">
        <div className="section-head">
          <h2>مقایسه پکیج‌ها</h2>
          <div className="tag">// PACKAGE_COMPARISON</div>
        </div>
        <div className="card glass purchase-compare-wrap">
          <table className="adm-table purchase-compare">
            <thead>
              <tr>
                <th>قابلیت</th>
                {PACKAGES.filter((p) => p.id !== 'full_spec').map((p) => (
                  <th key={p.id}>{p.label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>مستندات فنی خودرو</td>
                {PACKAGES.filter((p) => p.id !== 'full_spec').map((p) => (
                  <td key={p.id}>✓</td>
                ))}
              </tr>
              <tr>
                <td>دستیار AI (نیازمند راهنمای تعمیرات)</td>
                {PACKAGES.filter((p) => p.id !== 'full_spec').map((p) => (
                  <td key={p.id}>{p.id === 'manual' ? '✓' : '—'}</td>
                ))}
              </tr>
              <tr>
                <td>قیمت‌گذاری</td>
                {PACKAGES.filter((p) => p.id !== 'full_spec').map((p) => (
                  <td key={p.id}>تماس</td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section className="purchase-section">
        <div className="section-head">
          <h2>راهنمای انتخاب و ثبت سفارش</h2>
          <div className="tag">// ONBOARDING_TOUR</div>
        </div>
        <div className="purchase-tour glass">
          <div className="purchase-tour-step">
            <span className="num">{TOUR_STEPS[tourStep].n}</span>
            <div>
              <h3>{TOUR_STEPS[tourStep].title}</h3>
              <p>{TOUR_STEPS[tourStep].text}</p>
            </div>
          </div>
          <div className="purchase-tour-nav">
            {TOUR_STEPS.map((_, i) => (
              <button
                key={i}
                type="button"
                className={`btn${i === tourStep ? ' btn-accent' : ''}`}
                onClick={() => setTourStep(i)}
              >
                {i + 1}
              </button>
            ))}
          </div>
        </div>
      </section>

      <section className="purchase-section" id="order-form">
        <div className="section-head">
          <h2>فرم ثبت درخواست</h2>
          <div className="tag">// ORDER_FORM</div>
        </div>
        <PurchaseForm cars={cars} />
      </section>

      <section className="purchase-section">
        <div className="section-head">
          <h2>سوالات متداول</h2>
          <div className="tag">// FAQ</div>
        </div>
        <div className="purchase-faq">
          {FAQ.map((item, i) => (
            <div key={i} className={`card glass purchase-faq-item${openFaq === i ? ' open' : ''}`}>
              <button type="button" className="purchase-faq-q" onClick={() => setOpenFaq(openFaq === i ? -1 : i)}>
                <Icon name="info" size={16} /> {item.q}
              </button>
              {openFaq === i && <p className="purchase-faq-a">{item.a}</p>}
            </div>
          ))}
        </div>
      </section>
    </>
  );
}
