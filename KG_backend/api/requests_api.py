"""Company requests: a manager files an ask, the platform admin actions it, and
both dashboards reflect every state change in real time (each transition emits
an Event the SSE layer pushes).

Manager side  (portal token, team-manager gated):
    GET/POST  /api/company/requests/           list + create
    GET/POST  /api/company/requests/<id>/      detail + cancel (own, still open)
Admin side    (admin token):
    GET       /api/admin/company-requests/     inbox (all companies)
    POST      /api/admin/company-requests/<id>/ set status / note
"""
import json

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from . import events
from .admin_auth import require_admin_token
from .models import Car, CompanyRequest, PortalUser
from .portal import _body, portal_user
from .portal_auth import require_manager


VALID_KINDS = {k for k, _ in CompanyRequest.KIND_CHOICES}
VALID_STATUSES = {s for s, _ in CompanyRequest.STATUS_CHOICES}
VALID_PRIORITIES = {p for p, _ in CompanyRequest.PRIORITY_CHOICES}


def _request_dict(r, include_company=False):
    d = {
        'id': r.id,
        'kind': r.kind,
        'kind_label': dict(CompanyRequest.KIND_CHOICES).get(r.kind, r.kind),
        'subject': r.subject,
        'body': r.body,
        'payload': r.payload or {},
        'status': r.status,
        'status_label': dict(CompanyRequest.STATUS_CHOICES).get(r.status, r.status),
        'priority': r.priority,
        'admin_note': r.admin_note,
        'handled_by': r.handled_by,
        'created_by': ({'id': r.created_by_id,
                        'name': (r.created_by.display_name or r.created_by.username)}
                       if r.created_by_id and r.created_by else None),
        'created_at': r.created_at.isoformat(),
        'updated_at': r.updated_at.isoformat(),
        'resolved_at': r.resolved_at.isoformat() if r.resolved_at else None,
        'is_open': r.status in CompanyRequest.OPEN_STATUSES,
    }
    if include_company:
        d['company'] = {'id': r.company_id, 'name': r.company.name}
    return d


def _emit_created(r):
    payload = {'request': _request_dict(r, include_company=True)}
    events.emit_company('request.created', r.company_id, payload)
    events.emit('request.created', payload, audience='admin')


def _emit_updated(r, prev_status=None):
    payload = {'request': _request_dict(r, include_company=True), 'prev_status': prev_status}
    events.emit_company('request.updated', r.company_id, payload)
    events.emit('request.updated', payload, audience='admin')


# ---------------------------------------------------------------------------
# Manager side
# ---------------------------------------------------------------------------

@csrf_exempt
@require_manager
def company_requests_view(request):
    """GET  /api/company/requests/            -> {requests, meta}
    POST /api/company/requests/  {kind, subject, body?, priority?, payload?}"""
    manager = request.manager

    if request.method == 'GET':
        qs = CompanyRequest.objects.filter(company_id=manager.company_id).select_related('created_by')
        status = request.GET.get('status')
        if status in VALID_STATUSES:
            qs = qs.filter(status=status)
        items = [_request_dict(r) for r in qs[:300]]
        open_n = sum(1 for r in items if r['is_open'])
        return JsonResponse({'requests': items,
                             'meta': {'kinds': [{'id': k, 'label': l}
                                                for k, l in CompanyRequest.KIND_CHOICES],
                                      'open_count': open_n}})

    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)

    b = _body(request)
    kind = (str(b.get('kind') or 'support')).strip()
    if kind not in VALID_KINDS:
        return JsonResponse({'error': 'نوع درخواست نامعتبر است.'}, status=400)
    subject = (str(b.get('subject') or '')).strip()[:200]
    if not subject:
        return JsonResponse({'error': 'موضوع درخواست الزامی است.'}, status=400)
    body = (str(b.get('body') or '')).strip()[:4000]
    priority = (str(b.get('priority') or 'normal')).strip()
    if priority not in VALID_PRIORITIES:
        priority = 'normal'
    payload = b.get('payload') if isinstance(b.get('payload'), dict) else {}
    # Light validation of a couple of well-known structured asks.
    payload = _sanitize_payload(kind, payload)

    r = CompanyRequest.objects.create(
        company_id=manager.company_id, created_by=manager, kind=kind,
        subject=subject, body=body, priority=priority, payload=payload)
    _emit_created(r)
    return JsonResponse({'ok': True, 'request': _request_dict(r)})


def _sanitize_payload(kind, payload):
    out = {}
    if kind == 'vehicle_access':
        ids = payload.get('car_ids') or []
        if isinstance(ids, list):
            valid = list(Car.objects.filter(id__in=[i for i in ids if isinstance(i, int)])
                         .values_list('id', flat=True))
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
@require_manager
def company_request_detail_view(request, req_id):
    """GET  /api/company/requests/<id>/          -> {request}
    POST /api/company/requests/<id>/ {cancel:true}  (withdraw own open request)"""
    manager = request.manager
    r = (CompanyRequest.objects.filter(id=req_id, company_id=manager.company_id)
         .select_related('created_by', 'company').first())
    if not r:
        return JsonResponse({'error': 'not found'}, status=404)

    if request.method == 'POST':
        b = _body(request)
        if b.get('cancel'):
            if r.status not in CompanyRequest.OPEN_STATUSES:
                return JsonResponse({'error': 'این درخواست قابل لغو نیست.'}, status=400)
            prev = r.status
            r.status = 'rejected'
            r.admin_note = (r.admin_note + '\n' if r.admin_note else '') + 'لغو شده توسط درخواست‌دهنده'
            r.resolved_at = timezone.now()
            r.save(update_fields=['status', 'admin_note', 'resolved_at', 'updated_at'])
            _emit_updated(r, prev_status=prev)
        else:
            return JsonResponse({'error': 'عملیات نامعتبر.'}, status=400)
    return JsonResponse({'request': _request_dict(r, include_company=True)})


# ---------------------------------------------------------------------------
# Admin side
# ---------------------------------------------------------------------------

@require_admin_token
def admin_company_requests_view(request):
    """GET /api/admin/company-requests/?status=&company_id= — the inbox."""
    qs = CompanyRequest.objects.select_related('company', 'created_by')
    status = request.GET.get('status')
    if status in VALID_STATUSES:
        qs = qs.filter(status=status)
    company_id = request.GET.get('company_id')
    if company_id:
        qs = qs.filter(company_id=company_id)
    items = [_request_dict(r, include_company=True) for r in qs[:500]]
    counts = {s: 0 for s, _ in CompanyRequest.STATUS_CHOICES}
    for r in CompanyRequest.objects.values('status'):
        counts[r['status']] = counts.get(r['status'], 0) + 1
    return JsonResponse({'requests': items, 'counts': counts,
                         'open_count': counts.get('pending', 0) + counts.get('in_progress', 0)})


@csrf_exempt
@require_admin_token
def admin_company_request_detail_view(request, req_id):
    """POST /api/admin/company-requests/<id>/ {status?, admin_note?, handled_by?}

    Advancing to a closed status stamps resolved_at. Every change emits a
    'request.updated' event to BOTH the company (so the manager's dashboard
    updates live) and the admin audience."""
    r = (CompanyRequest.objects.filter(id=req_id)
         .select_related('company', 'created_by').first())
    if not r:
        return JsonResponse({'error': 'not found'}, status=404)
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)

    b = _body(request)
    prev_status = r.status
    changed = False
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
        r.admin_note = (str(b.get('admin_note') or '')).strip()[:4000]
        changed = True
    if 'handled_by' in b:
        r.handled_by = (str(b.get('handled_by') or '')).strip()[:100]
        changed = True
    elif changed and not r.handled_by:
        r.handled_by = 'admin'

    if changed:
        r.save()
        _emit_updated(r, prev_status=prev_status)
    return JsonResponse({'request': _request_dict(r, include_company=True)})
