'use client';

import { useEffect, useState } from 'react';
import Icon from './Icon';

// Applies + persists the theme. The <head> boot script (layout.tsx) has already
// set data-theme from localStorage before paint; here we just mirror that state
// and keep every open toggle in sync via the kg:theme event.
export function applyTheme(next) {
  document.documentElement.setAttribute('data-theme', next);
  try { localStorage.setItem('kg-theme', next); } catch { /* private mode */ }
  window.dispatchEvent(new CustomEvent('kg:theme', { detail: next }));
}

export default function ThemeToggle() {
  const [theme, setTheme] = useState('dark');

  useEffect(() => {
    setTheme(document.documentElement.getAttribute('data-theme') || 'dark');
    const onTheme = (e) => setTheme(e.detail);
    window.addEventListener('kg:theme', onTheme);
    return () => window.removeEventListener('kg:theme', onTheme);
  }, []);

  function toggle() {
    const next = theme === 'dark' ? 'light' : 'dark';
    applyTheme(next);
  }

  return (
    <div className="theme-toggle" onClick={toggle} title="تغییر حالت روشن/تاریک" role="button" aria-label="تغییر تم">
      <Icon name={theme === 'dark' ? 'sun' : 'moon'} />
    </div>
  );
}
