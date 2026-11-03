'use client';

import { useState } from 'react';
import RequestsInbox from '../../components/RequestsInbox';
import SupportChatInbox from './SupportChatInbox';

// «میز پشتیبانی»: the existing ticket desk stays exactly as it was; the visitor
// conversations are a second tab beside it. Ticket state is not touched here.
export default function SupportDesk({ me = null }) {
  const [tab, setTab] = useState('tickets');
  return (
    <div className="scx-desk">
      <div className="scx-tabs" role="tablist" aria-label="میز پشتیبانی">
        <button type="button" role="tab" aria-selected={tab === 'tickets'} className={tab === 'tickets' ? 'is-on' : ''} onClick={() => setTab('tickets')}>تیکت‌ها</button>
        <button type="button" role="tab" aria-selected={tab === 'chats'} className={tab === 'chats' ? 'is-on' : ''} onClick={() => setTab('chats')}>گفتگوهای زنده</button>
      </div>
      {tab === 'tickets' ? <RequestsInbox /> : <SupportChatInbox me={me} />}
    </div>
  );
}
