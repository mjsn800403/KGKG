'use client';

import { useEffect, useRef } from 'react';
import Link from 'next/link';
import Icon from './Icon';

// Renders a doc-grid of cards with the prototype's staggered "explode" reveal.
// items: [{ href, icon: <Icon name>, title, go }]
export default function CardGrid({ items }) {
  const gridRef = useRef(null);

  useEffect(() => {
    const cards = gridRef.current ? gridRef.current.querySelectorAll('.doc-card') : [];
    cards.forEach((c) => c.classList.remove('show'));
    cards.forEach((c, i) => setTimeout(() => c.classList.add('show'), 90 * i));
  }, [items]);

  if (!items || items.length === 0) {
    return <div className="empty-state">موردی در این بخش یافت نشد.</div>;
  }

  return (
    <div className="doc-grid" ref={gridRef}>
      {items.map((it) => (
        <Link key={it.href} href={it.href} className="doc-card explode glass">
          <div className="icon"><Icon name={it.icon} /></div>
          <div>
            <h4>{it.title}</h4>
            {it.sub && <div className="doc-card-sub" dir="ltr">{it.sub}</div>}
          </div>
          <div className="go">{it.go || 'ورود به مستند ←'}</div>
        </Link>
      ))}
    </div>
  );
}
