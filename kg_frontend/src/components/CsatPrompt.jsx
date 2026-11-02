'use client';

import { useState } from 'react';
import { csatFace, faNum } from '../lib/support';

// The question nobody was asking: was the resolution any good?
//
// Asked once, after closure, of the person who filed the ticket (api/
// requests_api._seat_csat enforces both). Five faces rather than a number,
// because a technician in a workshop reads a face faster than a scale, and the
// comment is optional so a score is never blocked behind writing prose.

const SCORES = [1, 2, 3, 4, 5];
const SCORE_LABELS = {
  1: 'خیلی بد', 2: 'بد', 3: 'متوسط', 4: 'خوب', 5: 'خیلی خوب',
};

export default function CsatPrompt({ onRate }) {
  const [score, setScore] = useState(null);
  const [comment, setComment] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  const submit = async () => {
    if (!score) { setErr('یک امتیاز انتخاب کنید.'); return; }
    setBusy(true); setErr('');
    try {
      await onRate?.({ score, comment: comment.trim() || undefined });
    } catch (e) {
      setErr(e?.message || 'ثبت امتیاز ناموفق بود.');
    } finally { setBusy(false); }
  };

  return (
    <div className="csat">
      <div className="csat-q">از رسیدگی به این درخواست چقدر راضی بودید؟</div>
      <div className="csat-faces" role="radiogroup" aria-label="امتیاز رضایت">
        {SCORES.map((s) => (
          <button
            type="button"
            key={s}
            role="radio"
            aria-checked={score === s}
            aria-label={`${faNum(s)} از ۵ — ${SCORE_LABELS[s]}`}
            title={SCORE_LABELS[s]}
            className={`csat-face${score === s ? ' on' : ''}`}
            onClick={() => { setScore(s); setErr(''); }}
          >
            <span aria-hidden="true">{csatFace(s)}</span>
          </button>
        ))}
      </div>
      {score && (
        <>
          <input
            className="csat-comment"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="توضیح اختیاری…"
            aria-label="توضیح اختیاری دربارهٔ رضایت"
          />
          <button type="button" className="btn btn-accent csat-send" disabled={busy} onClick={submit}>
            {busy ? 'در حال ثبت…' : 'ثبت امتیاز'}
          </button>
        </>
      )}
      {err && <div className="pform-error">{err}</div>}
    </div>
  );
}
