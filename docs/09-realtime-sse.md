# 09 — Real-time Events (SSE)

## 9.1 Why SQLite-backed SSE

The app is several gunicorn worker processes + a detached pipeline worker, with no Redis.
The one medium every process can write to and tail durably is the main SQLite DB (WAL).
So the real-time layer is: append-only `Event` table → SSE endpoint tails it → dashboards
update live. This gives durability and `Last-Event-ID` resume for free; the trade-off is a
1s tail latency, which is fine for dashboards. If fan-out ever outgrows it, only the
tailing implementation changes — the wire protocol stays.

## 9.2 Emitting

```python
from api import events
events.emit(type, payload, audience='admin')          # admins
events.emit_company(type, company_id, payload)        # company dashboards
events.emit_user(type, user_id, payload)              # one user
```
Best-effort (never raises into the request path). Table auto-trims to ~20k rows, amortized
(every ~500th emit).

**Current emitters:** pipeline worker (`pipeline.progress` throttled + terminal states),
pipeline start/resume/cancel (adminops), alerts raise/resolve (monitoring), login +
activity beacons (portal), team changes (`team.member.added/updated`,
`team.role.created/updated/deleted/reordered`), company requests
(`request.created/updated` → both audiences), change detector (`data.detected`,
`processing.pending`).

## 9.3 The stream (`/api/events/stream/`)

- Auth: admin token (`?admin=1`) or portal token; portal users get `user`-audience events,
  plus `company`-audience if `can_manage_team` or `can_view_analytics`
  (`portal_auth.user_can_view_company_stream`).
- Protocol: standard SSE frames (`id:`, `event:`, `data:` JSON `{id,type,ts,payload}`),
  heartbeat comment every 15s, stream recycles after 300s (clients reconnect with the
  cursor), resume via `Last-Event-ID` header or `?after=`.
- 1s DB tail loop. REST companion `/api/events/recent/?after=` for catch-up/polling.
- **nginx:** the exact location `/kg-api/api/events/stream/` has `proxy_buffering off` +
  3600s read timeout — without it events sit in nginx's buffer. Don't remove it; add
  equivalent config for any new streaming endpoint.
- gunicorn runs `--threads 8 --timeout 300` partly to hold these long-lived connections;
  every concurrent stream occupies a thread. Envelope: fine for tens of dashboards, not
  thousands.

## 9.4 Frontend consumption

`src/utils/useEventStream.js` — fetch-based SSE reader (native EventSource can't send the
Bearer header): parses frames, tracks the cursor, auto-reconnects with backoff, exposes
connection status. Consumers:

- **AdminDashboard** — KPIs, live processing progress bars, new requests, alerts, activity
  and event ticker.
- **RequestsInbox** (admin) / **RequestsView** (manager) — request lifecycle both ways,
  toast on completion, no reload.
- **TeamView** — `team.*` events → debounced reload (cross-tab and cross-user sync).
- **kgkg-detect.timer** (30s `realtime_tick`) diffs the pending-work fingerprint so "new
  data landed" appears on the admin dashboard without anyone clicking refresh.

## 9.5 Adding a new event type

1. Pick a dotted name (`area.action`) and the narrowest audience.
2. Emit from the backend at the state change (inside try/except — best-effort).
3. Handle in the consumer via `useEventStream` (`onEvent` switch on `type`).
4. Document it here and in `docs/CHANGELOG.md`.
