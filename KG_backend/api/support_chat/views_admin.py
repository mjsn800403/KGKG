"""Staff side of a visitor thread: reply, close, reopen, mark seen.

Every action needs a signed-in staff PERSON: the loopback script token is
rejected (403), so each reply, closure and reopening is attributable. Message
content never enters the audit log; the record is who, what, which thread.
The full inbox (list, assign, filters) arrives in Phase 5.
"""
import uuid

from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from api.admin_auth import acting_admin, require_admin_token
from api.audit import audit
from api.models import AuditLog
from api.portal import _body

from . import lifecycle, limits
from .models import SupportMessage, SupportThread


def _audit(request, admin, action, thread, **detail):
    audit(f'support_chat.{action}', request=request, actor_type=AuditLog.ADMIN,
          actor_id=admin.id, actor_label=admin.username, target_type='support_thread',
          target_id=str(thread.pk), detail=detail)


def _staff_action(method_name):
    """Shared preamble: POST only, a staff person, a well-formed thread id.
    The wrapped function receives (request, admin, locked_thread)."""
    def deco(fn):
        @csrf_exempt
        @require_admin_token
        def view(request, thread_id):
            if request.method != 'POST':
                return JsonResponse({'error': 'POST only'}, status=405)
            admin = acting_admin(request)
            if admin is None:
                return JsonResponse({'error': 'a staff session is required'}, status=403)
            try:
                key = uuid.UUID(str(thread_id))
            except ValueError:
                return JsonResponse({'error': 'not found'}, status=404)
            with transaction.atomic():
                thread = SupportThread.objects.select_for_update().filter(pk=key).first()
                if thread is None:
                    return JsonResponse({'error': 'not found'}, status=404)
                return fn(request, admin, thread)
        view.__name__ = method_name
        return view
    return deco


def _closed(thread):
    return JsonResponse({'error': 'این گفتگو بسته است. ابتدا آن را دوباره باز کنید.',
                         'code': 'closed'}, status=409)


@_staff_action('reply_view')
def reply_view(request, admin, thread):
    """POST .../reply/ {message, internal?}. A public reply moves the thread to
    ``waiting_customer``. A closed thread is NOT reopened by a reply: reopen it
    explicitly first."""
    b = _body(request)
    text, err = limits.clean_body(b.get('message'))
    if err:
        return JsonResponse({'error': err}, status=400)
    if thread.status == 'closed':
        return _closed(thread)
    internal = b.get('internal') is True
    msg = SupportMessage.objects.create(thread=thread, author_kind='admin', author_admin=admin,
                                        body=text, internal=internal)
    if not internal:
        thread.status = 'waiting_customer'
        thread.last_activity_at = timezone.now()
        thread.save(update_fields=['status', 'last_activity_at'])
    _audit(request, admin, 'reply', thread, message_id=msg.id, internal=internal)
    return JsonResponse({'id': msg.id, 'internal': internal}, status=201)


@_staff_action('close_view')
def close_view(request, admin, thread):
    if thread.status == 'closed':
        return JsonResponse({'error': 'این گفتگو از قبل بسته است.', 'code': 'closed'}, status=409)
    lifecycle.close(thread)
    _audit(request, admin, 'close', thread)
    return JsonResponse({'ok': True, 'status': thread.status})


@_staff_action('reopen_view')
def reopen_view(request, admin, thread):
    if thread.status != 'closed':
        return JsonResponse({'error': 'این گفتگو بسته نیست.', 'code': 'not_closed'}, status=409)
    lifecycle.reopen(thread, by_staff=True)
    _audit(request, admin, 'reopen', thread, reopen_count=thread.reopen_count)
    return JsonResponse({'ok': True, 'status': thread.status})


@_staff_action('seen_view')
def seen_view(request, admin, thread):
    thread.staff_seen_at = timezone.now()
    thread.save(update_fields=['staff_seen_at'])
    return JsonResponse({'ok': True})
