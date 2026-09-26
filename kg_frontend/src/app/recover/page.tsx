'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { recoverStart, recoverReset, resendOtp } from '@/utils/api';

const TURNSTILE_SITEKEY = '0x4AAAAAAEjnbFG2W2QYf-cE';
// Must match OtpChallenge.DEFAULT_TTL / RESEND_INTERVAL on the backend.
const OTP_TTL = 120;

declare global {
  interface Window {
    turnstile?: {
      render: (el: HTMLElement, opts: Record<string, unknown>) => string;
      reset: (id?: string) => void;
      remove: (id?: string) => void;
    };
  }
}

const toLatin = (s: string) => s.replace(/[۰-۹]/g, d => String(d.charCodeAt(0) - 1776));

export default function Recover() {
  const router = useRouter();
  const [step, setStep] = useState(1);
  const [identifier, setIdentifier] = useState('');
  const [token, setToken] = useState('');
  const [otpSession, setOtpSession] = useState('');
  const [code, setCode] = useState('');
  const [pw, setPw] = useState('');
  const [pw2, setPw2] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [left, setLeft] = useState(0);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const boxRef = useRef<HTMLDivElement | null>(null);
  const widgetId = useRef<string | null>(null);

  const renderWidget = useCallback(() => {
    if (!boxRef.current || widgetId.current || !window.turnstile) return;
    widgetId.current = window.turnstile.render(boxRef.current, {
      sitekey: TURNSTILE_SITEKEY,
      action: 'login',
      callback: (t: string) => setToken(t),
      'expired-callback': () => setToken(''),
      'error-callback': () => setToken(''),
      // follow the portal's own theme instead of a white box on the dark page
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

  function startTimer() {
    setLeft(OTP_TTL);
    if (timer.current) clearInterval(timer.current);
    timer.current = setInterval(() => setLeft(l => {
      if (l <= 1) { clearInterval(timer.current!); return 0; }
      return l - 1;
    }), 1000);
  }
  useEffect(() => () => { if (timer.current) clearInterval(timer.current); }, []);

  async function sendCode() {
    if (busy) return;
    setError('');
    if (!identifier.trim()) { setError('نام کاربری، ایمیل یا شماره موبایل را وارد کنید.'); return; }
    if (!token) { setError('لطفاً تأیید کنید که ربات نیستید.'); return; }
    setBusy(true);
    try {
      const data = await recoverStart(toLatin(identifier.trim()), token);
      setOtpSession(data.otp_session);
      startTimer();
      setStep(2);
    } catch (e) {
      setError((e as Error).message || 'درخواست ناموفق بود.');
      setToken('');
      try { window.turnstile?.reset(widgetId.current || undefined); } catch { /* noop */ }
    } finally {
      setBusy(false);
    }
  }

  async function resend() {
    if (left > 0 || busy) return;
    setError('');
    setBusy(true);
    try {
      await resendOtp(otpSession);
      startTimer();
      setCode('');
    } catch (e) {
      setError((e as Error).message || 'ارسال مجدد ناموفق بود.');
    } finally {
      setBusy(false);
    }
  }

  async function reset() {
    if (busy) return;
    setError('');
    if (code.length !== 6) { setError('کد ۶ رقمی را کامل وارد کنید.'); return; }
    if (pw.length < 8) { setError('رمز عبور باید حداقل ۸ کاراکتر باشد.'); return; }
    if (pw !== pw2) { setError('تکرار رمز عبور با رمز عبور یکسان نیست.'); return; }
    setBusy(true);
    try {
      await recoverReset(otpSession, code, pw);
      router.push('/browse');
    } catch (e) {
      setError((e as Error).message || 'بازیابی ناموفق بود.');
      setCode('');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="screen fade login-screen" id="recover">
      <div className="auth-wrap">
        <span className="backlink" onClick={() => router.push('/login')}>→ بازگشت به ورود</span>
        <div className="auth-step">
          <div className="auth-card glass">
            <div className="auth-head">
              <img src="/brand/logo-mark.png" alt="KGtechvault" />
              <h2>بازیابی حساب</h2>
              <p>بازیابی حساب · مرحلهٔ {step === 1 ? '۱' : '۲'} از ۲</p>
            </div>
            <div className="steps"><i className="done"></i><i className={step === 2 ? 'done' : ''}></i></div>

            {step === 1 && (<>
              <div className="field"><label>نام کاربری، ایمیل یا شماره موبایل</label>
                <input type="text" dir="auto" placeholder="مثلاً 09121234567" value={identifier}
                  onChange={e => setIdentifier(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && sendCode()} />
              </div>
              <div ref={boxRef} style={{ marginBottom: 12, display: 'flex', justifyContent: 'center' }}></div>
              {error && <div className="pform-error" style={{ marginBottom: 12 }}>{error}</div>}
              <button className="btn btn-accent full" onClick={sendCode} disabled={busy || !token}>
                {busy ? 'در حال ارسال…' : 'ارسال کد بازیابی ←'}
              </button>
              <div className="auth-foot">کد به شماره موبایل ثبت‌شده برای حساب پیامک می‌شود.</div>
            </>)}

            {step === 2 && (<>
              <div className="auth-foot" style={{ marginTop: 0, marginBottom: 12 }}>
                اگر حسابی با این مشخصات وجود داشته باشد، کد ۶ رقمی به شماره موبایل ثبت‌شده آن ارسال شد.
              </div>
              <div className="field"><label>کد تأیید</label>
                <input type="text" inputMode="numeric" dir="ltr" maxLength={6} value={code}
                  style={{ textAlign: 'center', letterSpacing: '0.4em' }}
                  onChange={e => setCode(toLatin(e.target.value).replace(/\D/g, '').slice(0, 6))} />
              </div>
              <div className="field"><label>رمز عبور جدید</label>
                <input type="password" placeholder="حداقل ۸ کاراکتر" value={pw}
                  onChange={e => setPw(e.target.value)} />
              </div>
              <div className="field"><label>تکرار رمز عبور جدید</label>
                <input type="password" value={pw2} onChange={e => setPw2(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && reset()} />
              </div>
              <div style={{ marginBottom: 12, fontSize: '0.82rem', opacity: 0.7, textAlign: 'center' }}>
                {left > 0
                  ? <>اعتبار کد: {String(Math.floor(left / 60)).padStart(2, '0')}:{String(left % 60).padStart(2, '0')}</>
                  : 'کد منقضی شده است. لطفاً کد جدید درخواست کنید.'}
              </div>
              {error && <div className="pform-error" style={{ marginBottom: 12 }}>{error}</div>}
              <button className="btn btn-accent full" onClick={reset} disabled={busy || left === 0}>
                {busy ? 'در حال بررسی…' : 'تغییر رمز و ورود ←'}
              </button>
              <div className="auth-foot">
                کد دریافت نشد؟{' '}
                {left > 0
                  ? <span style={{ opacity: 0.6 }}>ارسال مجدد</span>
                  : <a href="#" onClick={e => { e.preventDefault(); resend(); }}>ارسال مجدد</a>}
              </div>
            </>)}
          </div>
        </div>
      </div>
    </div>
  );
}
