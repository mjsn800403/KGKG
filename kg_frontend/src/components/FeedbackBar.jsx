'use client';

import { useState } from 'react';

// Human-in-the-loop: a 👍/👎 verdict on an assistant answer. A 👎 expands into
// a reason (and optional comment). Verdicts feed a guarded ranking boost in the
// backend (feedback.blob_boost_map), so the assistant learns from real use.

const REASONS = [
  { key: 'wrong', label: 'اشتباه بود' },
  { key: 'irrelevant', label: 'ربطی نداشت' },
  { key: 'incomplete', label: 'ناقص بود' },
];

export default function FeedbackBar({ onRate }) {
  const [state, setState] = useState('idle');   // idle | reason | done
  const [reason, setReason] = useState(null);
  const [comment, setComment] = useState('');

  function up() {
    setState('done');
    onRate?.({ verdict: 1 });
  }
  function down() {
    setState('reason');
  }
  function submitDown() {
    setState('done');
    onRate?.({ verdict: -1, reason, comment: comment.trim() || null });
  }

  if (state === 'done') {
    return <div className="fb-bar fb-done">ممنون از بازخوردت 🙏</div>;
  }

  return (
    <div className="fb-bar">
      {state === 'idle' && (
        <>
          <span className="fb-q">این پاسخ کمک‌کننده بود؟</span>
          <button className="fb-btn" onClick={up} aria-label="پاسخ خوب بود">👍</button>
          <button className="fb-btn" onClick={down} aria-label="پاسخ خوب نبود">👎</button>
        </>
      )}
      {state === 'reason' && (
        <div className="fb-reason">
          <div className="fb-chips">
            {REASONS.map((r) => (
              <button
                key={r.key}
                className={`fb-chip${reason === r.key ? ' active' : ''}`}
                onClick={() => setReason(r.key)}
              >
                {r.label}
              </button>
            ))}
          </div>
          <input
            className="fb-comment"
            placeholder="توضیح اختیاری…"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
          />
          <button className="fb-send" onClick={submitDown} disabled={!reason}>
            ارسال بازخورد
          </button>
        </div>
      )}
    </div>
  );
}
