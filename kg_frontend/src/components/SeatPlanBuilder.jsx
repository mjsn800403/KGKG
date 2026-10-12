'use client';

import Icon from './Icon';
import { DEPARTMENT_PRESETS, ROLES, emptySeatPlanRow } from '@/lib/packages';

export default function SeatPlanBuilder({ rows, onChange }) {
  const total = rows.reduce((s, r) => s + (Number(r.count) || 0), 0);

  const update = (idx, patch) => {
    onChange(rows.map((r, i) => (i === idx ? { ...r, ...patch } : r)));
  };

  const addRow = () => onChange([...rows, emptySeatPlanRow()]);

  const removeRow = (idx) => {
    if (rows.length <= 1) return;
    onChange(rows.filter((_, i) => i !== idx));
  };

  return (
    <div className="seat-plan">
      <p className="seat-plan-hint">
        برای هر نقش یا واحدی که قرار است از سامانه استفاده کند یک ردیف اضافه کنید.
        زیر هر ردیف بنویسید این افراد برای چه کاری به دسترسی نیاز دارند.
      </p>
      {rows.map((row, idx) => (
        <div key={idx} className="seat-plan-row glass">
          <div className="seat-plan-row-head">
            <span className="seat-plan-num">{idx + 1}</span>
            {rows.length > 1 && (
              <button type="button" className="btn seat-plan-remove" onClick={() => removeRow(idx)} aria-label="حذف">
                ×
              </button>
            )}
          </div>
          <div className="pform-grid seat-plan-fields">
            <div className="field">
              <label>نقش سازمانی <span className="req-star">*</span></label>
              <select value={row.role} onChange={(e) => update(idx, { role: e.target.value })}>
                {ROLES.map((r) => (
                  <option key={r.id} value={r.id}>{r.label}</option>
                ))}
              </select>
            </div>
            <div className="field">
              <label>واحد / بخش <span className="req-star">*</span></label>
              <input
                list={`seat-dept-${idx}`}
                value={row.department}
                onChange={(e) => update(idx, { department: e.target.value })}
                placeholder="مثلاً گارانتی"
              />
              <datalist id={`seat-dept-${idx}`}>
                {DEPARTMENT_PRESETS.map((d) => <option key={d} value={d} />)}
              </datalist>
            </div>
            <div className="field">
              <label>تعداد کاربر <span className="req-star">*</span></label>
              <input
                type="number" inputMode="numeric" dir="ltr" min="1" max="1000"
                value={row.count}
                onChange={(e) => update(idx, { count: e.target.value })}
              />
            </div>
          </div>
          <div className="field seat-plan-note">
            <label>توضیح نیاز دسترسی</label>
            <textarea
              rows={2}
              value={row.note}
              onChange={(e) => update(idx, { note: e.target.value })}
              placeholder="مثلاً: فقط راهنمای تعمیرات و قطعات برای تعمیرگاه مرکزی"
            />
          </div>
        </div>
      ))}
      <button type="button" className="btn seat-plan-add" onClick={addRow}>
        <Icon name="gear" size={16} /> افزودن نقش / واحد
      </button>
      <div className="seat-plan-total">
        جمع صندلی‌های درخواستی: <b dir="ltr">{total || 0}</b>
      </div>
    </div>
  );
}

export { emptySeatPlanRow };
