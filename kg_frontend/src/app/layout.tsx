// app/layout.js
import './globals.css';
import BackgroundFX from '@/components/BackgroundFX';
import Modal from '@/components/Modal';

export const metadata = {
  title: 'KGtechvault | پلتفرم مستندات فنی خودرو',
  description: 'سامانه یکپارچه مستندات فنی خودرو',
};

// Per-screen chrome (landing topnav, login backlink, dashboard sidebar) lives
// in each route, exactly like the prototype. The layout only mounts the global
// signature: fonts, ambient background, the microbar ticker and the modal.
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fa" dir="rtl" data-theme="dark">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&family=Vazirmatn:wght@300;400;500;600;700;800;900&display=swap"
          rel="stylesheet"
        />
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
      </body>
    </html>
  );
}
