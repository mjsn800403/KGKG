"""The support desk: a seat files a ticket, the platform side works it in a
conversation, and both sides see every state change in real time (each
transition emits an Event the SSE layer pushes).

2026-10-30 — this module was a request form for company managers. It is now a
service desk, because the evaluation's "customer feedback is collected by
telephone" finding had a technical cause rather than a cultural one: the whole
API was gated on ``require_manager``, so every non-manager seat got a 403 and
the telephone was its only channel. See
audit-evidence/16-improvement-programme/ROOT_CAUSE_ANALYSIS.md, Finding 4.

What changed, and why each piece exists:

  * **any seat may file a support ticket** (``require_portal_user``); the
    commercial kinds — seats, vehicle access, AI assistant, document packages —
    stay manager-only, because they commit the company to money or scope;
  * a seat sees **their own** tickets, a manager sees the **whole company's**;
  * a **conversation** (``TicketMessage``) replaces appending to one
    ``admin_note`` field, with admin-only internal notes;
  * **ownership** is a foreign key (``assignee``), not a free-text string;
  * **SLA clocks** (api/sla.py) are stamped at creation and reported with a
    met/breached/pending state;
  * a customer message on a closed ticket **reopens** it and restarts the
    resolution clock, so a problem's real resolution time is knowable;
  * **CSAT** is asked once, after closure, of the person who filed it;
  * ``source`` records the channel, so a ticket taken by telephone is recorded
    here too and the shift to digital is measurable.

Routes
    Any seat   GET/POST  /api/company/requests/            list + create
               GET/POST  /api/company/requests/<id>/       detail + message /
                                                           cancel / csat
    Admin      GET/POST  /api/admin/company-requests/      inbox + log a call
               GET/POST  /api/admin/company-requests/<id>/ detail + work it
"""
from django.db.models import Prefetch
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from . import events, sla
from .admin_auth import acting_admin, require_admin_token
from .models import (Car, Company, CompanyRequest, PlatformAdmin, PortalUser,
                     TicketMessage)
from .portal import _body, portal_user
from .portal_auth import (require_manager, require_portal_user,
                          user_can_view_company_stream)


VALID_KINDS = {k for k, _ in CompanyRequest.KIND_CHOICES}
VALID_STATUSES = {s for s, _ in CompanyRequest.STATUS_CHOICES}
VALID_PRIORITIES = {p for p, _ in CompanyRequest.PRIORITY_CHOICES}
VALID_SOURCES = {s for s, _ in CompanyRequest.SOURCE_CHOICES}

#: Kinds that commit the company to cost or scope — a manager's decision.
MANAGER_ONLY_KINDS = {'vehicle_access', 'seats', 'ai_assistant', 'documents'}
#: Kinds any seat may raise for themselves.
SELF_SERVICE_KINDS = VALID_KINDS - MANAGER_ONLY_KINDS

MAX_BODY = 4000
MAX_MESSAGE = 4000


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def _payload_cars(payload):
    ids = (payload or {}).get('car_ids') or []
    if not ids:
        return []
    return [{'id': c.id, 'name': f'{c.car_name} {c.year}'.strip()}
            for c in Car.objects.filter(id__in=ids).order_by('car_name', 'year')]


def _author(m):
    if m.author_user_id and m.author_user:
        return {'kind': 'user',
                'name': (m.author_user.display_name or m.author_user.username)}
    if m.author_admin_id and m.author_admin:
        return {'kind': 'admin', 'name': m.author_admin.username}
    return {'kind': 'admin', 'name': m.author_label or 'admin'}


def _message_dict(m, *, with_internal):
    d = {'id': m.id, 'body': m.body, 'author': _author(m),
         'created_at': m.created_at.isoformat()}
    if with_internal:
        d['internal'] = m.internal
    return d


def _thread(r, *, with_internal):
    """The conversation. The customer never receives internal notes: they are
    filtered out of the queryset, not hidden by the client."""
    qs = r.messages.all().select_related('author_user', 'author_admin')
    if not with_internal:
        qs = qs.filter(internal=False)
    return [_message_dict(m, with_internal=with_internal) for m in qs]


def _sla_dict(r, now):
    return {
        'policy': {'response_hours': sla.targets(r.priority)[0].total_seconds() / 3600,
                   'resolve_hours': sla.targets(r.priority)[1].total_seconds() / 3600},
        'response_due_at': r.sla_response_due_at.isoformat() if r.sla_response_due_at else None,
        'resolve_due_at': r.sla_resolve_due_at.isoformat() if r.sla_resolve_due_at else None,
        'response_state': sla.state(r.sla_response_due_at, r.first_response_at, now),
        'resolve_state': sla.state(r.sla_resolve_due_at, r.resolved_at, now),
    }


def _request_dict(r, *, include_company=False, thread=None, with_internal=False, now=None):
    now = now or timezone.now()
    d = {
        'id': r.id,
        'kind': r.kind,
        'kind_label': dict(CompanyRequest.KIND_CHOICES).get(r.kind, r.kind),
        'subject': r.subject,
        'body': r.body,
        'payload': r.payload or {},
        'cars': _payload_cars(r.payload),
        'status': r.status,
        'status_label': dict(CompanyRequest.STATUS_CHOICES).get(r.status, r.status),
        'priority': r.priority,
        'source': r.source,
        'source_label': dict(CompanyRequest.SOURCE_CHOICES).get(r.source, r.source),
        'admin_note': r.admin_note,
        'handled_by': r.handled_by,
        'assignee': ({'id': r.assignee_id, 'name': r.assignee.username}
                     if r.assignee_id and r.assignee else None),
        'created_by': ({'id': r.created_by_id,
                        'name': (r.created_by.display_name or r.created_by.username)}
                       if r.created_by_id and r.created_by else None),
        'created_at': r.created_at.isoformat(),
        'updated_at': r.updated_at.isoformat(),
        'resolved_at': r.resolved_at.isoformat() if r.resolved_at else None,
        'first_response_at': (r.first_response_at.isoformat()
                              if r.first_response_at else None),
        'escalated_at': r.escalated_at.isoformat() if r.escalated_at else None,
        'reopen_count': r.reopen_count,
        'is_open': r.status in CompanyRequest.OPEN_STATUSES,
        'sla': _sla_dict(r, now),
        'csat': ({'score': r.csat_score, 'comment': r.csat_comment,
                  'at': r.csat_at.isoformat() if r.csat_at else None}
                 if r.csat_score is not None else None),
        'csat_pending': (r.status in CompanyRequest.CLOSED_STATUSES
                         and r.csat_score is None),
    }
    if include_company:
        d['company'] = {'id': r.company_id, 'name': r.company.name}
    if thread is not None:
        d['messages'] = thread
    elif with_internal is not None:
        d['messages'] = _thread(r, with_internal=with_internal)
    return d


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

def _emit(type_, r, **extra):
    """Push one state change to everyone entitled to see it.

    The third emit is the one that matters since the channel opened to every
    seat. `events._scoped_qs` gives a plain user only their OWN 'user' events
    plus broadcasts — 'company' events reach managers and analytics viewers
    only. Without a user-scoped copy a specialist filed a ticket and then
    watched a dashboard that never moved. Managers are skipped because the
    company event already reached them, and a second copy would double every
    toast.
    """
    payload = {'request': _request_dict(r, include_company=True, thread=[])}
    payload.update(extra)
    events.emit_company(type_, r.company_id, payload)
    events.emit(type_, payload, audience='admin')
    filer = r.created_by if r.created_by_id else None
    if filer and not user_can_view_company_stream(filer):
        events.emit_user(type_, filer.id, payload, company_id=r.company_id)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _visible_qs(user):
    """What this seat may see: a manager sees the company, anyone else sees
    only the tickets they filed themselves."""
    qs = (CompanyRequest.objects.filter(company_id=user.company_id)
          .select_related('created_by', 'company', 'assignee'))
    if not user.can_manage_team:
        qs = qs.filter(created_by_id=user.id)
    return qs


def _stamp_sla(r, *, start=None):
    """Stamp both targets from the policy for r.priority."""
    start = start or r.created_at
    r.sla_response_due_at, r.sla_resolve_due_at = sla.due_dates(r.priority, start)


def _add_message(r, body, *, user=None, admin=None, label='', internal=False):
    return TicketMessage.objects.create(
        request=r, author_user=user, author_admin=admin,
        author_label=label, body=body, internal=internal)


def _int_or_none(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


# ---------------------------------------------------------------------------
# Seat side
# ---------------------------------------------------------------------------

@csrf_exempt
@require_portal_user
def company_requests_view(request):
    """GET  /api/company/requests/            -> {requests, meta}
    POST /api/company/requests/  {kind, subject, body?, priority?, payload?}"""
    user = request.portal_user

    if request.method == 'GET':
        qs = _visible_qs(user)
        status = request.GET.get('status')
        if status in VALID_STATUSES:
            qs = qs.filter(status=status)
        now = timezone.now()
        items = [_request_dict(r, with_internal=None, now=now) for r in qs[:300]]
        open_n = sum(1 for r in items if r['is_open'])
        allowed = (VALID_KINDS if user.can_manage_team else SELF_SERVICE_KINDS)
        return JsonResponse({'requests': items,
                             'meta': {'kinds': [{'id': k, 'label': l}
                                                for k, l in CompanyRequest.KIND_CHOICES
                                                if k in allowed],
                                      'can_manage_team': bool(user.can_manage_team),
                                      'open_count': open_n}})

    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)

    b = _body(request)
    kind = (str(b.get('kind') or 'support')).strip()
    if kind not in VALID_KINDS:
        return JsonResponse({'error': 'نوع درخواست نامعتبر است.'}, status=400)
    if kind in MANAGER_ONLY_KINDS and not user.can_manage_team:
        return JsonResponse(
            {'error': 'این نوع درخواست را فقط مدیر تیم می‌تواند ثبت کند.'}, status=403)
    subject = (str(b.get('subject') or '')).strip()[:200]
    if not subject:
        return JsonResponse({'error': 'موضوع درخواست الزامی است.'}, status=400)
    body = (str(b.get('body') or '')).strip()[:MAX_BODY]
    priority = (str(b.get('priority') or 'normal')).strip()
    if priority not in VALID_PRIORITIES:
        priority = 'normal'
    payload = b.get('payload') if isinstance(b.get('payload'), dict) else {}
    payload = _sanitize_payload(kind, payload)

    # `source` is never taken from the client: a ticket filed here came through
    # the portal by definition. Only the admin endpoint may say otherwise.
    r = CompanyRequest.objects.create(
        company_id=user.company_id, created_by=user, kind=kind,
        subject=subject, body=body, priority=priority, payload=payload,
        source='portal')
    _stamp_sla(r)
    r.save(update_fields=['sla_response_due_at', 'sla_resolve_due_at'])
    if body:
        _add_message(r, body, user=user)
    _emit('request.created', r)
    return JsonResponse({'ok': True, 'request': _request_dict(r, with_internal=False)})


def _sanitize_payload(kind, payload):
    out = {}
    if kind == 'vehicle_access':
        ids = payload.get('car_ids') or []
        if isinstance(ids, list):
            valid = list(Car.objects.filter(id__in=[i for i in ids if isinstance(i, int)])
                         .values_list('id', flat=True))
            if valid:
                out['car_ids'] = valid
        docs = payload.get('documents')
        if isinstance(docs, list):
            out['documents'] = [d for d in docs if isinstance(d, str)][:10]
    elif kind == 'seats':
        try:
            out['seats'] = max(1, min(int(payload.get('seats')), 10000))
        except (TypeError, ValueError):
            pass
    return out


@csrf_exempt
@require_portal_user
def company_request_detail_view(request, req_id):
    """GET  /api/company/requests/<id>/   -> {request} including the thread
    POST /api/company/requests/<id>/
         {message: "..."}              add a turn (reopens a closed ticket)
         {csat: {score: 1..5, comment?}}  rate it once, after closure
         {cancel: true}                withdraw an open ticket
    """
    user = request.portal_user
    r = _visible_qs(user).filter(id=req_id).first()
    if not r:
        return JsonResponse({'error': 'not found'}, status=404)

    if request.method == 'POST':
        b = _body(request)
        if 'message' in b:
            err = _seat_message(r, user, b.get('message'))
            if err:
                return err
        elif 'csat' in b:
            err = _seat_csat(r, user, b.get('csat'))
            if err:
                return err
        elif b.get('cancel'):
            err = _seat_cancel(r, user)
            if err:
                return err
        else:
            return JsonResponse({'error': 'عملیات نامعتبر.'}, status=400)
        r.refresh_from_db()
    return JsonResponse({'request': _request_dict(r, include_company=True,
                                                  with_internal=False)})


def _seat_message(r, user, raw):
    body = (str(raw or '')).strip()[:MAX_MESSAGE]
    if not body:
        return JsonResponse({'error': 'متن پیام خالی است.'}, status=400)
    _add_message(r, body, user=user)
    if r.status in CompanyRequest.CLOSED_STATUSES:
        # The customer says it is not done. Reopening restarts the resolution
        # clock from now; the response clock already happened and is kept, so
        # first-response figures stay honest.
        r.status = 'pending'
        r.resolved_at = None
        r.reopen_count += 1
        _, r.sla_resolve_due_at = sla.due_dates(r.priority, timezone.now())
        r.save(update_fields=['status', 'resolved_at', 'reopen_count',
                              'sla_resolve_due_at', 'updated_at'])
        _emit('request.reopened', r)
    else:
        r.save(update_fields=['updated_at'])
        _emit('request.message', r)
    return None


def _seat_csat(r, user, raw):
    if r.status not in CompanyRequest.CLOSED_STATUSES:
        return JsonResponse(
            {'error': 'تا بسته شدن درخواست نمی‌توان امتیاز داد.'}, status=400)
    if r.csat_score is not None:
        return JsonResponse({'error': 'برای این درخواست قبلاً امتیاز ثبت شده است.'},
                            status=400)
    # Only the person who filed it judges it. A ticket logged by the platform
    # side (a telephone call) has no filer, so a manager answers for the company.
    if r.created_by_id:
        if r.created_by_id != user.id:
            return JsonResponse({'error': 'فقط ثبت‌کنندهٔ درخواست می‌تواند امتیاز دهد.'},
                                status=403)
    elif not user.can_manage_team:
        return JsonResponse({'error': 'فقط مدیر تیم می‌تواند امتیاز دهد.'}, status=403)

    data = raw if isinstance(raw, dict) else {}
    score = _int_or_none(data.get('score'))
    if score is None or not 1 <= score <= 5:
        return JsonResponse({'error': 'امتیاز باید عددی بین ۱ تا ۵ باشد.'}, status=400)
    r.csat_score = score
    r.csat_comment = (str(data.get('comment') or '')).strip()[:2000]
    r.csat_at = timezone.now()
    r.save(update_fields=['csat_score', 'csat_comment', 'csat_at', 'updated_at'])
    _emit('request.rated', r)
    return None


def _seat_cancel(r, user):
    if r.status not in CompanyRequest.OPEN_STATUSES:
        return JsonResponse({'error': 'این درخواست قابل لغو نیست.'}, status=400)
    prev = r.status
    r.status = 'rejected'
    r.admin_note = (r.admin_note + '\n' if r.admin_note else '') + 'لغو شده توسط درخواست‌دهنده'
    r.resolved_at = timezone.now()
    r.save(update_fields=['status', 'admin_note', 'resolved_at', 'updated_at'])
    _add_message(r, 'لغو شده توسط درخواست‌دهنده', user=user)
    _emit('request.updated', r, prev_status=prev)
    return None


# ---------------------------------------------------------------------------
# Admin side
# ---------------------------------------------------------------------------

@csrf_exempt
@require_admin_token
def admin_company_requests_view(request):
    """GET  /api/admin/company-requests/?status=&company_id=&source=  — the inbox
    POST /api/admin/company-requests/ {company_id, subject, body?, kind?,
                                       priority?, source?}

    The POST exists so that a request arriving by telephone, e-mail or in
    person is recorded in the same system as a digital one — otherwise the
    only measurable channel is the one that was already working.
    """
    if request.method == 'POST':
        return _admin_create(request)
    if request.method != 'GET':
        return JsonResponse({'error': 'GET or POST'}, status=405)

    qs = CompanyRequest.objects.select_related('company', 'created_by', 'assignee')
    status = request.GET.get('status')
    if status in VALID_STATUSES:
        qs = qs.filter(status=status)
    source = request.GET.get('source')
    if source in VALID_SOURCES:
        qs = qs.filter(source=source)
    company_id = request.GET.get('company_id')
    if company_id:
        if not company_id.isdigit():
            return JsonResponse({'error': 'invalid company_id'}, status=400)
        qs = qs.filter(company_id=int(company_id))
    now = timezone.now()
    items = [_request_dict(r, include_company=True, with_internal=None, now=now)
             for r in qs[:500]]
    counts = {s: 0 for s, _ in CompanyRequest.STATUS_CHOICES}
    for r in CompanyRequest.objects.values('status'):
        counts[r['status']] = counts.get(r['status'], 0) + 1
    return JsonResponse({'requests': items, 'counts': counts,
                         'admins': [{'id': a.id, 'name': a.username}
                                    for a in PlatformAdmin.objects.filter(active=True)
                                    .order_by('username')],
                         'open_count': counts.get('pending', 0) + counts.get('in_progress', 0)})


def _admin_create(request):
    b = _body(request)
    company_id = _int_or_none(b.get('company_id'))
    company = Company.objects.filter(id=company_id).first() if company_id else None
    if not company:
        return JsonResponse({'error': 'company_id نامعتبر است.'}, status=400)
    subject = (str(b.get('subject') or '')).strip()[:200]
    if not subject:
        return JsonResponse({'error': 'موضوع درخواست الزامی است.'}, status=400)
    source = (str(b.get('source') or 'phone')).strip()
    if source not in VALID_SOURCES:
        return JsonResponse({'error': 'کانال نامعتبر است.'}, status=400)
    kind = (str(b.get('kind') or 'support')).strip()
    if kind not in VALID_KINDS:
        return JsonResponse({'error': 'نوع درخواست نامعتبر است.'}, status=400)
    priority = (str(b.get('priority') or 'normal')).strip()
    if priority not in VALID_PRIORITIES:
        priority = 'normal'
    body = (str(b.get('body') or '')).strip()[:MAX_BODY]
    admin = acting_admin(request)

    r = CompanyRequest.objects.create(
        company=company, created_by=None, kind=kind, subject=subject, body=body,
        priority=priority, source=source,
        handled_by=(admin.username if admin else 'admin'))
    _stamp_sla(r)
    r.save(update_fields=['sla_response_due_at', 'sla_resolve_due_at'])
    if body:
        _add_message(r, body, admin=admin,
                     label=('' if admin else 'admin'))
    _emit('request.created', r)
    return JsonResponse({'ok': True, 'request': _request_dict(r, include_company=True,
                                                              with_internal=True)})


@csrf_exempt
@require_admin_token
def admin_company_request_detail_view(request, req_id):
    """GET  /api/admin/company-requests/<id>/  -> {request} with internal notes
    POST /api/admin/company-requests/<id>/
         {status?, admin_note?, handled_by?, message?, internal?,
          assignee_id?, escalate?}

    Advancing to a closed status stamps resolved_at. The first PUBLIC message
    stamps first_response_at (once). Every change emits 'request.updated' to
    both the company and the admin audience.
    """
    r = (CompanyRequest.objects.filter(id=req_id)
         .select_related('company', 'created_by', 'assignee').first())
    if not r:
        return JsonResponse({'error': 'not found'}, status=404)
    if request.method == 'GET':
        return JsonResponse({'request': _request_dict(r, include_company=True,
                                                      with_internal=True)})
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)

    b = _body(request)
    admin = acting_admin(request)
    prev_status = r.status
    changed = False
    emitted = None

    if 'assignee_id' in b:
        raw = b.get('assignee_id')
        if raw is None:
            r.assignee = None
            changed = True
        else:
            aid = _int_or_none(raw)
            target = PlatformAdmin.objects.filter(id=aid, active=True).first() if aid else None
            if not target:
                return JsonResponse({'error': 'مدیر انتخاب‌شده معتبر نیست.'}, status=400)
            r.assignee = target
            changed = True

    if b.get('escalate'):
        if r.escalated_at is None:
            r.escalated_at = timezone.now()
            if r.priority != 'high':
                r.priority = 'high'
                _stamp_sla(r, start=r.created_at)
            changed = True
            emitted = 'request.escalated'

    if 'status' in b:
        new_status = (str(b.get('status') or '')).strip()
        if new_status not in VALID_STATUSES:
            return JsonResponse({'error': 'وضعیت نامعتبر است.'}, status=400)
        if new_status != r.status:
            r.status = new_status
            r.resolved_at = (timezone.now() if new_status in CompanyRequest.CLOSED_STATUSES
                             else None)
            changed = True

    if 'admin_note' in b:
        r.admin_note = (str(b.get('admin_note') or '')).strip()[:MAX_BODY]
        changed = True
        # `admin_note` IS the platform's reply — the customer reads it on their
        # own ticket — so filling it in stops the response clock exactly as a
        # message does. Without this, a ticket answered through the note field
        # stayed unmeasured and drifted into a false SLA breach. An emptied
        # note is not an answer, and an earlier response is never overwritten.
        if r.admin_note and r.first_response_at is None:
            r.first_response_at = timezone.now()

    message = (str(b.get('message') or '')).strip()[:MAX_MESSAGE] if 'message' in b else ''
    internal = bool(b.get('internal'))
    if 'message' in b and not message:
        return JsonResponse({'error': 'متن پیام خالی است.'}, status=400)
    if message:
        _add_message(r, message, admin=admin, label=('' if admin else 'admin'),
                     internal=internal)
        changed = True
        # Only a reply the customer can see is a response.
        if not internal and r.first_response_at is None:
            r.first_response_at = timezone.now()

    if 'handled_by' in b:
        r.handled_by = (str(b.get('handled_by') or '')).strip()[:100]
        changed = True
    elif changed:
        # The acting admin, not the literal string 'admin': ownership has to be
        # a fact for workload and escalation to mean anything.
        r.handled_by = (admin.username if admin else (r.handled_by or 'admin'))

    if changed:
        r.save()
        _emit(emitted or 'request.updated', r, prev_status=prev_status)
    return JsonResponse({'request': _request_dict(r, include_company=True,
                                                  with_internal=True)})
