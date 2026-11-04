# 09 — Real-time Events (SSE)

## 9.1 Why database-backed SSE

*(Written when the main database was SQLite; since 2026-10-29 it is PostgreSQL `kgkg` and the design is unchanged.)*

The app is several gunicorn worker processes + a detached pipeline worker, with no Redis.
The one medium every process can write to and tail durably is the main database.
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

**Current emitters** (event types found as literal `emit*` calls in `KG_backend/api`, 2026-11-04 **[C]**): pipeline worker
(`pipeline.progress` throttled + terminal states) and pipeline start/resume/cancel (`pipeline.started|resumed|canceled`), alerts
(`alert.opened`, `alert.resolved`), login + activity beacons (portal), company requests / support desk (`request.created|updated|reopened|rated|message`,
both audiences where relevant), product feedback (`feedback.created`), recommendations refresh (`rec.updated`), support chat
(`support_chat.message|updated|reopened`), change detector (`data.detected`, `processing.pending`). *Historical:* the `team.member.*` and
`team.role.*` events of the removed team CRUD are no longer emitted (`team._emit_team` has no caller).

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
connection status. The connector itself is `src/utils/eventStreamConnector.js` (environment
injected, unit-tested): silence for 45 s (three missed heartbeats) tears the stream down and reopens
it; failed attempts back off 3, 6, 12 s... capped at 60 s with +/-25% jitter and reset after a
successful open; the browser's `online` event reconnects at once; a 401 reports `unauthorized`
and stops. The support inbox shows a notice while live updates are down and keeps its 20 s refresh.
Consumers:

- **AdminDashboard** — KPIs, live processing progress bars, new requests, alerts, activity
  and event ticker.
- **RequestsInbox** (admin) / **RequestsView** (manager) — request lifecycle both ways,
  toast on completion, no reload.
- **SupportChatInbox** (`support-chat/admin/`) — `support_chat.*` events for the staff inbox, with the shared connector and a 20 s refresh fallback; **RecommendationsWidget** — `rec.updated`. *(The former `TeamView` consumer of `team.*` events was removed with the team CRUD.)*
- **kgkg-detect.timer** (30s `realtime_tick`) diffs the pending-work fingerprint so "new
  data landed" appears on the admin dashboard without anyone clicking refresh.

## 9.5 Adding a new event type

1. Pick a dotted name (`area.action`) and the narrowest audience.
2. Emit from the backend at the state change (inside try/except — best-effort).
3. Handle in the consumer via `useEventStream` (`onEvent` switch on `type`).
4. Document it here and in `docs/CHANGELOG.md`.
