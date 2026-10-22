'use client';

// Plain sheet table for the flat-rate manual. With `filters` it becomes the
// LTS browser: text search + per-column selects, rendered a page at a time
// (the sheet has ~5,000 rows).
import { useMemo, useState } from 'react';
import useUnsealed, { SealedNotice } from '@/lib/useUnsealed';

const PAGE = 100;
const FA = (n) => Number(n).toLocaleString('fa-IR');

export default function FrmTable({ columns, rows: plain, sealed, filters = [], headTitles = {}, hideEmpty = false }) {
  const opened = useUnsealed(sealed, plain);
  const rows = useMemo(() => opened || [], [opened]);
  const [q, setQ] = useState('');
  const [sel, setSel] = useState({});
  const [shown, setShown] = useState(PAGE);

  const filterIdx = useMemo(
    () => filters.map((f) => ({ ...f, i: columns.indexOf(f.column) })).filter((f) => f.i >= 0),
    [filters, columns]);
  const options = useMemo(() => filterIdx.map(({ i }) =>
    [...new Set(rows.map((r) => r[i]).filter(Boolean))]
      .sort((a, b) => String(a).localeCompare(String(b), 'en', { numeric: true }))),
  [rows, filterIdx]);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return rows.filter((r) =>
      filterIdx.every(({ i }) => !sel[i] || r[i] === sel[i])
      && (!needle || r.some((c) => String(c).toLowerCase().includes(needle))));
  }, [rows, q, sel, filterIdx]);

  // Hour columns that are blank for every visible row are noise; drop them.
  const visibleCols = columns.map((c, i) => i).filter((i) =>
    !hideEmpty || !/^Hours\(/.test(columns[i]) || filtered.some((r) => r[i] !== ''));

  if (sealed && !opened) return <SealedNotice value={opened} />;

  return (
    <div className="frm-wrap">
      {filterIdx.length > 0 && (
        <div className="frm-filters">
          <input className="frm-search" type="search" placeholder="جستجو در عملیات، قطعه، کد…"
            value={q} onChange={(e) => { setQ(e.target.value); setShown(PAGE); }} />
          {filterIdx.map(({ i, label }, n) => (
            <select key={i} value={sel[i] || ''} onChange={(e) => { setSel({ ...sel, [i]: e.target.value }); setShown(PAGE); }}>
              <option value="">{label}: همه</option>
              {options[n].map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
          ))}
          <span className="frm-count">{FA(filtered.length)} ردیف</span>
        </div>
      )}
      <div className="frm-scroll">
        <table className="frm-table">
          <thead>
            <tr>{visibleCols.map((i) => <th key={i} title={headTitles[columns[i]] || undefined}>{columns[i]}</th>)}</tr>
          </thead>
          <tbody>
            {filtered.slice(0, shown).map((r, k) => (
              <tr key={k}>{visibleCols.map((i) => <td key={i}>{r[i]}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </div>
      {filtered.length === 0 && <div className="empty-state">ردیفی مطابق فیلتر یافت نشد.</div>}
      {shown < filtered.length && (
        <button type="button" className="btn frm-more" onClick={() => setShown(shown + PAGE * 5)}>
          نمایش ردیف‌های بیشتر ({FA(filtered.length - shown)} باقی‌مانده)
        </button>
      )}
    </div>
  );
}
