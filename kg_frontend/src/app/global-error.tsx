'use client';

// Last-resort boundary: it replaces the root layout, so no stylesheet is
// loaded here and the markup carries its own minimal styling. Anything
// recoverable is handled by app/error.tsx instead.
export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <html lang="fa" dir="rtl">
      <body style={{ margin: 0, minHeight: '100vh', display: 'grid', placeItems: 'center', background: '#0e1013', color: '#ecedee', fontFamily: "'Vazirmatn', system-ui, sans-serif" }}>
        <div style={{ textAlign: 'center', padding: '24px', maxWidth: '460px' }}>
          <div style={{ fontSize: '40px', fontWeight: 800, marginBottom: '12px' }}>۵۰۰</div>
          <h1 style={{ fontSize: '20px', fontWeight: 700, margin: '0 0 10px' }}>سامانه در دسترس نیست</h1>
          <p style={{ fontSize: '14px', lineHeight: 2, color: '#b4b9c0', margin: '0 0 20px' }}>
            بارگذاری صفحه ناموفق بود. لطفاً دوباره تلاش کنید؛ اگر تکرار شد با پشتیبانی تماس بگیرید.
          </p>
          <button
            type="button" onClick={reset}
            style={{ padding: '10px 22px', borderRadius: '8px', border: 0, background: '#d0262d', color: '#fff', fontSize: '15px', fontFamily: 'inherit', cursor: 'pointer' }}
          >
            تلاش دوباره
          </button>
          {error?.digest && <p style={{ fontSize: '12px', color: '#8c929b', marginTop: '16px' }}>کد پیگیری: {error.digest}</p>}
        </div>
      </body>
    </html>
  );
}
