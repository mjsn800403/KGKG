'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { motion } from 'motion/react';
import { validateInvite, acceptInvite } from '@/utils/api';

// Employee invite acceptance: validate the token, let the employee choose a
// password, then auto-login into the portal.
export default function InviteAccept() {
  const router = useRouter();
  const params = useParams();
  const token = String(params?.token || '');

  const [state, setState] = useState('loading'); // loading | ready | invalid | done
  const [user, setUser] = useState(null);
  const [pw, setPw] = useState('');
  const [pw2, setPw2] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const u = await validateInvite(token);
        if (cancelled) return;
        setUser(u); setState('ready');
      } catch (e) {
        if (cancelled) return;
        setError(e?.message || 'لینک دعوت نامعتبر است.');
        setState('invalid');
      }
    })();
    return () => { cancelled = true; };
  }, [token]);

  async function submit() {
    setError('');
    if (pw.length < 8) return setError('رمز عبور باید حداقل ۸ نویسه باشد.');
    if (pw !== pw2) return setError('رمز عبور و تکرار آن یکسان نیستند.');
    setBusy(true);
    try {
      await acceptInvite(token, pw);
      setState('done');
      setTimeout(() => router.push('/browse'), 1400);
    } catch (e) {
      setError(e?.message || 'فعال‌سازی ناموفق بود.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="screen fade login-screen" id="invite">
      <div className="auth-wrap">
        <motion.div className="auth-card glass" initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}>
          <div className="auth-head">
            <img src="/logo.png" alt="KGtechvault" />
            <h2>فعال‌سازی حساب کاربری</h2>
            <p>ACCOUNT ACTIVATION</p>
          </div>

          {state === 'loading' && <div className="empty-state">در حال بررسی دعوت‌نامه…</div>}

          {state === 'invalid' && (
            <div className="pform-error" style={{ marginTop: 8 }}>
              {error}
              <div style={{ marginTop: 14 }}><a href="/login" className="quick-link">رفتن به صفحه ورود ←</a></div>
            </div>
          )}

          {state === 'ready' && user && (
            <>
              <p className="invite-welcome">
                {user.display_name} گرامی، به سامانه <b>{user.company}</b> خوش آمدید.
                برای فعال‌سازی حساب، رمز عبور خود را انتخاب کنید.
              </p>
              <div className="acct-row"><span className="k">نام کاربری</span><span className="v ltr">{user.email || user.username}</span></div>
              <div className="field" style={{ marginTop: 14 }}><label>رمز عبور جدید</label>
                <input type="password" dir="ltr" placeholder="حداقل ۸ نویسه" value={pw} onChange={(e) => setPw(e.target.value)} />
              </div>
              <div className="field"><label>تکرار رمز عبور</label>
                <input type="password" dir="ltr" value={pw2} onChange={(e) => setPw2(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && submit()} />
              </div>
              {error && <div className="pform-error" style={{ marginBottom: 12 }}>{error}</div>}
              <button className="btn btn-accent full" onClick={submit} disabled={busy}>
                {busy ? 'در حال فعال‌سازی…' : 'فعال‌سازی و ورود ←'}
              </button>
            </>
          )}

          {state === 'done' && (
            <motion.div className="empty-state" initial={{ scale: 0.9, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}>
              حساب شما فعال شد؛ در حال ورود به سامانه…
            </motion.div>
          )}
        </motion.div>
      </div>
    </div>
  );
}
