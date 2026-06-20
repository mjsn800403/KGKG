'use client';

import { useState } from 'react';

export default function Switch({ on = false }) {
  const [v, setV] = useState(on);
  return (
    <div className={`switch${v ? ' on' : ''}`} onClick={() => setV((x) => !x)}>
      <i></i>
    </div>
  );
}
