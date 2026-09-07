'use client';

import Link from 'next/link';
import { useEffect } from 'react';

export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);

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
        <div style={{ fontSize: '4rem', fontWeight: 700, color: 'var(--accent, #e34e63)', fontFamily: "'IBM Plex Mono', monospace" }}>500</div>
        <div style={{ fontSize: '1.1rem', color: 'var(--text-dim, #9a98a5)' }}>خطایی رخ داد</div>
        <div style={{ fontSize: '0.9rem', color: 'var(--text-faint, #5f5d69)' }}>An unexpected error occurred</div>
        <div style={{ display: 'flex', gap: '0.75rem', marginTop: '0.5rem' }}>
          <button onClick={reset} style={{
            padding: '0.5rem 1.5rem',
            background: 'var(--accent, #e34e63)',
            color: '#fff',
            border: 'none',
            borderRadius: '6px',
            cursor: 'pointer',
            fontSize: '0.95rem',
          }}>تلاش مجدد</button>
          <Link href="/" style={{
            padding: '0.5rem 1.5rem',
            background: 'transparent',
            color: 'var(--text-dim, #9a98a5)',
            border: '1px solid var(--border, #32343f)',
            borderRadius: '6px',
            textDecoration: 'none',
            fontSize: '0.95rem',
          }}>بازگشت</Link>
        </div>
      </body>
    </html>
  );
}
