'use client';

import { useEffect, useRef, useState } from 'react';
import { openEventStream } from './api';
import { createSharedEventStream } from './sharedEventStream';

// One connection per audience per tab, however many components subscribe (see
// sharedEventStream.js). The connector itself (cursor resume, reconnect) is
// unchanged: openEventStream in api.jsx.
const shared = createSharedEventStream({ open: openEventStream });

/**
 * Subscribe to the server's real-time event stream.
 *
 *   const { status, last } = useEventStream({ admin: true, onEvent });
 *
 * `onEvent(evt)` fires for every delivered event ({ type, id, ts, payload }).
 * `status` is one of connecting | open | reconnecting | unauthorized. The
 * connection auto-reconnects (with cursor resume) until the last subscriber
 * unmounts. The latest event is also returned as `last` for components that
 * prefer to react declaratively rather than via the callback.
 */
export default function useEventStream({ admin = false, onEvent, enabled = true } = {}) {
  const [status, setStatus] = useState('idle');
  const [last, setLast] = useState(null);
  const cbRef = useRef(onEvent);
  useEffect(() => { cbRef.current = onEvent; });

  useEffect(() => {
    if (!enabled) return undefined;
    return shared.subscribe(admin, {
      onStatus: setStatus,
      onEvent: (evt) => {
        setLast(evt);
        try { cbRef.current?.(evt); } catch { /* handler error must not kill stream */ }
      },
    });
  }, [admin, enabled]);

  return { status, last };
}
