'use client';

import { useEffect, useState } from 'react';

export default function ThemeToggle() {
  const [theme, setTheme] = useState('dark');

  useEffect(() => {
    const stored = localStorage.getItem('kg-theme') || 'dark';
    document.documentElement.setAttribute('data-theme', stored);
    setTheme(stored);
  }, []);

  function toggle() {
    const next = theme === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('kg-theme', next);
    setTheme(next);
  }

  return (
    <div className="theme-toggle" onClick={toggle} title="Toggle theme">
      {theme === 'dark' ? '◐' : '◑'}
    </div>
  );
}
