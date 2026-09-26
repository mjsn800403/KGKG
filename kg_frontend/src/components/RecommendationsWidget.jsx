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
//
// The warehouse holds navigation stubs as real nodes, so the raw feed offers
// entries like «"D"» or «External Pages», and the same procedure repeats once
// per vehicle. Both are filtered here: a suggestion has to name something a
// technician would recognise, and repeats collapse into one row that says how
// many vehicles share it.

// Titles that are structure, not content.
const JUNK_TITLE = /^(external pages?|other variants?|untitled|page|index|contents?|misc)$/i;

function isUseful(item) {
  const title = String(item?.title || item?.car || '').replace(/["'“”«»]/g, '').trim();
  if (title.length < 4) return false;              // «"D"», «A/C», single letters
  if (JUNK_TITLE.test(title)) return false;
  return true;
}

// One row per procedure: the first vehicle keeps the link, the rest become a
// count so four identical "Anti-Lock Brakes" rows read as one.
function collapse(items) {
  const byTitle = new Map();
  items.filter(isUseful).forEach((it) => {
    const key = String(it.title || it.car).trim().toLowerCase();
    const seen = byTitle.get(key);
    if (seen) { seen.alsoCars = (seen.alsoCars || 0) + 1; return; }
    byTitle.set(key, { ...it });
  });
  return [...byTitle.values()];
}
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

  const cont = collapse(rec.continue || []);
  const related = collapse(rec.related || []);
  const popular = collapse(rec.popular || []);
  const focus = rec.focus_areas?.areas || [];
  const focusSug = collapse(rec.focus_areas?.suggestions || []);
  const explore = (rec.explore || []).filter(isUseful);

  // Nothing to show for a brand-new user -> render nothing (fleet grid is enough).
  if (!cont.length && !related.length && !popular.length && !focusSug.length && !explore.length) {
    return null;
  }

  const sections = [
    { key: 'continue', title: 'ادامه بدهید', icon: 'clock', items: cont, tone: 'accent' },
    { key: 'related', title: 'مرتبط با مطالعهٔ شما', icon: 'bot', items: related, tone: 'info' },
    { key: 'focus', title: 'محبوب در حوزهٔ کاری شما', icon: 'chart', items: focusSug, tone: 'info' },
    { key: 'popular', title: 'پرکاربرد در شرکت شما', icon: 'users', items: popular, tone: 'info' },
  ].filter((s) => s.items.length > 0);

  return (
    <motion.section className="recs" data-guide="recs" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}
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
                        {it.alsoCars ? ` · و ${it.alsoCars.toLocaleString('fa-IR')} خودروی دیگر` : ''}
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
