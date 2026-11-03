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

from api import events
from api.admin_auth import acting_admin, require_admin_token
from api.audit import audit
from api.models import AuditLog, PlatformAdmin
from api.portal import _body

from . import lifecycle, limits, permissions
from .models import SupportMessage, SupportThread


def _audit(request, admin, action, thread, **detail):
    audit(f'support_chat.{action}', request=request, actor_type=AuditLog.ADMIN,
          actor_id=admin.id, actor_label=admin.username, target_type='support_thread',
          target_id=str(thread.pk), detail=detail)


audit_action = _audit


def _announce(request, kind):
    """Ask for an admin-feed update after the transaction commits."""
    request._support_announce = kind


def _staff_action(method_name, permission=permissions.REPLY):
    """Shared preamble: POST only, a staff person holding ``permission``, a
    well-formed thread id. The wrapped function receives (request, admin,
    locked_thread). A change it announces with ``_announce`` reaches the admin
    feed as ``support_chat.updated {thread_id, kind}`` (ids only, never text),
    after the transaction commits and only when the action succeeded."""
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
                if not permissions.visible(admin, thread):
                    # Out of scope must look absent: no existence oracle.
                    return JsonResponse({'error': 'not found'}, status=404)
                if not permissions.can(admin, permission, thread):
                    return _forbidden()
                response = fn(request, admin, thread)
            kind = getattr(request, '_support_announce', None)
            if kind and response.status_code < 300:
                # intent lets the stream deliver this only to roles that cover it.
                events.emit('support_chat.updated',
                            {'thread_id': str(thread.pk), 'kind': kind, 'intent': thread.intent},
                            audience='admin')
            return response
        view.__name__ = method_name
        return view
    return deco


def _forbidden():
    return JsonResponse({'error': 'forbidden', 'code': permissions.denial_code()}, status=403)


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
    _announce(request, 'reply')
    return JsonResponse({'id': msg.id, 'internal': internal}, status=201)


@_staff_action('close_view', permissions.CLOSE)
def close_view(request, admin, thread):
    if thread.status == 'closed':
        return JsonResponse({'error': 'این گفتگو از قبل بسته است.', 'code': 'closed'}, status=409)
    lifecycle.close(thread)
    _audit(request, admin, 'close', thread)
    _announce(request, 'close')
    return JsonResponse({'ok': True, 'status': thread.status})


@_staff_action('reopen_view', permissions.REOPEN)
def reopen_view(request, admin, thread):
    if thread.status != 'closed':
        return JsonResponse({'error': 'این گفتگو بسته نیست.', 'code': 'not_closed'}, status=409)
    lifecycle.reopen(thread, by_staff=True)
    _audit(request, admin, 'reopen', thread, reopen_count=thread.reopen_count)
    _announce(request, 'reopen')
    return JsonResponse({'ok': True, 'status': thread.status})


@_staff_action('seen_view', permissions.READ)
def seen_view(request, admin, thread):
    thread.staff_seen_at = timezone.now()
    thread.save(update_fields=['staff_seen_at'])
    _announce(request, 'seen')
    return JsonResponse({'ok': True})


PRIORITIES = ('low', 'normal', 'high', 'urgent')


def _unchanged():
    return JsonResponse({'ok': True, 'changed': False})


@_staff_action('assign_view', permissions.READ)
def assign_view(request, admin, thread):
    """POST .../assign/ {admin: 'me' | <admin id> | null}. The target must be an
    active staff account. Moves no status and tells the visitor nothing."""
    b = _body(request)
    if 'admin' not in b:
        return JsonResponse({'error': 'admin is required (an id, "me" or null)'}, status=400)
    want = b['admin']
    if want is None:
        target = None
    elif want == 'me':
        target = admin
    elif isinstance(want, int) and not isinstance(want, bool):
        target = PlatformAdmin.objects.filter(pk=want, active=True).first()
        if target is None:
            return JsonResponse({'error': 'unknown or inactive staff account'}, status=400)
    else:
        return JsonResponse({'error': 'admin must be an id, "me" or null'}, status=400)
    if (target.id if target else None) == thread.assignee_id:
        return _unchanged()
    # Taking a thread (or releasing your own) is TAKE; moving it to or from anyone else is ASSIGN.
    needed = (permissions.TAKE if target == admin or (target is None and thread.assignee_id == admin.id)
              else permissions.ASSIGN)
    if not permissions.can(admin, needed, thread):
        return _forbidden()
    thread.assignee = target
    thread.save(update_fields=['assignee'])
    _audit(request, admin, 'assign', thread, assignee_id=target.id if target else None)
    _announce(request, 'assign')
    return JsonResponse({'ok': True, 'changed': True,
                         'assignee': {'id': target.id, 'username': target.username}
                         if target else None})


@_staff_action('priority_view', permissions.PRIORITY)
def priority_view(request, admin, thread):
    value = _body(request).get('priority')
    if value not in PRIORITIES:
        return JsonResponse({'error': 'unknown priority'}, status=400)
    if value == thread.priority:
        return _unchanged()
    old, thread.priority = thread.priority, value
    thread.save(update_fields=['priority'])
    _audit(request, admin, 'priority', thread, **{'from': old, 'to': value})
    _announce(request, 'priority')
    return JsonResponse({'ok': True, 'changed': True, 'priority': value})


@_staff_action('intent_view', permissions.INTENT)
def intent_view(request, admin, thread):
    value = _body(request).get('intent')
    if value not in dict(SupportThread.INTENT_CHOICES):
        return JsonResponse({'error': 'unknown intent'}, status=400)
    if value == thread.intent:
        return _unchanged()
    old, thread.intent = thread.intent, value
    thread.save(update_fields=['intent'])
    _audit(request, admin, 'intent', thread, **{'from': old, 'to': value})
    _announce(request, 'intent')
    return JsonResponse({'ok': True, 'changed': True, 'intent': value})


@_staff_action('spam_view', permissions.SPAM)
def spam_view(request, admin, thread):
    """Mark as spam: the visitor's token stops working (404) and the thread
    leaves the default inbox. Reversible with ``restore``."""
    if thread.status == 'spam':
        return JsonResponse({'error': 'already spam', 'code': 'spam'}, status=409)
    thread.status = 'spam'
    thread.save(update_fields=['status'])
    _audit(request, admin, 'spam', thread)
    _announce(request, 'spam')
    return JsonResponse({'ok': True, 'status': 'spam'})


@_staff_action('restore_view', permissions.SPAM)
def restore_view(request, admin, thread):
    """Undo ``spam``: the thread returns to ``waiting_staff`` (the visitor's last
    word is unanswered). The earlier status is not remembered."""
    if thread.status != 'spam':
        return JsonResponse({'error': 'not spam', 'code': 'not_spam'}, status=409)
    thread.status = 'waiting_staff'
    thread.save(update_fields=['status'])
    _audit(request, admin, 'restore', thread)
    _announce(request, 'restore')
    return JsonResponse({'ok': True, 'status': thread.status})
