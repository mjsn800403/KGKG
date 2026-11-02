'use client';

import { useEffect } from 'react';
import { reportSignal } from '../guidance/signals';

// A client island that lets a SERVER component report a guidance signal.
//
// The search results page is a server component, so it cannot call
// reportSignal itself. Rendering this where the page already knows something
// the hint rules care about — "this search found nothing" — keeps the
// knowledge at the place it is true, instead of re-deriving it on the client.
//
// Renders nothing.
export default function SignalReporter({ name, value }) {
  useEffect(() => {
    reportSignal(name, value);
  }, [name, value]);
  return null;
}
