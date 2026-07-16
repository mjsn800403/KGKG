'use client';

import { useEffect, useMemo, useState } from 'react';
import Icon from '../components/Icon';
import { pickHint } from './hintRules';
import { hintDismissed, dismissHint, hintShownCount, bumpHintShown } from './storage';

// Renders AT MOST ONE contextual hint at a time — a small, calm card anchored
// bottom-inline-start (just above the help button). Never modal, never blocks
// input. The user can act on it or dismiss it; dismissals persist (with an
// optional cooldown so a still-relevant hint can return later, but not nag).
export default function HintLayer({ audience, pathname, section, signals, onOpenHelp, onStartTour }) {
  const [dismissTick, setDismissTick] = useState(0); // force re-eval after dismiss
  const [closing, setClosing] = useState(false);

  const ctx = useMemo(
    () => ({ audience, pathname, section, signals, portalUser: null }),
    [audience, pathname, section, signals],
  );

  const hint = useMemo(
    () => pickHint(ctx, { isDismissed: hintDismissed, shownCount: hintShownCount }),
    [ctx, dismissTick],
  );

  // Count a display once per (hint, mount-of-that-hint).
  useEffect(() => {
    if (hint) { bumpHintShown(hint.id); setClosing(false); }
  }, [hint?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!hint) return null;

  const close = (cooldownOverride) => {
    dismissHint(hint.id, cooldownOverride != null ? cooldownOverride : (hint.cooldownMs || 0));
    setClosing(true);
    // let the exit transition play, then re-evaluate
    setTimeout(() => setDismissTick((t) => t + 1), 180);
  };

  const act = () => {
    const a = hint.action;
    if (!a) { close(); return; }
    if (a.kind === 'help' && a.article) { onOpenHelp(a.article); close(); }
    else if (a.kind === 'tour' && a.tour) { onStartTour(a.tour); close(); }
    else if (a.kind === 'link' && a.href) {
      close();
      try { window.location.assign(a.href); } catch { /* ignore */ }
    } else { close(); }
  };

  return (
    <div className={`guide-hint sev-${hint.severity}${closing ? ' closing' : ''}`} role="status" aria-live="polite">
      <div className="guide-hint-ico"><Icon name={hint.severity === 'warn' ? 'info' : 'sparkles'} /></div>
      <div className="guide-hint-main">
        <div className="guide-hint-title">{hint.title}</div>
        <div className="guide-hint-body">{hint.body}</div>
        <div className="guide-hint-actions">
          <button type="button" className="guide-hint-act" onClick={act}>
            {hint.action?.label || 'باشه'}
          </button>
          {hint.action?.kind !== 'dismiss' && (
            <button type="button" className="guide-hint-later" onClick={() => close()}>بعداً</button>
          )}
        </div>
      </div>
      <button type="button" className="guide-hint-x" aria-label="بستن" onClick={() => close()}>
        <Icon name="x" />
      </button>
    </div>
  );
}
