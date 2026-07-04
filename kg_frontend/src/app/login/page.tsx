'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { portalLogin } from '@/utils/api';

export default function Login() {
  const router = useRouter();
  const [step, setStep] = useState(1);
  const [captcha, setCaptcha] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  // Step 1 verifies real credentials against the backend; the captcha/OTP
  // steps stay as the confirmation UX but only run after a successful login.
  async function submitCredentials() {
    if (busy) return;
    setError('');
    if (!username.trim() || !password) {
      setError('نام کاربری و رمز عبور را وارد کنید.');
      return;
    }
    setBusy(true);
    try {
      await portalLogin(username.trim(), password);
      setStep(2);
    } catch (e) {
      setError((e as Error).message || 'ورود ناموفق بود.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="screen fade login-screen" id="login">
      <div className="auth-wrap">
        <span className="backlink" onClick={() => router.push('/')}>→ بازگشت به سایت</span>

        {step === 1 && (
          <div className="auth-step" id="step1">
            <div className="auth-card glass">
              <div className="auth-head">
                <img src="/logo.png" alt="KGtechvault" />
                <h2>ورود به پورتال</h2>
                <p>AUTHENTICATION // STEP 1 OF 3</p>
              </div>
              <div className="steps"><i className="done"></i><i></i><i></i></div>
              <div className="field"><label>نام کاربری</label>
                <input type="text" placeholder="نام کاربری صادرشده توسط ادمین" value={username}
                  onChange={(e) => setUsername(e.target.value)} />
              </div>
              <div className="field"><label>رمز عبور</label>
                <input type="password" placeholder="••••••••••" value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && submitCredentials()} />
              </div>
              {error && <div className="pform-error" style={{ marginBottom: 12 }}>{error}</div>}
              <button className="btn btn-accent full" onClick={submitCredentials} disabled={busy}>
                {busy ? 'در حال بررسی…' : 'ادامه ←'}
              </button>
              <div className="auth-foot">رمز را فراموش کرده‌اید؟ <a href="#">بازیابی حساب</a></div>
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="auth-step" id="step2">
            <div className="auth-card glass">
              <div className="auth-head">
                <img src="/logo.png" alt="KGtechvault" />
                <h2>تایید انسانی بودن</h2>
                <p>AUTHENTICATION // STEP 2 OF 3</p>
              </div>
              <div className="steps"><i className="done"></i><i className="done"></i><i></i></div>
              <div className={`captcha-box glass${captcha ? ' checked' : ''}`} id="captchaBox" onClick={() => setCaptcha((c) => !c)}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}><div className="chk"></div><span>من ربات نیستم</span></div>
                <small>KGTV-VERIFY</small>
              </div>
              <button className="btn btn-accent full" onClick={() => captcha && setStep(3)}>ادامه ←</button>
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="auth-step" id="step3">
            <div className="auth-card glass">
              <div className="auth-head">
                <img src="/logo.png" alt="KGtechvault" />
                <h2>تایید دو مرحله‌ای</h2>
                <p>AUTHENTICATION // STEP 3 OF 3</p>
              </div>
              <div className="steps"><i className="done"></i><i className="done"></i><i className="done"></i></div>
              <div className="field" style={{ textAlign: 'center' }}>
                <label style={{ textAlign: 'center' }}>کد ۶ رقمی ارسال‌شده را وارد کنید</label>
                <div className="otp-row" style={{ justifyContent: 'center', marginTop: 10 }}>
                  <input maxLength={1} /><input maxLength={1} /><input maxLength={1} /><input maxLength={1} /><input maxLength={1} /><input maxLength={1} />
                </div>
              </div>
              <button className="btn btn-accent full" onClick={() => router.push('/browse')}>ورود به سامانه ←</button>
              <div className="auth-foot">کد دریافت نشد؟ <a href="#">ارسال مجدد (۰۰:۵۹)</a></div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
