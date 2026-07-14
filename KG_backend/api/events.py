"""Real-time event backbone: emit → append-only log → SSE fan-out.

The pieces:
  * ``emit(...)``        — append one Event row (best-effort; never raises into
                            the caller's request path).
  * ``events_since(...)``— tail the log for a viewer's scope past a cursor.
  * ``stream_view``      — an SSE endpoint that long-holds the connection and
                            pushes new events as they land (~1s tail cadence),
                            with heartbeats and ``Last-Event-ID`` resume.
  * ``snapshot_pending``/``detect_and_emit`` — the "what still needs processing"
                            picture, emitted the moment it changes so the admin
                            dashboard shows newly-landed / unprocessed data live.

Multi-worker note: this deliberately goes through the shared SQLite DB (WAL) —
several gunicorn workers plus a detached pipeline worker all write/tail the same
table, which an in-process bus (or the per-process LocMemCache) could not do.
"""
import json
import time

from django.db import connection
from django.http import JsonResponse, StreamingHttpResponse
from django.utils import timezone

from .models import Event, SystemState


# ---------------------------------------------------------------------------
# Emit
# ---------------------------------------------------------------------------

# Keep the log bounded: newest N rows are plenty for resume + history panels.
_MAX_EVENTS = 20000
_TRIM_EVERY = 500          # amortised trim (only every Nth emit does the DELETE)
_emit_count = 0


def emit(type, payload=None, audience='admin', company_id=None, user_id=None):
    """Append one event. Returns the Event (or None on failure — emitting is a
    side channel and must never break the action that triggered it)."""
    global _emit_count
    try:
        ev = Event.objects.create(
            type=type, payload=payload or {}, audience=audience,
            company_id=company_id, user_id=user_id)
    except Exception:
        return None
    _emit_count += 1
    if _emit_count % _TRIM_EVERY == 0:
        _trim()
    return ev


def emit_company(type, company_id, payload=None, user_id=None):
    return emit(type, payload, audience='company', company_id=company_id, user_id=user_id)


def emit_user(type, user_id, payload=None, company_id=None):
    return emit(type, payload, audience='user', user_id=user_id, company_id=company_id)


def _trim():
    try:
        keep_from = (Event.objects.order_by('-id')
                     .values_list('id', flat=True)[_MAX_EVENTS:_MAX_EVENTS + 1])
        keep_from = list(keep_from)
        if keep_from:
            Event.objects.filter(id__lte=keep_from[0]).delete()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Tail (scoped)
# ---------------------------------------------------------------------------

def _scoped_qs(after_id, *, is_admin, company_id=None, user_id=None,
               can_see_company=False):
    """Events past ``after_id`` this viewer may receive.

    * admin        → every 'admin' and 'all' event (the platform view);
    * company mgr  → 'company' events for their company + their own 'user'
                     events + 'all';
    * plain user   → their own 'user' events + 'all'.
    """
    from django.db.models import Q
    qs = Event.objects.filter(id__gt=after_id)
    if is_admin:
        return qs.filter(audience__in=('admin', 'all')).order_by('id')
    scope = Q(audience='all')
    if user_id is not None:
        scope |= Q(audience='user', user_id=user_id)
    if can_see_company and company_id is not None:
        scope |= Q(audience='company', company_id=company_id)
    return qs.filter(scope).order_by('id')


def events_since(after_id, *, is_admin, company_id=None, user_id=None,
                 can_see_company=False, limit=200):
    rows = list(_scoped_qs(after_id, is_admin=is_admin, company_id=company_id,
                           user_id=user_id, can_see_company=can_see_company)[:limit])
    return rows


def _latest_id():
    row = Event.objects.order_by('-id').values_list('id', flat=True).first()
    return row or 0


# ---------------------------------------------------------------------------
# Auth resolution for the stream (Bearer header OR cookie; admin OR portal)
# ---------------------------------------------------------------------------

def _resolve_viewer(request):
    """Return a dict describing who is connecting, or None if unauthenticated.

    Admin is checked first (admin token in Authorization/X-Admin-Token or the
    KG_ADMIN_TOKEN env secret). Otherwise a portal user (Bearer or cookie)."""
    from .admin_auth import _presented_token, _configured_token, _admin_session_valid
    import hmac
    presented = _presented_token(request)
    configured = _configured_token()
    if presented and configured and hmac.compare_digest(presented, configured):
        return {'is_admin': True}
    if _admin_session_valid(presented):
        return {'is_admin': True}
    from .portal import portal_user
    from .portal_auth import user_can_view_company_stream
    u = portal_user(request)
    if u is not None:
        return {
            'is_admin': False,
            'user_id': u.id,
            'company_id': u.company_id,
            'can_see_company': user_can_view_company_stream(u),
        }
    return None


# ---------------------------------------------------------------------------
# SSE stream
# ---------------------------------------------------------------------------

# Tail cadence and lifetimes. A short tail keeps latency ~1s; capping the
# connection lifetime recycles the worker thread (the client's EventSource-style
# reader reconnects automatically with Last-Event-ID, so no events are missed).
_TAIL_INTERVAL_S = 1.0
_HEARTBEAT_S = 15.0
_MAX_STREAM_S = 300.0


def _sse_frame(ev):
    return f"id: {ev.id}\nevent: {ev.type}\ndata: {json.dumps(ev.to_sse())}\n\n"


def stream_view(request):
    """GET /api/events/stream/ — Server-Sent Events for the caller's scope.

    Resume: ``Last-Event-ID`` header or ``?after=<id>``. The very first frame is
    a ``ready`` comment carrying the current cursor so a fresh client can then
    fetch a REST snapshot and know exactly where the live tail begins."""
    viewer = _resolve_viewer(request)
    if viewer is None:
        return JsonResponse({'error': 'unauthorized'}, status=401)

    try:
        after = int(request.headers.get('Last-Event-ID')
                    or request.GET.get('after') or 0)
    except (TypeError, ValueError):
        after = 0
    if after <= 0:
        # A new subscriber starts at the live edge (history comes from REST).
        after = _latest_id()

    def gen():
        cursor = after
        started = time.monotonic()
        last_beat = started
        # Prime the pipe: flush headers immediately and tell the client the cursor.
        yield f": connected\nretry: 3000\n\n"
        yield f"event: ready\ndata: {json.dumps({'cursor': cursor})}\n\n"
        while True:
            now = time.monotonic()
            if now - started > _MAX_STREAM_S:
                # Ask the client to reconnect (EventSource does this on stream end).
                yield "event: reconnect\ndata: {}\n\n"
                return
            try:
                rows = events_since(
                    cursor, is_admin=viewer['is_admin'],
                    company_id=viewer.get('company_id'),
                    user_id=viewer.get('user_id'),
                    can_see_company=viewer.get('can_see_company', False),
                    limit=200)
            except Exception:
                rows = []
            if rows:
                for ev in rows:
                    yield _sse_frame(ev)
                    cursor = ev.id
                last_beat = now
            elif now - last_beat >= _HEARTBEAT_S:
                yield ": ping\n\n"        # comment frame keeps proxies from idling us out
                last_beat = now
            # Don't hold a SQLite connection open between polls (WAL readers are
            # cheap to reopen, and a long-held conn would pin the WAL).
            try:
                connection.close()
            except Exception:
                pass
            time.sleep(_TAIL_INTERVAL_S)

    resp = StreamingHttpResponse(gen(), content_type='text/event-stream')
    resp['Cache-Control'] = 'no-cache, no-transform'
    resp['X-Accel-Buffering'] = 'no'     # belt-and-suspenders vs nginx buffering
    resp['Connection'] = 'keep-alive'
    return resp


# ---------------------------------------------------------------------------
# REST companions (initial snapshot + recent history for a fresh dashboard)
# ---------------------------------------------------------------------------

def recent_view(request):
    """GET /api/events/recent/?after=&limit= — recent events for the scope, as
    JSON. The dashboard loads this once, then switches to the live stream."""
    viewer = _resolve_viewer(request)
    if viewer is None:
        return JsonResponse({'error': 'unauthorized'}, status=401)
    try:
        after = int(request.GET.get('after') or 0)
    except (TypeError, ValueError):
        after = 0
    try:
        limit = max(1, min(int(request.GET.get('limit') or 100), 500))
    except (TypeError, ValueError):
        limit = 100
    if after <= 0:
        # Most recent `limit`, returned oldest-first so the client can append.
        qs = _scoped_qs(0, is_admin=viewer['is_admin'],
                        company_id=viewer.get('company_id'),
                        user_id=viewer.get('user_id'),
                        can_see_company=viewer.get('can_see_company', False))
        rows = list(qs.order_by('-id')[:limit])[::-1]
    else:
        rows = events_since(after, is_admin=viewer['is_admin'],
                            company_id=viewer.get('company_id'),
                            user_id=viewer.get('user_id'),
                            can_see_company=viewer.get('can_see_company', False),
                            limit=limit)
    return JsonResponse({'cursor': _latest_id(),
                         'events': [e.to_sse() for e in rows]})


# ---------------------------------------------------------------------------
# "What still needs processing" — snapshot + change detection
# ---------------------------------------------------------------------------

def snapshot_pending():
    """The live processing picture for the admin dashboard: what data has landed,
    what still needs catalog/RAG/DIAG work, and the current job + load. Cheap
    enough for a GET and for the 30s detector."""
    from . import pipeline
    from .models import PipelineSettings
    work = pipeline.pending_work()
    job = pipeline.active_job()
    load = pipeline.load_snapshot()
    st = PipelineSettings.get()
    est = pipeline.estimate_duration_s(work, st)
    return {
        'pending': {
            'vehicles_on_disk': work['vehicles_on_disk'],
            'need_catalog': work['need_catalog'],
            'need_rag_ingest': work['need_rag_ingest'],
            'need_diag': work['need_diag'],
            'pages_to_embed': work['pages_to_embed'],
            'embed_total': work['embed_total'],
            'embed_done': work['embed_done'],
            'graph_pending': work['graph_pending'],
            'has_work': work['has_work'],
            'counts': {
                'catalog': len(work['need_catalog']),
                'rag_ingest': len(work['need_rag_ingest']),
                'diag': len(work['need_diag']),
            },
            'estimate_s': est,
        },
        'active_job': pipeline.job_dict(job) if job else None,
        'load': load,
        'auto_enabled': st.auto_enabled,
        'ts': timezone.now().isoformat(),
    }


def _pending_fingerprint(snap):
    """A small comparable signature of the processing picture — changes only
    when the real state does (so the detector doesn't spam identical events)."""
    p = snap['pending']
    job = snap.get('active_job') or {}
    return {
        'catalog': p['counts']['catalog'],
        'rag_ingest': p['counts']['rag_ingest'],
        'diag': p['counts']['diag'],
        'pages_to_embed': p['pages_to_embed'],
        'graph_pending': p['graph_pending'],
        'vehicles': p['vehicles_on_disk'],
        'has_work': p['has_work'],
        'job_id': job.get('id'),
        'job_status': job.get('status'),
    }


def detect_and_emit():
    """Compare the current processing picture to the last one; emit an admin
    event when it changed. Called by the realtime_tick timer (fast cadence) and
    after pipeline transitions. Returns the emitted event type or None."""
    try:
        snap = snapshot_pending()
    except Exception:
        return None
    fp = _pending_fingerprint(snap)
    prev = SystemState.get('pending_fingerprint', default=None)
    if prev == fp:
        return None
    SystemState.put('pending_fingerprint', fp)
    if prev is None:
        # First run establishes the baseline without a noisy "changed" event.
        return None

    # Decide the most informative event type from what moved.
    new_data = (fp['vehicles'] > prev.get('vehicles', 0)
                or fp['catalog'] > prev.get('catalog', 0)
                or fp['rag_ingest'] > prev.get('rag_ingest', 0))
    etype = 'data.detected' if new_data else 'processing.pending'
    emit(etype, {
        'pending': snap['pending'],
        'active_job': snap['active_job'],
        'changed_from': prev,
    }, audience='admin')
    return etype
