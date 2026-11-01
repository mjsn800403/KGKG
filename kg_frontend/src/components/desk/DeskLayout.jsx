'use client';

import { useEffect, useRef } from 'react';
import Icon from '../Icon';

// Two panes above 860px; a stack below it, where the conversation covers the
// list and a back control returns. One component owns that decision so the
// customer view and the desk inbox cannot drift apart on small screens.
//
// The narrow case is handled with a class rather than a width measurement:
// rendering different trees either side of a breakpoint means the first paint
// after hydration can be the wrong one.

export default function DeskLayout({
  listPane, conversationPane, hasSelection, onBack, listLabel = 'تیکت‌ها',
}) {
  const backRef = useRef(null);

  // Esc returns to the list on a narrow screen. Harmless on a wide one, where
  // both panes are visible and `onBack` only clears the selection.
  useEffect(() => {
    if (!hasSelection) return undefined;
    const onKey = (e) => {
      const t = e.target;
      const typing = t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable);
      if (e.key === 'Escape' && !typing) onBack?.();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [hasSelection, onBack]);

  // Moving focus to the back control is what makes the stacked view usable by
  // keyboard: without it, focus stays on a row that is now off-screen.
  useEffect(() => {
    if (hasSelection) backRef.current?.focus({ preventScroll: true });
  }, [hasSelection]);

  return (
    <div className={`dk${hasSelection ? ' dk-on-conv' : ''}`}>
      <section className="dk-list" aria-label={listLabel}>
        {listPane}
      </section>
      <section className="dk-conv" aria-label="گفت‌وگو">
        <button ref={backRef} type="button" className="dk-back" onClick={() => onBack?.()}>
          <Icon name="chevron" size={16} /> بازگشت به فهرست
        </button>
        {conversationPane}
      </section>
    </div>
  );
}
