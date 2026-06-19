// app/layout.js
import './globals.css';
import Link from 'next/link';
import BackgroundFX from '@/components/BackgroundFX';
import ThemeToggle from '@/components/ThemeToggle';

export const metadata = {
  title: 'KGtechvault | Car Technical Documentation',
  description: 'Browse car repair manuals, parts catalogs and specs',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" dir="ltr" data-theme="dark">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700;800&family=IBM+Plex+Mono:wght@400;500;600&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>
        <BackgroundFX />
        <nav className="topnav">
          <Link href="/" className="brand">
            <span className="mark">KG</span>
            <span className="name">KG<span>techvault</span></span>
          </Link>
          <div className="nav-right">
            <ThemeToggle />
          </div>
        </nav>
        {children}
      </body>
    </html>
  );
}
