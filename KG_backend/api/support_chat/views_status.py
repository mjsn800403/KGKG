"""Public availability and the staff console's presence endpoints."""
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from api.admin_auth import acting_admin, require_admin_token
from api.portal import _body

from . import config, presence, throttle


def status_view(request):
    """GET /api/support-chat/status/ -> {mode: 'live'|'async', reply_target_minutes}.

    Public. ``live`` means a named person is eligible to answer (connected and
    declared available), and nothing more: no names, no counts. The reply
    target is ``null`` unless the owner has chosen to publish one; the internal
    ticket SLA is never exposed here."""
    if request.method != 'GET':
        return JsonResponse({'error': 'GET only'}, status=405)
    ok, retry = throttle.shared_ok('status_ip', throttle.client_ip(request))
    if not ok:
        return throttle.too_many(retry)
    return JsonResponse({'mode': presence.current_mode(),
                         'reply_target_minutes': config.reply_target_minutes()})


def _person(request):
    """The signed-in staff member; the loopback script token is not a person
    and has no availability to report."""
    return acting_admin(request)


def _not_a_person():
    return JsonResponse({'error': 'a staff session is required'}, status=403)


@csrf_exempt
@require_admin_token
def heartbeat_view(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)
    admin = _person(request)
    if admin is None:
        return _not_a_person()
    presence.heartbeat(admin)
    return JsonResponse({'ok': True})


@csrf_exempt
@require_admin_token
def presence_view(request):
    """GET: the three facts per staff member. PUT {status}: declare availability."""
    if request.method == 'GET':
        return JsonResponse({'agents': presence.snapshot()})
    if request.method != 'PUT':
        return JsonResponse({'error': 'GET or PUT only'}, status=405)
    admin = _person(request)
    if admin is None:
        return _not_a_person()
    status = _body(request).get('status')
    if status not in presence.STATUSES:
        return JsonResponse({'error': 'وضعیت نامعتبر است.'}, status=400)
    presence.set_status(admin, status)
    return JsonResponse({'ok': True, 'status': status})
