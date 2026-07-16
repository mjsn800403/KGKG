// app/layout.js
import './globals.css';
import BackgroundFX from '@/components/BackgroundFX';
import Modal from '@/components/Modal';
import Guidance from '@/guidance';

export const metadata = {
  title: 'KGtechvault | پلتفرم مستندات فنی خودرو',
  description: 'سامانه یکپارچه مستندات فنی خودرو',
};

// Runs before first paint so the stored theme applies immediately — without it
// the SSR default flashes in and the user's saved choice "resets" on reload.
const THEME_BOOT = `try{var t=localStorage.getItem('kg-theme');if(t!=='light'&&t!=='dark')t='dark';document.documentElement.setAttribute('data-theme',t);}catch(e){document.documentElement.setAttribute('data-theme','dark');}`;

// Per-screen chrome (landing topnav, login backlink, dashboard sidebar) lives
// in each route, exactly like the prototype. The layout only mounts the global
// signature: fonts, ambient background, the microbar ticker and the modal.
// Fonts are self-hosted (see globals.css @font-face) — no CDN dependency.
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fa" dir="rtl" data-theme="dark" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT }} />
      </head>
      <body>
        <BackgroundFX />
        <div className="microbar">
          <div className="track">
            <span>EVERY VEHICLE. EVERY SPEC. ONE PLATFORM.</span>
            <span>سامانه یکپارچه مستندات فنی خودرو</span>
            <span>EVERY VEHICLE. EVERY SPEC. ONE PLATFORM.</span>
            <span>سامانه یکپارچه مستندات فنی خودرو</span>
            <span>EVERY VEHICLE. EVERY SPEC. ONE PLATFORM.</span>
            <span>سامانه یکپارچه مستندات فنی خودرو</span>
          </div>
        </div>
        {children}
        <Modal />
        <Guidance />
      </body>
    </html>
  );
}
