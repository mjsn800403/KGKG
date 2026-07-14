'use client';

import { useEffect, useRef, useState } from 'react';
import { openEventStream } from './api';

/**
 * Subscribe to the server's real-time event stream.
 *
 *   const { status, last } = useEventStream({ admin: true, onEvent });
 *
 * `onEvent(evt)` fires for every delivered event ({ type, id, ts, payload }).
 * `status` is one of connecting | open | reconnecting | unauthorized. The
 * connection auto-reconnects (with cursor resume) until the component unmounts.
 * The latest event is also returned as `last` for components that prefer to
 * react declaratively rather than via the callback.
 */
export default function useEventStream({ admin = false, onEvent, enabled = true } = {}) {
  const [status, setStatus] = useState('idle');
  const [last, setLast] = useState(null);
  const cbRef = useRef(onEvent);
  cbRef.current = onEvent;

  useEffect(() => {
    if (!enabled) return undefined;
    const close = openEventStream({
      admin,
      onStatus: setStatus,
      onEvent: (evt) => {
        setLast(evt);
        try { cbRef.current?.(evt); } catch { /* handler error must not kill stream */ }
      },
    });
    return close;
  }, [admin, enabled]);

  return { status, last };
}
