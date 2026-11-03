// Pure conversation state for the widget. Components dispatch events; nothing
// here touches the network, storage or the clock.
//
// A message is {key, id?, clientId?, kind, body, at, delivery}:
//   kind      'visitor' | 'staff' | 'system'   (server author_kind 'admin' -> 'staff')
//   delivery  'sending' | 'sent' | 'read' | 'failed'   (visitor messages only)
// Server messages are keyed by id, optimistic ones by clientId; when the server
// confirms an optimistic message the two merge, so a double delivery of the same
// client_id can never show twice.

export const initialState = () => ({
  phase: 'welcome',           // welcome | chat | closed | gone
  threadId: null,
  messages: [],
  lastId: 0,                  // highest server message id seen (the poll cursor)
  mode: 'async',
  status: 'open',
  staffSeenAt: null,
  canReopen: false,
  fellBack: false,            // live, but the first message went unanswered
  rated: false,
  unread: 0,                  // staff replies arrived while the panel was closed
  panelOpen: false,
  intent: 'other',
});

const kindOf = (authorKind) => (authorKind === 'admin' ? 'staff' : authorKind === 'system' ? 'system' : 'visitor');

function fromServer(m) {
  return {
    key: `s${m.id}`, id: m.id, kind: kindOf(m.author_kind), body: m.body, at: m.created_at,
    delivery: m.author_kind === 'visitor' ? 'sent' : undefined,
  };
}

function merge(state, serverMessages) {
  const byKey = new Map(state.messages.map((m) => [m.key, m]));
  let lastId = state.lastId;
  let arrived = 0;
  for (const raw of serverMessages) {
    if (raw.id <= lastId && byKey.has(`s${raw.id}`)) continue;
    const incoming = fromServer(raw);
    if (incoming.kind === 'staff' || incoming.kind === 'system') arrived += incoming.kind === 'staff' ? 1 : 0;
    // The optimistic twin: a visitor message not yet carrying a server id and
    // with identical text is replaced rather than duplicated.
    if (incoming.kind === 'visitor') {
      const twin = state.messages.find((m) => m.kind === 'visitor' && m.id === undefined
        && m.body === incoming.body && m.delivery !== 'failed');
      if (twin) byKey.delete(twin.key);
    }
    byKey.set(incoming.key, incoming);
    lastId = Math.max(lastId, raw.id);
  }
  const messages = [...byKey.values()].sort((a, b) => (a.id ?? Infinity) - (b.id ?? Infinity)
    || String(a.at).localeCompare(String(b.at)));
  return { messages, lastId, arrived };
}

/** Delivery of a visitor message given when staff last opened the thread. */
export function deliveryOf(message, staffSeenAt) {
  if (message.kind !== 'visitor') return undefined;
  if (message.delivery === 'sending' || message.delivery === 'failed') return message.delivery;
  if (staffSeenAt && message.at && new Date(staffSeenAt) >= new Date(message.at)) return 'read';
  return 'sent';
}

export function reduce(state, event) {
  switch (event.type) {
    case 'restore':          // thread found in this browser
      return { ...state, phase: 'chat', threadId: event.threadId, intent: event.intent || state.intent };
    case 'panel': {
      const open = !!event.open;
      return { ...state, panelOpen: open, unread: open ? 0 : state.unread };
    }
    case 'intent':
      return { ...state, intent: event.intent };
    case 'send_start': {
      if (state.messages.some((m) => m.clientId === event.clientId)) {
        return { ...state, messages: state.messages.map((m) => (m.clientId === event.clientId
          ? { ...m, delivery: 'sending' } : m)) };
      }
      const m = { key: `c${event.clientId}`, clientId: event.clientId, kind: 'visitor',
        body: event.body, at: event.at, delivery: 'sending' };
      return { ...state, fellBack: false, messages: [...state.messages, m] };
    }
    case 'send_ok': {
      const next = merge({ ...state, messages: state.messages.filter((m) => m.clientId !== event.clientId) },
        [event.message]);
      return { ...state, ...next, phase: state.phase === 'welcome' ? 'chat' : state.phase,
        threadId: event.threadId || state.threadId, status: 'waiting_staff' };
    }
    case 'send_fail':
      return { ...state, messages: state.messages.map((m) => (m.clientId === event.clientId
        ? { ...m, delivery: 'failed' } : m)) };
    case 'created':
      return { ...state, phase: 'chat', threadId: event.threadId, mode: event.mode || state.mode };
    case 'poll': {
      const { messages, lastId, arrived } = merge(state, event.messages || []);
      const closed = event.status === 'closed';
      return {
        ...state, messages, lastId, status: event.status || state.status, mode: event.mode || state.mode,
        staffSeenAt: event.staffSeenAt ?? state.staffSeenAt, canReopen: !!event.canReopen,
        phase: closed ? 'closed' : (state.phase === 'closed' ? 'chat' : state.phase),
        unread: state.panelOpen ? 0 : state.unread + arrived,
        // A staff reply ends any "nobody answered yet" state.
        fellBack: arrived > 0 ? false : state.fellBack,
      };
    }
    case 'fell_back':
      return { ...state, fellBack: true };
    case 'rated':
      return { ...state, rated: true };
    case 'reopened':
      return { ...state, phase: 'chat', status: 'waiting_staff', rated: false };
    case 'gone':
      return { ...initialState(), phase: 'gone', panelOpen: state.panelOpen };
    case 'reset':
      return { ...initialState(), panelOpen: state.panelOpen };
    default:
      return state;
  }
}

/** True when the visitor spoke last and nobody on staff has answered since. */
export function awaitingReply(state) {
  const last = [...state.messages].reverse().find((m) => m.kind !== 'system');
  return !!last && last.kind === 'visitor';
}

/** The live-to-async fallback: live mode, an unanswered first message, N seconds passed. */
export function shouldFallBack({ mode, messages, firstSentAt, now, afterSeconds = 90, fellBack }) {
  if (mode !== 'live' || fellBack || !firstSentAt) return false;
  if (messages.some((m) => m.kind === 'staff')) return false;
  return now - firstSentAt >= afterSeconds * 1000;
}
