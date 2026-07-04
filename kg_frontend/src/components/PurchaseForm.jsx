'use client';

import { useMemo, useState } from 'react';
import Icon from './Icon';
import { showModal } from './Modal';
import { submitPurchaseRequest } from '../utils/api';

// Documentation types the buyer can request. `id` is what we store; `label` is
// the Persian UI text. Mirrors the four coverage layers on the landing page,
// plus a "full spec" option.
const DOC_TYPES = [
  { id: 'parts', label: 'فهرست قطعات', icon: 'parts' },
  { id: 'manual', label: 'منوال تعمیر', icon: 'manual' },
  { id: 'standard_time', label: 'زمان استاندارد تعمیراتی', icon: 'clock' },
  { id: 'special_tools', label: 'ابزار مخصوص تعمیراتی', icon: 'wrench' },
  { id: 'full_spec', label: 'مشخصات کامل خودرو', icon: 'catalog' },
];

// Purchase request form. `cars` (the live catalog) only powers typeahead
// suggestions — the buyer may request docs for a vehicle not yet in the system,
// so brand/model stay free-text with a datalist rather than a locked <select>.
export default function PurchaseForm({ cars }) {
  const catalog = Array.isArray(cars) ? cars : [];
  const [form, setForm] = useState({
    brand: '', model: '', year: '',
    company: '', landline: '', mobile: '', reg_no: '', note: '',
    employees_count: '', seats_count: '',
  });
  const [docs, setDocs] = useState([]);
  const [wantsDemo, setWantsDemo] = useState(false);
  const [wantsAI, setWantsAI] = useState(false);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const brands = useMemo(
    () => [...new Set(catalog.map((c) => c.brand_name).filter(Boolean))].sort(),
    [catalog]
  );
  const models = useMemo(() => {
    const pool = form.brand
      ? catalog.filter((c) => c.brand_name === form.brand)
      : catalog;
    return [...new Set(pool.map((c) => c.car_name).filter(Boolean))].sort();
  }, [catalog, form.brand]);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const toggleDoc = (id) =>
    setDocs((d) => (d.includes(id) ? d.filter((x) => x !== id) : [...d, id]));

  async function submit(e) {
    e.preventDefault();
    if (submitting) return;
    setError('');

    // Validation — brand/model/year + at least one document + full legal contact.
    if (!form.brand.trim() || !form.model.trim() || !String(form.year).trim()) {
      setError('لطفاً برند، مدل و سال خودرو را کامل وارد کنید.');
      return;
    }
    if (!docs.length) {
      setError('حداقل یک نوع مستند را انتخاب کنید.');
      return;
    }
    if (!form.company.trim() || !form.landline.trim() || !form.mobile.trim() || !form.reg_no.trim()) {
      setError('برای اشخاص حقوقی، نام شرکت، تلفن ثابت، تلفن همراه و شماره ثبتی الزامی است.');
      return;
    }
    if (!String(form.employees_count).trim() || !String(form.seats_count).trim()) {
      setError('تعداد پرسنل شرکت و تعداد کاربران مورد نیاز را وارد کنید.');
      return;
    }

    setSubmitting(true);
    try {
      await submitPurchaseRequest({
        brand: form.brand.trim(),
        model: form.model.trim(),
        year: String(form.year).trim(),
        documents: docs,
        company: form.company.trim(),
        landline: form.landline.trim(),
        mobile: form.mobile.trim(),
        reg_no: form.reg_no.trim(),
        note: form.note.trim(),
        employees_count: Number(form.employees_count) || null,
        seats_count: Number(form.seats_count) || null,
        wants_demo: wantsDemo,
        wants_ai_assistant: wantsAI,
      });
      showModal(
        'درخواست شما ثبت شد',
        'کارشناسان ما در اولین فرصت با شما تماس خواهند گرفت. از اعتماد شما سپاسگزاریم.',
        '✓'
      );
      setForm({ brand: '', model: '', year: '', company: '', landline: '', mobile: '', reg_no: '', note: '', employees_count: '', seats_count: '' });
      setDocs([]);
      setWantsDemo(false);
      setWantsAI(false);
    } catch (err) {
      setError(err.message || 'ثبت درخواست ناموفق بود. کمی بعد دوباره تلاش کنید.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="pform" onSubmit={submit} noValidate>
      <div className="pform-note">
        <Icon name="info" />
        <span>
          مستندات فنی خودرو <b>فقط به اشخاص حقوقی</b> عرضه می‌شود. لطفاً مشخصات خودرو،
          مستندات مورد نیاز و اطلاعات تماس شرکت را کامل کنید تا کارشناسان ما با شما تماس بگیرند.
        </span>
      </div>

      <div className="pform-section">مشخصات خودرو</div>
      <div className="pform-grid">
        <div className="field">
          <label>برند <span className="req-star">*</span></label>
          <input
            list="pf-brands" value={form.brand} onChange={set('brand')}
            placeholder="مثلاً Toyota"
          />
          <datalist id="pf-brands">
            {brands.map((b) => <option key={b} value={b} />)}
          </datalist>
        </div>
        <div className="field">
          <label>مدل <span className="req-star">*</span></label>
          <input
            list="pf-models" value={form.model} onChange={set('model')}
            placeholder="مثلاً bZ4X یا Land Cruiser"
          />
          <datalist id="pf-models">
            {models.map((m) => <option key={m} value={m} />)}
          </datalist>
        </div>
        <div className="field">
          <label>سال <span className="req-star">*</span></label>
          <input
            type="number" inputMode="numeric" dir="ltr" value={form.year}
            onChange={set('year')} placeholder="مثلاً 2023" min="1980" max="2100"
          />
        </div>
      </div>

      <div className="pform-section">مستندات مورد نیاز <span className="req-star">*</span></div>
      <div className="doc-chips">
        {DOC_TYPES.map((d) => {
          const active = docs.includes(d.id);
          return (
            <button
              type="button" key={d.id}
              className={`doc-chip${active ? ' active' : ''}`}
              onClick={() => toggleDoc(d.id)}
              aria-pressed={active}
            >
              <span className="tick">✓</span>
              <Icon name={d.icon} size={16} />
              {d.label}
            </button>
          );
        })}
      </div>

      <div className="pform-section">اطلاعات تماس (شخص حقوقی)</div>
      <div className="pform-grid">
        <div className="field">
          <label>نام شرکت <span className="req-star">*</span></label>
          <input value={form.company} onChange={set('company')} placeholder="نام کامل شرکت" />
        </div>
        <div className="field">
          <label>شماره ثبتی <span className="req-star">*</span></label>
          <input dir="ltr" value={form.reg_no} onChange={set('reg_no')} placeholder="شماره ثبت شرکت" />
        </div>
        <div className="field">
          <label>تلفن ثابت <span className="req-star">*</span></label>
          <input type="tel" dir="ltr" value={form.landline} onChange={set('landline')} placeholder="021-XXXXXXXX" />
        </div>
        <div className="field">
          <label>تلفن همراه <span className="req-star">*</span></label>
          <input type="tel" dir="ltr" value={form.mobile} onChange={set('mobile')} placeholder="09XXXXXXXXX" />
        </div>
      </div>

      <div className="pform-section">ابعاد سازمان و کاربران</div>
      <div className="pform-grid">
        <div className="field">
          <label>تعداد پرسنل شرکت <span className="req-star">*</span></label>
          <input
            type="number" inputMode="numeric" dir="ltr" min="1"
            value={form.employees_count} onChange={set('employees_count')}
            placeholder="مثلاً 120"
          />
        </div>
        <div className="field">
          <label>تعداد کاربران مورد نیاز (صندلی) <span className="req-star">*</span></label>
          <input
            type="number" inputMode="numeric" dir="ltr" min="1"
            value={form.seats_count} onChange={set('seats_count')}
            placeholder="مثلاً 5"
          />
        </div>
      </div>

      <div className="pform-section">گزینه‌های اختیاری</div>
      <div className="doc-chips">
        <button
          type="button"
          className={`doc-chip${wantsDemo ? ' active' : ''}`}
          onClick={() => setWantsDemo((v) => !v)}
          aria-pressed={wantsDemo}
        >
          <span className="tick">✓</span>
          <Icon name="info" size={16} />
          درخواست نسخه دمو (آزمایشی)
        </button>
        <button
          type="button"
          className={`doc-chip${wantsAI ? ' active' : ''}`}
          onClick={() => setWantsAI((v) => !v)}
          aria-pressed={wantsAI}
        >
          <span className="tick">✓</span>
          <Icon name="bot" size={16} />
          دستیار هوش مصنوعی (افزودنی)
        </button>
      </div>

      <div className="field">
        <label>توضیحات تکمیلی (اختیاری)</label>
        <textarea value={form.note} onChange={set('note')} placeholder="هر توضیح دیگری درباره خودرو یا مستندات مورد نیاز…" />
      </div>

      {error && <div className="pform-error">{error}</div>}

      <div className="pform-actions">
        <button className="btn btn-accent" type="submit" disabled={submitting}>
          {submitting ? 'در حال ثبت…' : 'ثبت درخواست خرید'}
        </button>
        <span style={{ color: 'var(--text-faint)', fontSize: '13px' }}>
          پس از ثبت، کارشناسان ما با شما تماس می‌گیرند.
        </span>
      </div>
    </form>
  );
}
