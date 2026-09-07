'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { portalLogin, verifyOtp, resendOtp } from '@/utils/api';

const TURNSTILE_SITEKEY = '0x4AAAAAAEjnbFG2W2QYf-cE';
const RESEND_COOLDOWN = 60;
// Must match OtpChallenge.DEFAULT_TTL on the backend (minutes=2).
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

export default function Login() {
  const router = useRouter();
  const [step, setStep] = useState(1);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [token, setToken] = useState('');

  // OTP state
  const [otpSession, setOtpSession] = useState('');
  const [phoneHint, setPhoneHint] = useState('');
  const [otp, setOtp] = useState(['', '', '', '', '', '']);
  const [resendCooldown, setResendCooldown] = useState(0);
  const [expiry, setExpiry] = useState(0);
  const otpRefs = useRef<(HTMLInputElement | null)[]>([]);
  const cooldownRef = useRef<ReturnType<typeof setInterval> | null>(null);

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
    });
  }, []);

  useEffect(() => {
    if (window.turnstile) { renderWidget(); }
    else {
      const existing = document.querySelector('script[data-cf-turnstile]');
      if (!existing) {
        const s = document.createElement('script');
        s.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
        s.async = true; s.defer = true;
        s.setAttribute('data-cf-turnstile', '1');
        s.onload = renderWidget;
        document.head.appendChild(s);
      } else {
        existing.addEventListener('load', renderWidget);
      }
    }
    const iv = setInterval(() => { if (window.turnstile) { renderWidget(); clearInterval(iv); } }, 300);
    return () => {
      clearInterval(iv);
      // Only remove while the container is still in the document. React can
      // detach it first, and Turnstile then logs 'Cannot find Widget'.
      try {
        if (widgetId.current && boxRef.current?.isConnected) {
          window.turnstile?.remove(widgetId.current);
        }
      } catch { /* noop */ }
      widgetId.current = null;
    };
  }, [renderWidget]);

  function startCooldown() {
    setResendCooldown(RESEND_COOLDOWN);
    setExpiry(OTP_TTL);
    if (cooldownRef.current) clearInterval(cooldownRef.current);
    cooldownRef.current = setInterval(() => {
      setResendCooldown(c => (c <= 1 ? 0 : c - 1));
      setExpiry(e => {
        // The expiry window is the longest timer; stop the interval when it ends.
        if (e <= 1) { clearInterval(cooldownRef.current!); return 0; }
        return e - 1;
      });
    }, 1000);
  }

  useEffect(() => () => { if (cooldownRef.current) clearInterval(cooldownRef.current); }, []);

  async function submitCredentials() {
    if (busy) return;
    setError('');
    if (!username.trim() || !password) {
      setError('نام کاربری و رمز عبور را وارد کنید.');
      return;
    }
    if (!token) {
      setError('لطفاً تأیید کنید که ربات نیستید.');
      return;
    }
    setBusy(true);
    try {
      const data = await portalLogin(username.trim(), password, token);
      setOtpSession(data.otp_session);
      setPhoneHint(data.phone_hint || '');
      startCooldown();
      setStep(2);
      setTimeout(() => otpRefs.current[0]?.focus(), 100);
    } catch (e) {
      setError((e as Error).message || 'ورود ناموفق بود.');
      setToken('');
      try { window.turnstile?.reset(widgetId.current || undefined); } catch { /* noop */ }
    } finally {
      setBusy(false);
    }
  }

  function handleOtpKey(idx: number, e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Backspace') {
      if (otp[idx]) {
        const next = [...otp]; next[idx] = '';
        setOtp(next);
      } else if (idx > 0) {
        otpRefs.current[idx - 1]?.focus();
      }
    } else if (e.key === 'ArrowLeft' && idx > 0) {
      otpRefs.current[idx - 1]?.focus();
    } else if (e.key === 'ArrowRight' && idx < 5) {
      otpRefs.current[idx + 1]?.focus();
    }
  }

  function handleOtpChange(idx: number, val: string) {
    const digits = val.replace(/\D/g, '').replace(/[۰-۹]/g, d => String(d.charCodeAt(0) - 1776));
    if (!digits) return;
    if (digits.length > 1) {
      // paste: fill all
      const next = [...otp];
      for (let i = 0; i < 6 && i < digits.length; i++) next[i] = digits[i];
      setOtp(next);
      otpRefs.current[Math.min(digits.length, 5)]?.focus();
      return;
    }
    const next = [...otp]; next[idx] = digits[0];
    setOtp(next);
    if (idx < 5) otpRefs.current[idx + 1]?.focus();
  }

  async function submitOtp() {
    if (busy) return;
    const code = otp.join('');
    if (code.length !== 6) { setError('کد ۶ رقمی را کامل وارد کنید.'); return; }
    setError('');
    setBusy(true);
    try {
      await verifyOtp(otpSession, code);
      router.push('/browse');
    } catch (e) {
      setError((e as Error).message || 'تأیید ناموفق بود.');
      setOtp(['', '', '', '', '', '']);
      otpRefs.current[0]?.focus();
    } finally {
      setBusy(false);
    }
  }

  async function handleResend() {
    if (resendCooldown > 0 || busy) return;
    setError('');
    setBusy(true);
    try {
      await resendOtp(otpSession);
      startCooldown();
      setOtp(['', '', '', '', '', '']);
      otpRefs.current[0]?.focus();
    } catch (e) {
      setError((e as Error).message || 'ارسال مجدد ناموفق بود.');
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
                <p>AUTHENTICATION // STEP 1 OF 2</p>
              </div>
              <div className="steps"><i className="done"></i><i></i></div>
              <div className="field"><label>نام کاربری</label>
                <input type="text" placeholder="نام کاربری صادرشده توسط ادمین" value={username}
                  onChange={(e) => setUsername(e.target.value)} />
              </div>
              <div className="field"><label>رمز عبور</label>
                <input type="password" placeholder="••••••••••" value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && submitCredentials()} />
              </div>
              <div ref={boxRef} style={{ marginBottom: 12, display: 'flex', justifyContent: 'center' }}></div>
              {error && <div className="pform-error" style={{ marginBottom: 12 }}>{error}</div>}
              <button className="btn btn-accent full" onClick={submitCredentials} disabled={busy || !token}>
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
                <h2>تایید دو مرحله‌ای</h2>
                <p>AUTHENTICATION // STEP 2 OF 2</p>
              </div>
              <div className="steps"><i className="done"></i><i className="done"></i></div>
              <div className="field" style={{ textAlign: 'center' }}>
                <label style={{ textAlign: 'center', display: 'block', marginBottom: 4 }}>
                  کد ۶ رقمی ارسال‌شده به <bdi dir="ltr" style={{ unicodeBidi: 'isolate' }}>{phoneHint}</bdi> را وارد کنید
                </label>
                <div className="otp-row" style={{ justifyContent: 'center', marginTop: 10, direction: 'ltr' }}>
                  {otp.map((d, i) => (
                    <input
                      key={i}
                      ref={el => { otpRefs.current[i] = el; }}
                      maxLength={6}
                      inputMode="numeric"
                      value={d}
                      onChange={e => handleOtpChange(i, e.target.value)}
                      onKeyDown={e => handleOtpKey(i, e)}
                      onFocus={e => e.target.select()}
                      style={{ textAlign: 'center', width: 44, fontSize: '1.4rem' }}
                    />
                  ))}
                </div>
                {expiry > 0
                  ? <div style={{ marginTop: 12, fontSize: '0.82rem', opacity: 0.7 }}>اعتبار کد: {String(Math.floor(expiry / 60)).padStart(2, '0')}:{String(expiry % 60).padStart(2, '0')}</div>
                  : <div style={{ marginTop: 12, fontSize: '0.82rem', color: '#e06666' }}>کد منقضی شده است. لطفاً کد جدید درخواست کنید.</div>}
              </div>
              {error && <div className="pform-error" style={{ marginBottom: 12 }}>{error}</div>}
              <button className="btn btn-accent full" onClick={submitOtp} disabled={busy || otp.join('').length !== 6 || expiry === 0}>
                {busy ? 'در حال بررسی…' : 'ورود به سامانه ←'}
              </button>
              <div className="auth-foot">
                کد دریافت نشد؟{' '}
                {resendCooldown > 0
                  ? <span style={{ opacity: 0.6 }}>ارسال مجدد ({String(Math.floor(resendCooldown / 60)).padStart(2, '0')}:{String(resendCooldown % 60).padStart(2, '0')})</span>
                  : <a href="#" onClick={e => { e.preventDefault(); handleResend(); }}>ارسال مجدد</a>}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
