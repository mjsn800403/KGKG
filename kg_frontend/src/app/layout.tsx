// app/layout.js
import { headers } from 'next/headers';
import './globals.css';
import './system.css';
import BackgroundFX from '@/components/BackgroundFX';
import Modal from '@/components/Modal';
import Guidance from '@/guidance';
import Analytics from '@/components/Analytics';

export const metadata = {
  // Absolute base for the og:/twitter: image URLs Next derives from the
  // opengraph-image / twitter-image files in this directory.
  metadataBase: new URL('https://kgtechvault.com'),
  title: {
    default: 'KGTechVault | پلتفرم هوشمند دانش و مستندات فنی خودرو',
    template: '%s | KGTechVault',
  },
  description: 'پلتفرم هوشمند دانش و مستندات فنی خودرو — منوال تعمیر، نقشهٔ سیم‌کشی، زمان استاندارد و کاتالوگ قطعات، همراه با دستیار هوشمند فارسی. خدمات گستر سپهر گیتی.',
  applicationName: 'KGTechVault',
  openGraph: {
    type: 'website',
    siteName: 'KGTechVault',
    locale: 'fa_IR',
    url: 'https://kgtechvault.com',
    title: 'KGTechVault | پلتفرم هوشمند دانش و مستندات فنی خودرو',
    description: 'منوال تعمیر، نقشهٔ سیم‌کشی، زمان استاندارد و کاتالوگ قطعات، همراه با دستیار هوشمند فارسی.',
  },
  twitter: {
    card: 'summary_large_image',
    title: 'KGTechVault | پلتفرم هوشمند دانش و مستندات فنی خودرو',
    description: 'منوال تعمیر، نقشهٔ سیم‌کشی، زمان استاندارد و کاتالوگ قطعات، همراه با دستیار هوشمند فارسی.',
  },
};

// Runs before first paint so the stored theme applies immediately — without it
// the SSR default flashes in and the user's saved choice "resets" on reload.
const THEME_BOOT = `try{var t=localStorage.getItem('kg-theme');if(t!=='light'&&t!=='dark')t='dark';document.documentElement.setAttribute('data-theme',t);}catch(e){document.documentElement.setAttribute('data-theme','dark');}`;

// Per-screen chrome (landing topnav, login backlink, dashboard sidebar) lives
// in each route, exactly like the prototype. The layout only mounts the global
// signature: fonts, ambient background, the microbar ticker and the modal.
// Fonts are self-hosted (see globals.css @font-face) — no CDN dependency.
export default async function RootLayout({ children }: { children: React.ReactNode }) {
  // Set by src/proxy.ts; reading headers() also keeps every page dynamic,
  // which nonces require (a prerendered page would carry a stale nonce).
  const nonce = (await headers()).get('x-nonce') ?? undefined;
  return (
    <html lang="fa" dir="rtl" data-theme="dark" suppressHydrationWarning>
      <head>
        <script nonce={nonce} dangerouslySetInnerHTML={{ __html: THEME_BOOT }} />
        {/* Self-hosted Umami (see components/Analytics.jsx): page views are sent
            manually so URLs can be redacted before they leave the browser. */}
        <script defer nonce={nonce} src="/stats/kgs.js" data-website-id="86d05558-7aeb-4b11-8931-fdbd8b2f3eee"
                data-host-url="/stats" data-auto-track="false" data-exclude-search="true" />
      </head>
      <body>
        <Analytics />
        <BackgroundFX />
        <div className="microbar">
          <div className="track">
            <span>EVERY VEHICLE. EVERY SPEC. ONE PLATFORM.</span>
            <span>پلتفرم هوشمند دانش و مستندات فنی</span>
            <span>EVERY VEHICLE. EVERY SPEC. ONE PLATFORM.</span>
            <span>پلتفرم هوشمند دانش و مستندات فنی</span>
            <span>EVERY VEHICLE. EVERY SPEC. ONE PLATFORM.</span>
            <span>پلتفرم هوشمند دانش و مستندات فنی</span>
          </div>
        </div>
        {children}
        <Modal />
        <Guidance />
      </body>
    </html>
  );
}
