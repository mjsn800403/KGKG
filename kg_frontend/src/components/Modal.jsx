'use client';

import { useEffect, useState } from 'react';

// Global styled modal, identical markup to the prototype's #modalOverlay.
// Any component can open it by dispatching:
//   window.dispatchEvent(new CustomEvent('kg:modal',
//     { detail: { title, body, icon } }))
export function showModal(title, body, icon) {
  window.dispatchEvent(new CustomEvent('kg:modal', { detail: { title, body, icon } }));
}

export default function Modal() {
  const [data, setData] = useState(null);

  useEffect(() => {
    function onOpen(e) { setData(e.detail || {}); }
    window.addEventListener('kg:modal', onOpen);
    return () => window.removeEventListener('kg:modal', onOpen);
  }, []);

  const close = () => setData(null);

  return (
    <div
      className={`modal-overlay${data ? ' show' : ''}`}
      onClick={(e) => { if (e.target === e.currentTarget) close(); }}
    >
      <div className="modal-box glass">
        <span className="mclose" onClick={close}>✕</span>
        <div className="micon">{data?.icon || 'i'}</div>
        <h4>{data?.title}</h4>
        <p>{data?.body}</p>
        <button className="btn btn-accent full" onClick={close}>متوجه شدم</button>
      </div>
    </div>
  );
}
