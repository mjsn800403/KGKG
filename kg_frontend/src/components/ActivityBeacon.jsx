'use client';

import { useEffect, useRef } from 'react';
import { logActivity } from '../utils/api';

// Fire-and-forget usage signal for pages rendered by server components. The
// backend resolves a canonical content category from `segments`, so browsing a
// technical section (Engine / Body / Electrical …) shows up in analytics.
// Best-effort; never blocks or affects rendering. Deduped per action+key so a
// re-render / StrictMode double-invoke doesn't double-count.
const sent = new Set();

export default function ActivityBeacon({
  action, detail = '', segments = [], nodeTitle = '',
  appUrl = '', brand = '', year = '', model = '',
}) {
  const key = `${action}:${(segments || []).join('/')}:${nodeTitle}`;
  const fired = useRef(false);
  useEffect(() => {
    if (fired.current || sent.has(key)) return;
    fired.current = true;
    sent.add(key);
    // app_url + brand/model let the backend attach the activity to a car and
    // give the recommendation engine exact "continue reading" deep-links.
    logActivity(action, detail, {
      segments, node_title: nodeTitle,
      app_url: appUrl, brand, year, model,
    });
  }, [key, action, detail, segments, nodeTitle, appUrl, brand, year, model]);
  return null;
}
