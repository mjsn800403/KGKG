'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { motion, AnimatePresence } from 'motion/react';
import Icon from './Icon';
import { fetchRecommendations } from '../utils/api';
import useEventStream from '../utils/useEventStream';

// Personalised, behaviour-driven suggestions for the logged-in user. Loads from
// /api/recommendations/ and quietly refreshes when the user's own activity
// stream ticks (they viewed something new -> "continue" / "related" shift).
export default function RecommendationsWidget() {
  const [rec, setRec] = useState(null);
  const [loaded, setLoaded] = useState(false);

  const load = () => fetchRecommendations(6).then((d) => { setRec(d); setLoaded(true); });
  useEffect(() => { load(); }, []);

  // Refresh (debounced) when this user's own activity is streamed back.
  useEventStream({
    admin: false,
    onEvent: (evt) => {
      if (evt.type === 'activity') {
        clearTimeout(window.__recTimer);
        window.__recTimer = setTimeout(load, 2500);
      }
    },
  });

  if (!loaded) return null;
  if (!rec) return null;

  const cont = rec.continue || [];
  const related = rec.related || [];
  const popular = rec.popular || [];
  const focus = rec.focus_areas?.areas || [];
  const focusSug = rec.focus_areas?.suggestions || [];
  const explore = rec.explore || [];

  // Nothing to show for a brand-new user -> render nothing (fleet grid is enough).
  if (!cont.length && !related.length && !popular.length && !focusSug.length && !explore.length) {
    return null;
  }

  const sections = [
    { key: 'continue', title: 'ادامه بدهید', icon: 'clock', items: cont, tone: 'accent' },
    { key: 'related', title: 'مرتبط با مطالعهٔ شما', icon: 'bot', items: related, tone: 'gold' },
    { key: 'focus', title: 'محبوب در حوزهٔ کاری شما', icon: 'chart', items: focusSug, tone: 'info' },
    { key: 'popular', title: 'پرکاربرد در شرکت شما', icon: 'users', items: popular, tone: 'info' },
  ].filter((s) => s.items.length > 0);

  return (
    <motion.section className="recs" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}>
      <div className="recs-head">
        <span className="eyebrow">پیشنهادهای هوشمند</span>
        {focus.length > 0 && (
          <div className="recs-chips">
            {focus.slice(0, 4).map((f) => (
              <span key={f.category} className="recs-chip">{f.label}<b>{(f.events || 0).toLocaleString('fa-IR')}</b></span>
            ))}
          </div>
        )}
      </div>

      <div className="recs-cols">
        {sections.map((s) => (
          <div key={s.key} className={`recs-col recs-${s.tone}`}>
            <h4 className="recs-col-title"><Icon name={s.icon} size={15} /> {s.title}</h4>
            <ul className="recs-list">
              <AnimatePresence initial={false}>
                {s.items.slice(0, 4).map((it, i) => (
                  <motion.li key={it.app_url || i} layout
                    initial={{ opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0 }}>
                    <Link href={it.app_url || '#'} className="recs-item">
                      <span className="recs-item-title">{it.title || it.car}</span>
                      <span className="recs-item-sub">
                        {it.car ? it.car : ''}
                        {it.category_label ? ` · ${it.category_label}` : ''}
                        {it.views ? ` · ${it.views.toLocaleString('fa-IR')} بازدید` : ''}
                        {it.peers ? ` · ${it.peers.toLocaleString('fa-IR')} همکار` : ''}
                      </span>
                      <span className="recs-go"><Icon name="back" size={13} /></span>
                    </Link>
                  </motion.li>
                ))}
              </AnimatePresence>
            </ul>
          </div>
        ))}
      </div>

      {explore.length > 0 && (
        <div className="recs-explore">
          <span className="recs-explore-label">خودروهای بازنشده:</span>
          {explore.slice(0, 5).map((e) => (
            <Link key={e.app_url} href={e.app_url} className="recs-explore-chip">{e.car}</Link>
          ))}
        </div>
      )}
    </motion.section>
  );
}
