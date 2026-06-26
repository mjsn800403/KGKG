'use client';

import { useEffect, useState } from 'react';
import { fetchRecentFeedback, pinFeedback, setAdminToken } from '../../utils/api';

// Token prompt shown until a valid admin token is supplied. The token is held
// only in sessionStorage (see api.setAdminToken) — never in the bundle — and is
// what the server-side gate (KG_ADMIN_TOKEN) checks before exposing the queue or
// accepting a pin.
function TokenGate({ onAuthed, error }) {
  const [token, setToken] = useState('');
  return (
    <div className="review-wrap" dir="rtl" style={{ maxWidth: 460 }}>
      <h1 style={{ fontSize: 20, marginBottom: 8 }}>ورود کارشناس</h1>
      <p style={{ color: 'var(--text-faint)', fontSize: 13, marginBottom: 14 }}>
        این بخش فقط برای کارشناس است. توکن مدیریت (KG_ADMIN_TOKEN) را وارد کن.
      </p>
      <input
        type="password" dir="ltr" placeholder="admin token"
        value={token} onChange={(e) => setToken(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && token.trim() && onAuthed(token.trim())}
        style={{ padding: '8px 10px', fontSize: 14, width: '100%', boxSizing: 'border-box' }}
      />
      {error && <p style={{ color: 'crimson', fontSize: 13, marginTop: 8 }}>{error}</p>}
      <button
        onClick={() => token.trim() && onAuthed(token.trim())}
        style={{ marginTop: 12, padding: '8px 18px', fontSize: 14 }}
      >
        ورود
      </button>
    </div>
  );
}

// Minimal human-in-the-loop review queue: the recent 👎 verdicts, so a domain
// expert can spot bad answers and pin a correction (a verified source for the
// query pattern) straight from the queue — no curl required.
const REASON_FA = { wrong: 'اشتباه بود', irrelevant: 'ربطی نداشت', incomplete: 'ناقص بود' };

// Inline pin form for one review item. The expert supplies the correct source
// link (app_url) for the query; pattern_query defaults to the failed query.
function PinForm({ item, onDone }) {
  const [appUrl, setAppUrl] = useState('');
  const [title, setTitle] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState(null);   // 'ok' | 'err' | null

  const submit = async () => {
    if (!appUrl.trim()) {
      setStatus('err');
      return;
    }
    setBusy(true);
    setStatus(null);
    try {
      const ok = await pinFeedback({
        patternQuery: item.query || '',
        appUrl: appUrl.trim(),
        blobId: item.blob_id ?? null,
        title: title.trim() || null,
        note: note.trim() || null,
        by: 'admin-review',
      });
      setStatus(ok ? 'ok' : 'err');
      if (ok) onDone?.();
    } catch {
      setStatus('err');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ marginTop: 10, display: 'grid', gap: 6 }}>
      <input
        type="text" dir="ltr" placeholder="لینک منبع درست (app_url) — مثلاً /Toyota/2022/.../..."
        value={appUrl} onChange={(e) => setAppUrl(e.target.value)}
        style={{ padding: '6px 8px', fontSize: 13 }}
      />
      <input
        type="text" placeholder="عنوان منبع (اختیاری)"
        value={title} onChange={(e) => setTitle(e.target.value)}
        style={{ padding: '6px 8px', fontSize: 13 }}
      />
      <input
        type="text" placeholder="یادداشت کارشناس (اختیاری)"
        value={note} onChange={(e) => setNote(e.target.value)}
        style={{ padding: '6px 8px', fontSize: 13 }}
      />
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <button onClick={submit} disabled={busy} style={{ padding: '6px 14px', fontSize: 13 }}>
          {busy ? 'در حال ثبت…' : 'ثبت پین'}
        </button>
        {status === 'ok' && <span style={{ color: 'green', fontSize: 13 }}>✓ پین شد</span>}
        {status === 'err' && <span style={{ color: 'crimson', fontSize: 13 }}>خطا — لینک را بررسی کن</span>}
      </div>
    </div>
  );
}

export default function AdminReviewPage() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [openPin, setOpenPin] = useState(null);   // index of the item being pinned
  const [pinned, setPinned] = useState({});        // index -> true once pinned
  const [authed, setAuthed] = useState(false);
  const [authError, setAuthError] = useState(null);

  // Only the async result touches state (never synchronously in the effect body),
  // so callers that want a spinner set `loading` themselves first.
  function load() {
    fetchRecentFeedback(100).then((d) => {
      if (d.unauthorized) {
        setAdminToken('');
        setAuthed(false);
        setAuthError('توکن نادرست یا تنظیم‌نشده است.');
        setLoading(false);
        return;
      }
      setItems(d.items || []);
      setAuthed(true);
      setLoading(false);
    });
  }

  // Always attempt the load: in dev (DEBUG) the server allows it without a token
  // (loading starts true), so no ceremony; in prod an unauthorized response flips
  // us to the token gate.
  useEffect(() => { load(); }, []);

  function onAuthed(token) {
    setAdminToken(token);
    setAuthError(null);
    setLoading(true);
    load();
  }

  if (!authed) {
    return <TokenGate onAuthed={onAuthed} error={authError} />;
  }

  return (
    <div className="review-wrap" dir="rtl">
      <h1 style={{ fontSize: 20, marginBottom: 4 }}>صف بازبینی بازخوردها</h1>
      <p style={{ color: 'var(--text-faint)', fontSize: 13, marginBottom: 18 }}>
        پاسخ‌هایی که کاربران 👎 داده‌اند. برای اصلاح دائمی، روی «پین اصلاح» بزن و
        لینک منبع درست را وارد کن — همان الگوی پرسش در آینده این منبع تأییدشده را
        بالای نتایج می‌آورد.
      </p>
      {loading && <p style={{ color: 'var(--text-faint)' }}>در حال بارگذاری…</p>}
      {!loading && items.length === 0 && (
        <p style={{ color: 'var(--text-faint)' }}>هنوز بازخورد منفی‌ای ثبت نشده.</p>
      )}
      {items.map((it, i) => (
        <div className="review-item" key={i}>
          <div className="review-q">{it.query || '—'}</div>
          <div className="review-meta">
            <span>{it.ts}</span>
            {it.mode && <span>حالت: {it.mode}</span>}
            {(it.model || it.car_stem) && <span>{it.model || it.car_stem}</span>}
            {it.blob_id != null && <span>blob #{it.blob_id}</span>}
          </div>
          {it.reason && <span className="review-reason">{REASON_FA[it.reason] || it.reason}</span>}
          {it.comment && <p style={{ marginTop: 6, fontSize: 13 }}>{it.comment}</p>}
          <div style={{ marginTop: 8 }}>
            {pinned[i] ? (
              <span style={{ color: 'green', fontSize: 13 }}>✓ اصلاح پین شد</span>
            ) : (
              <button
                onClick={() => setOpenPin(openPin === i ? null : i)}
                style={{ padding: '5px 12px', fontSize: 13 }}
              >
                {openPin === i ? 'بستن' : 'پین اصلاح'}
              </button>
            )}
          </div>
          {openPin === i && !pinned[i] && (
            <PinForm
              item={it}
              onDone={() => {
                setPinned((p) => ({ ...p, [i]: true }));
                setOpenPin(null);
              }}
            />
          )}
        </div>
      ))}
    </div>
  );
}
