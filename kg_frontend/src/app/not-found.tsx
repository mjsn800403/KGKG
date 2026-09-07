import Link from 'next/link';

export default function NotFound() {
  return (
    <html lang="fa" dir="rtl">
      <body style={{
        margin: 0,
        background: 'var(--bg, #0b0c10)',
        color: 'var(--text, #e9e7e0)',
        fontFamily: "'Vazirmatn', 'Space Grotesk', sans-serif",
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: '100vh',
        flexDirection: 'column',
        gap: '1.5rem',
        textAlign: 'center',
      }}>
        <div style={{ fontSize: '4rem', fontWeight: 700, color: 'var(--accent, #e34e63)', fontFamily: "'IBM Plex Mono', monospace" }}>404</div>
        <div style={{ fontSize: '1.1rem', color: 'var(--text-dim, #9a98a5)' }}>صفحه مورد نظر یافت نشد</div>
        <div style={{ fontSize: '0.9rem', color: 'var(--text-faint, #5f5d69)' }}>Page not found</div>
        <Link href="/" style={{
          marginTop: '0.5rem',
          padding: '0.5rem 1.5rem',
          background: 'var(--accent, #e34e63)',
          color: '#fff',
          borderRadius: '6px',
          textDecoration: 'none',
          fontSize: '0.95rem',
        }}>بازگشت به صفحه اصلی</Link>
      </body>
    </html>
  );
}
