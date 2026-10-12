'use client';

import { useState } from 'react';

// Uncontrolled by default (local state seeded from `on`); pass `checked` +
// `onChange` to control it from the parent (settings page persists to storage).
export default function Switch({ on = false, checked, onChange }) {
  const [v, setV] = useState(on);
  const controlled = typeof checked === 'boolean';
  const value = controlled ? checked : v;
  const toggle = () => {
    const next = !value;
    if (!controlled) setV(next);
    onChange?.(next);
  };
  return (
    <div className={`switch${value ? ' on' : ''}`} onClick={toggle} role="switch" aria-checked={value}>
      <i></i>
    </div>
  );
}
