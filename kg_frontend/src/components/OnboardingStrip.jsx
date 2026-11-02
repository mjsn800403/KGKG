'use client';

import { useCallback, useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import Link from 'next/link';
import Icon from './Icon';
import { onboardingApi } from '../utils/api';
import { nextItem, progressLabel, shouldShowStrip } from '../lib/onboarding';

// "What else is here" — one collapsed line on the fleet page.
//
// Measured on production over four months: the parts catalogue had been opened
// by 6 of 34 active seats, the assistant asked by 9, the search box used by
// nobody, against 71,886 manual views. People found the manuals and stopped
// looking. The tour at first login is not the fix — all of them saw one; the
// moment that matters is three weeks later, mid-task.
//
// Rules this component obeys, in order of importance:
//   * it never blocks. No modal, no overlay, no layout shift when absent.
//   * every item is EARNED. There is no "mark as done" — the server decides
//     from what the person actually did, so the list cannot be gamed and is
//     truthful for seats that have used the product for months.
//   * dismissed means gone. The server remembers, so it does not return on
//     another device, and a thing that returns after you closed it is a nag.

export default function OnboardingStrip() {
  const [payload, setPayload] = useState(null);
  const [open, setOpen] = useState(false);
  const [hidden, setHidden] = useState(false);

  const load = useCallback(() => {
    onboardingApi.get()
      .then(setPayload)
      .catch(() => setPayload(null));   // enhancement only: never break the page
  }, []);
  useEffect(() => { load(); }, [load]);

  const dismiss = async () => {
    setHidden(true);
    try { await onboardingApi.dismiss(); } catch { /* it is hidden either way */ }
  };

  if (hidden || !shouldShowStrip(payload)) return null;
  const next = nextItem(payload);

  return (
    <motion.section
      className="onb glass"
      aria-label="قدم‌های شروع کار"
      initial={{ opacity: 0, y: -6 }}
      animate={{ opacity: 1, y: 0 }}
    >
      <div className="onb-line">
        <span className="onb-count">{progressLabel(payload.done, payload.total)}</span>
        {/* An item that lives inside a vehicle has no href: linking it back
            to /browse, the page this strip is rendered on, would be a pointer
            at itself. Its copy says where to go instead. */}
        {next && !open && (next.href ? (
          <Link className="onb-next" href={next.href}>
            <Icon name="sparkles" size={14} /> {next.title}
          </Link>
        ) : (
          <span className="onb-next onb-next-static">
            <Icon name="sparkles" size={14} /> {next.title}
          </span>
        ))}
        <button
          type="button"
          className="onb-toggle"
          aria-expanded={open}
          onClick={() => setOpen((o) => !o)}
        >
          {open ? 'بستن' : 'همهٔ قدم‌ها'}
          <Icon name="chevron" size={14} className={open ? 'onb-chev up' : 'onb-chev'} />
        </button>
        <button type="button" className="onb-dismiss" onClick={dismiss}
          aria-label="دیگر نشان نده">
          <Icon name="x" size={14} />
        </button>
      </div>

      <AnimatePresence>
        {open && (
          <motion.ul className="onb-items"
            initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }} style={{ overflow: 'hidden' }}>
            {payload.items.map((i) => (
              <li key={i.id} className={`onb-item${i.done ? ' done' : ''}`}>
                <span className="onb-mark" aria-hidden="true">
                  {i.done ? <Icon name="check" size={14} /> : <span className="onb-dot" />}
                </span>
                <span className="onb-text">
                  {i.done || !i.href ? (
                    <b>{i.title}</b>
                  ) : (
                    <Link href={i.href}><b>{i.title}</b></Link>
                  )}
                  <span className="onb-why">{i.why}</span>
                </span>
                {i.done && <span className="onb-done-tag">انجام شد</span>}
              </li>
            ))}
          </motion.ul>
        )}
      </AnimatePresence>
    </motion.section>
  );
}
