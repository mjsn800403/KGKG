'use client';

// Dedicated platform-admin sign-in — mirrors the portal /login URL structure.
// A successful login lands on the admin hub (/admin), which never renders
// for unauthenticated visitors.

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { AnimatePresence, motion, MotionConfig } from 'motion/react';
import Icon from '@/components/Icon';
import { adminLogin, getAdminToken } from '@/utils/api';

const EASE = [0.22, 1, 0.36, 1];

export default function AdminLogin() {
  const router = useRouter();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [entered, setEntered] = useState(false);

  useEffect(() => {
    if (getAdminToken()) router.replace('/admin');
  }, [router]);

  async function submit(e) {
    e?.preventDefault();
    if (busy) return;
    setError('');
    if (!username.trim() || !password) {
      setError('نام کاربری و رمز عبور مدیر سامانه را وارد کنید.');
      return;
    }
    setBusy(true);
    try {
      await adminLogin(username.trim(), password);
      setEntered(true);
      setTimeout(() => router.replace('/admin'), 650);
    } catch (err) {
      setError(err?.message || 'ورود ناموفق بود.');
      setBusy(false);
    }
  }

  return (
    <MotionConfig reducedMotion="user">
      <div className="screen fade login-screen" id="admin-login">
        <div className="auth-wrap">
          <span className="backlink" onClick={() => router.push('/')}>→ بازگشت به سایت</span>
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
                      <img src="/logo.png" alt="KGtechvault" />
                      <h2>ورود مدیر سامانه</h2>
                      <p>PLATFORM ADMIN // RESTRICTED</p>
                    </div>
                    <div className="admin-auth-band">
                      <Icon name="shield" size={15} />
                      <span>این بخش مخصوص مدیر پلتفرم است؛ کاربران شرکتی از <a onClick={() => router.push('/login')}>صفحه ورود پورتال</a> وارد شوند.</span>
                    </div>
                    <div className="field"><label>نام کاربری</label>
                      <input dir="ltr" type="text" autoComplete="username" value={username}
                        onChange={(e) => setUsername(e.target.value)} placeholder="admin" />
                    </div>
                    <div className="field"><label>رمز عبور</label>
                      <input dir="ltr" type="password" autoComplete="current-password" placeholder="••••••••••" value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && submit(e)} />
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
                      {busy ? 'در حال بررسی…' : 'ورود به میز مدیریت ←'}
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
