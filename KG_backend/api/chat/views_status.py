"""Public status and the agent console's presence endpoints."""
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from api import sla
from api.admin_auth import acting_admin, require_admin_token
from api.portal import _body
from api.ratelimit import rate_limited

from . import presence


@rate_limited('chat_status', 60, 60)
def status_view(request):
    """GET /api/chat/status/ -> {mode: 'live'|'async', expected_reply_minutes}.
    Public. Never reveals who is available, only whether anyone is."""
    if request.method != 'GET':
        return JsonResponse({'error': 'GET only'}, status=405)
    minutes = int(sla.targets('normal')[0].total_seconds() // 60)
    return JsonResponse({'mode': presence.current_mode(), 'expected_reply_minutes': minutes})


def _person(request):
    """The signed-in staff member; the loopback script token is not a person
    and has no availability to report."""
    return acting_admin(request)


@csrf_exempt
@require_admin_token
def heartbeat_view(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)
    admin = _person(request)
    if admin is None:
        return JsonResponse({'error': 'a staff session is required'}, status=403)
    presence.heartbeat(admin)
    return JsonResponse({'ok': True})


@csrf_exempt
@require_admin_token
def set_status_view(request):
    if request.method != 'PUT':
        return JsonResponse({'error': 'PUT only'}, status=405)
    admin = _person(request)
    if admin is None:
        return JsonResponse({'error': 'a staff session is required'}, status=403)
    status = _body(request).get('status')
    if status not in presence.STATUSES:
        return JsonResponse({'error': 'وضعیت نامعتبر است.'}, status=400)
    presence.set_status(admin, status)
    return JsonResponse({'ok': True, 'status': status})
