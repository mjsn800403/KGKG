'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';

export default function Login() {
  const router = useRouter();
  const [step, setStep] = useState(1);
  const [captcha, setCaptcha] = useState(false);

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
              <div className="field"><label>نام کاربری</label><input type="text" placeholder="مثلاً: khadamatgostar_0142" /></div>
              <div className="field"><label>رمز عبور</label><input type="password" placeholder="••••••••••" /></div>
              <button className="btn btn-accent full" onClick={() => setStep(2)}>ادامه ←</button>
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
              <button className="btn btn-accent full" onClick={() => setStep(3)}>ادامه ←</button>
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
