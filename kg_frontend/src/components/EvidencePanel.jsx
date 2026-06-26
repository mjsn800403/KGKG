'use client';

import { useState } from 'react';
import Link from 'next/link';

// Transparency / interpretability for a high-stakes repair assistant: show WHY
// the answer was given — which sources grounded it, how confident the retrieval
// was, and how each source matched. All of this is computed in the backend
// (scoring.calibrate / confidence_band) and passed straight through.

const MATCHED_VIA_FA = {
  exact_code: 'تطابق دقیق کد',
  keyword: 'تطابق کلیدواژه',
  semantic: 'شباهت معنایی',
  vehicle: 'همین خودرو',
  expert_verified: 'تأییدشدهٔ کارشناس',
  diagnostic: 'موتور تشخیص',
};

function bandClass(band) {
  return band === 'high' ? 'conf-high' : band === 'low' ? 'conf-low' : 'conf-medium';
}

function SourceRow({ s }) {
  const sim = typeof s.similarity === 'number' ? Math.max(0, Math.min(1, s.similarity)) : null;
  const internal = (s.url || '').startsWith('/');
  const tag = MATCHED_VIA_FA[s.matched_via] || null;
  return (
    <li className="evi-source">
      <span className="evi-num">{s.n}</span>
      <div className="evi-source-body">
        <div className="evi-source-title">
          {internal ? (
            <Link href={s.url} className="evi-link">{s.title || s.url} ←</Link>
          ) : (
            <span>{s.title}</span>
          )}
        </div>
        <div className="evi-source-meta">
          {(s.model || s.variant) && (
            <span className="evi-veh">{s.model} {s.variant}</span>
          )}
          {tag && <span className={`evi-via evi-via-${s.matched_via}`}>{tag}</span>}
          {s.band && <span className={`evi-band ${bandClass(s.band)}`}>{s.band_label || s.band}</span>}
        </div>
        {sim != null && (
          <div className="evi-bar" title={`شباهت ${(sim * 100).toFixed(0)}٪`}>
            <span className={`evi-bar-fill ${bandClass(s.band)}`} style={{ width: `${sim * 100}%` }} />
          </div>
        )}
      </div>
    </li>
  );
}

export default function EvidencePanel({ sources = [], confidence, grounded, mode, degraded }) {
  const [open, setOpen] = useState(false);
  const hasSources = sources && sources.length > 0;
  if (!hasSources && grounded !== false && !degraded) return null;

  return (
    <div className="evi-panel">
      <div className="evi-badges">
        {mode && (
          <span className="evi-badge evi-mode">
            {mode === 'diagnose' ? '🔧 تشخیص عیب' : '📖 جستجوی دفترچه'}
          </span>
        )}
        {degraded && (
          <span className="evi-badge conf-medium" title="پاسخ بدون مدل زبانی تولید شده">
            ⚙️ حالت بدون هوش مصنوعی
          </span>
        )}
        {confidence?.band && (
          <span className={`evi-badge ${bandClass(confidence.band)}`}>
            اطمینان: {confidence.label || confidence.band}
          </span>
        )}
        {grounded === false && (
          <span className="evi-badge conf-low">⚠️ این پاسخ در داده‌های ما پایه ندارد</span>
        )}
        {mode === 'diagnose' && grounded !== false && (
          <span className="evi-disclaimer">تشخیص اولیه — تأیید نهایی با تست عملی</span>
        )}
      </div>

      {hasSources && (
        <>
          <button className="evi-toggle" onClick={() => setOpen((o) => !o)}>
            {open ? '▾' : '▸'} چرا این پاسخ؟ ({sources.length} منبع)
          </button>
          {open && (
            <ul className="evi-sources">
              {sources.map((s, i) => <SourceRow key={i} s={s} />)}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
