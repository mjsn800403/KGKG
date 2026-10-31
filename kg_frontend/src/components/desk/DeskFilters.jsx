'use client';

import Icon from '../Icon';
import { faNum } from '../../lib/support';

// The filter bar both sides share. A cleared field is dropped from the query
// rather than sent empty, so "no filter" and "filter for nothing" stay
// different things.

export default function DeskFilters({
  value, onChange, topics = [], statuses = [], extra = null, counts = {},
}) {
  const set = (patch) => onChange({ ...value, ...patch, cursor: null });

  return (
    <div className="dk-filters">
      <label className="dk-search">
        <Icon name="search" size={15} />
        <input
          type="search"
          value={value.q || ''}
          placeholder="جستجو در موضوع و متن پیام‌ها…"
          aria-label="جستجو در تیکت‌ها"
          onChange={(e) => set({ q: e.target.value })}
        />
      </label>

      <div className="dk-chips">
        <button type="button" className={`inbox-fbtn${!value.status ? ' on' : ''}`}
          onClick={() => set({ status: '' })}>همه</button>
        {statuses.map((s) => (
          <button key={s.id} type="button"
            className={`inbox-fbtn${value.status === s.id ? ' on' : ''}`}
            onClick={() => set({ status: s.id })}>
            {s.label}
            {counts[s.id] ? <span className="inbox-fcount">{faNum(counts[s.id])}</span> : null}
          </button>
        ))}
      </div>

      <div className="dk-chips">
        <select className="dk-select" aria-label="دستهٔ مشکل"
          value={value.topic || ''} onChange={(e) => set({ topic: e.target.value })}>
          <option value="">همهٔ دسته‌ها</option>
          {topics.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
        </select>
        <button type="button" className={`inbox-fbtn${value.unread ? ' on' : ''}`}
          onClick={() => set({ unread: value.unread ? '' : '1' })}>
          <Icon name="mail" size={14} /> فقط خوانده‌نشده
        </button>
        {extra}
      </div>
    </div>
  );
}
