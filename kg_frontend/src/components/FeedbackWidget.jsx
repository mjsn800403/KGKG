'use client';

import { useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import Icon from './Icon';
import { feedbackApi } from '../utils/api';
import { csatFace, faNum } from '../lib/support';
import { friendlyError } from '../lib/friendlyError';

// A way to say "this page is wrong" without telephoning anybody.
//
// The product had exactly one digital feedback surface before this: the thumb
// on an assistant answer. An opinion about any other screen had nowhere to go,
// which is half of why feedback arrived by telephone. This is deliberately not
// a support ticket — it asks for nothing and carries no SLA — so it posts to
// /api/feedback/submit/ and lands in its own admin feed.
//
// The current path is sent with it, because "the search is slow" is only
// actionable if you know where the person was standing.

const SCORES = [1, 2, 3, 4, 5];
const SCORE_LABELS = { 1: 'خیلی بد', 2: 'بد', 3: 'متوسط', 4: 'خوب', 5: 'خیلی خوب' };

export default function FeedbackWidget() {
  const [open, setOpen] = useState(false);
  const [rating, setRating] = useState(null);
  const [comment, setComment] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [sent, setSent] = useState(false);
  const boxRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('keydown', onKey);
    const t = setTimeout(() => boxRef.current?.querySelector('button')?.focus(), 60);
    return () => { document.removeEventListener('keydown', onKey); clearTimeout(t); };
  }, [open]);

  const reset = () => { setRating(null); setComment(''); setErr(''); setSent(false); };

  const submit = async () => {
    const text = comment.trim();
    if (!rating && !text) { setErr('امتیاز یا توضیح لازم است.'); return; }
    setBusy(true); setErr('');
    try {
      await feedbackApi.submit({
        page: typeof window === 'undefined' ? '' : window.location.pathname,
        rating: rating || undefined,
        comment: text || undefined,
      });
      setSent(true);
      setTimeout(() => { setOpen(false); reset(); }, 2200);
    } catch (e) {
      setErr(friendlyError(e, 'ارسال بازخورد ناموفق بود.'));
    } finally { setBusy(false); }
  };

  return (
    <>
      <button
        type="button"
        className="fbw-launch"
        aria-label="ارسال بازخورد دربارهٔ این صفحه"
        title="بازخورد"
        onClick={() => setOpen((o) => !o)}
      >
        <Icon name="mailplus" size={17} />
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            className="fbw-panel glass"
            ref={boxRef}
            role="dialog"
            aria-label="ارسال بازخورد"
            initial={{ opacity: 0, y: 14, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 10, scale: 0.98 }}
          >
            {sent ? (
              <div className="fbw-done">بازخورد شما ثبت شد. ممنون 🙏</div>
            ) : (
              <>
                <div className="fbw-head">
                  <b>بازخورد دربارهٔ این صفحه</b>
                  <button type="button" className="guide-icon-btn" aria-label="بستن"
                    onClick={() => setOpen(false)}>
                    <Icon name="x" size={15} />
                  </button>
                </div>
                <p className="fbw-sub">
                  این یک تیکت پشتیبانی نیست؛ اگر مشکلی دارید که باید حل شود، از صفحهٔ
                  «پشتیبانی و درخواست‌ها» تیکت بدهید.
                </p>
                <div className="fbw-faces" role="radiogroup" aria-label="امتیاز به این صفحه">
                  {SCORES.map((s) => (
                    <button
                      type="button"
                      key={s}
                      role="radio"
                      aria-checked={rating === s}
                      aria-label={`${faNum(s)} از ۵ — ${SCORE_LABELS[s]}`}
                      title={SCORE_LABELS[s]}
                      className={`csat-face${rating === s ? ' on' : ''}`}
                      onClick={() => { setRating(s); setErr(''); }}
                    >
                      <span aria-hidden="true">{csatFace(s)}</span>
                    </button>
                  ))}
                </div>
                <textarea
                  className="fbw-comment"
                  rows={3}
                  value={comment}
                  onChange={(e) => { setComment(e.target.value); setErr(''); }}
                  placeholder="چه چیزی بهتر می‌شد؟ (اختیاری اگر امتیاز داده‌اید)"
                  aria-label="توضیح بازخورد"
                />
                {err && <div className="pform-error">{err}</div>}
                <div className="fbw-actions">
                  <button type="button" className="btn btn-accent" disabled={busy} onClick={submit}>
                    {busy ? 'در حال ارسال…' : 'ارسال بازخورد'}
                  </button>
                </div>
              </>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}
