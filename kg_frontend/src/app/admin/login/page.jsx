'use client';

// Dedicated platform-admin sign-in — mirrors the portal /login URL structure.
// A successful login lands on the admin hub (/admin), which never renders
// for unauthenticated visitors.

import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { AnimatePresence, motion, MotionConfig } from 'motion/react';
import Icon from '@/components/Icon';
import { adminLogin, adminVerifyOtp, obtainAdminToken } from '@/utils/api';

const EASE = [0.22, 1, 0.36, 1];
const TURNSTILE_SITEKEY = '0x4AAAAAAEjnbFG2W2QYf-cE';

export default function AdminLogin() {
  const router = useRouter();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [entered, setEntered] = useState(false);
  const [token, setToken] = useState('');
  const [otp, setOtp] = useState(null); // {session, hint} after the password step
  const [code, setCode] = useState('');
  const boxRef = useRef(null);
  const widgetId = useRef(null);

  useEffect(() => {
    obtainAdminToken().then((t) => { if (t) router.replace('/admin'); });
  }, [router]);

  const renderWidget = useCallback(() => {
    if (!boxRef.current || widgetId.current || !window.turnstile) return;
    widgetId.current = window.turnstile.render(boxRef.current, {
      sitekey: TURNSTILE_SITEKEY,
      action: 'login',
      callback: (t) => setToken(t),
      'expired-callback': () => setToken(''),
      'error-callback': () => setToken(''),
      theme: document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark',
      language: 'fa',
    });
  }, []);

  useEffect(() => {
    if (!document.querySelector('script[data-cf-turnstile]')) {
      const s = document.createElement('script');
      s.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
      s.async = true; s.defer = true;
      s.setAttribute('data-cf-turnstile', '1');
      document.head.appendChild(s);
    }
    const iv = setInterval(() => { if (window.turnstile) { renderWidget(); clearInterval(iv); } }, 300);
    return () => {
      clearInterval(iv);
      try {
        if (widgetId.current && boxRef.current?.isConnected) window.turnstile?.remove(widgetId.current);
      } catch { /* noop */ }
      widgetId.current = null;
    };
  }, [renderWidget]);

  async function submit(e) {
    e?.preventDefault();
    if (busy) return;
    setError('');
    if (otp) {
      if (!/^\d{6}$/.test(code.trim())) { setError('کد ۶ رقمی پیامک‌شده را وارد کنید.'); return; }
      setBusy(true);
      try {
        await adminVerifyOtp(otp.session, code.trim());
        setEntered(true);
        setTimeout(() => router.replace('/admin'), 650);
      } catch (err) {
        setError(err?.message || 'تأیید کد ناموفق بود.');
        setBusy(false);
      }
      return;
    }
    if (!username.trim() || !password) {
      setError('نام کاربری و رمز عبور مدیر سامانه را وارد کنید.');
      return;
    }
    if (!token) {
      setError('لطفاً تأیید کنید که ربات نیستید.');
      return;
    }
    setBusy(true);
    try {
      const d = await adminLogin(username.trim(), password, token);
      if (d?.otp_required) {
        setOtp({ session: d.otp_session, hint: d.phone_hint });
        setBusy(false);
        return;
      }
      setEntered(true);
      setTimeout(() => router.replace('/admin'), 650);
    } catch (err) {
      setError(err?.message || 'ورود ناموفق بود.');
      setBusy(false);
      setToken('');
      try { window.turnstile?.reset(widgetId.current || undefined); } catch { /* noop */ }
    }
  }

  return (
    <MotionConfig reducedMotion="user">
      <div className="screen fade login-screen" id="admin-login">
        <div className="auth-wrap">
          <a className="backlink" href="/">→ بازگشت به سایت</a>
          <motion.div
            initial={{ opacity: 0, y: 22, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            transition={{ duration: 0.55, ease: EASE }}
          >
            <div className="auth-card glass admin-auth-card">
              <AnimatePresence mode="wait">
                {entered ? (
                  <motion.div
                    key="ok"
                    className="admin-auth-ok"
                    initial={{ opacity: 0, scale: 0.9 }}
                    animate={{ opacity: 1, scale: 1 }}
                    transition={{ type: 'spring', stiffness: 280, damping: 20 }}
                  >
                    <motion.svg viewBox="0 0 52 52" width="64" height="64">
                      <motion.circle cx="26" cy="26" r="24" fill="none" stroke="var(--accent)" strokeWidth="2"
                        initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.45 }} />
                      <motion.path d="M16 27l7 7 14-15" fill="none" stroke="var(--accent)" strokeWidth="3"
                        strokeLinecap="round" strokeLinejoin="round"
                        initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.35, delay: 0.3 }} />
                    </motion.svg>
                    <h2>خوش آمدید</h2>
                    <p>در حال انتقال به میز مدیریت…</p>
                  </motion.div>
                ) : (
                  <motion.form key="form" onSubmit={submit}
                    initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0, y: -10 }}>
                    <div className="auth-head">
                      <img src="/brand/logo-mark.png" alt="KGtechvault" />
                      <h2>ورود مدیر سامانه</h2>
                      <p>ورود مدیر سامانه · دسترسی محدود</p>
                    </div>
                    <div className="admin-auth-band">
                      <Icon name="shield" size={15} />
                      <span>این بخش مخصوص مدیر پلتفرم است؛ کاربران شرکتی از <a onClick={() => router.push('/login')}>صفحه ورود پورتال</a> وارد شوند.</span>
                    </div>
                    {otp && (
                      <div className="field"><label>
                        کد تأیید ارسال‌شده به <bdi dir="ltr" style={{ unicodeBidi: 'isolate' }}>{otp.hint}</bdi>
                      </label>
                        <input dir="ltr" inputMode="numeric" autoComplete="one-time-code" maxLength={6}
                          value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))} autoFocus />
                        <a style={{ fontSize: 12, cursor: 'pointer' }}
                          onClick={() => { setOtp(null); setCode(''); setToken('');
                            try { window.turnstile?.reset(widgetId.current || undefined); } catch { /* noop */ } }}>
                          ← بازگشت و ارسال دوباره
                        </a>
                      </div>
                    )}
                    <div style={otp ? { display: 'none' } : undefined}>
                    <div className="field"><label>نام کاربری</label>
                      <input dir="ltr" type="text" autoComplete="username" value={username}
                        onChange={(e) => setUsername(e.target.value)} placeholder="admin" />
                    </div>
                    <div className="field"><label>رمز عبور</label>
                      <input dir="ltr" type="password" autoComplete="current-password" placeholder="••••••••••" value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && submit(e)} />
                    </div>
                    <div ref={boxRef} style={{ margin: '4px 0 12px', minHeight: 65 }} />
                    </div>
                    <AnimatePresence>
                      {error && (
                        <motion.div className="pform-error" style={{ marginBottom: 12 }}
                          initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }}>
                          {error}
                        </motion.div>
                      )}
                    </AnimatePresence>
                    <motion.button className="btn btn-accent full" type="submit" disabled={busy}
                      whileTap={{ scale: 0.97 }}>
                      {busy ? 'در حال بررسی…' : otp ? 'تأیید کد و ورود ←' : 'ورود به میز مدیریت ←'}
                    </motion.button>
                  </motion.form>
                )}
              </AnimatePresence>
            </div>
          </motion.div>
        </div>
      </div>
    </MotionConfig>
  );
}
