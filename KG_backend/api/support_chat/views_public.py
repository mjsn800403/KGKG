"""Endpoints for an anonymous landing-page visitor.

Authorisation is the thread's bearer token in ``X-Support-Chat-Token`` (a
header, not a cookie, so there is no CSRF surface). A wrong token and a missing
thread are indistinguishable: both 404. A malformed token is rejected before
any database query, and only FAILED checks count toward the per-IP limit, so a
valid visitor is never blocked by a neighbour's bad requests.

    POST  /api/support-chat/threads/                  start (idempotent on a client token)
    GET   /api/support-chat/threads/<id>/messages/    poll   (?after=<message id>)
    POST  /api/support-chat/threads/<id>/messages/    send
    PATCH /api/support-chat/threads/<id>/contact/     add name / phone / email
    POST  /api/support-chat/threads/<id>/reopen/      continue a closed thread (time-limited)
    POST  /api/support-chat/threads/<id>/csat/        rate a closure, once
"""
import hashlib
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from api import events
from api.audit import audit
from api.models import AuditLog
from api.portal import _body, _verify_turnstile

from . import config, lifecycle, limits, presence, throttle, tokens
from .models import SupportMessage, SupportRating, SupportThread

AUTHOR_LABELS = {'admin': 'پشتیبانی', 'system': 'سامانه', 'visitor': None}


def _not_found():
    return JsonResponse({'error': 'not found'}, status=404)


def _message_dict(m):
    return {'id': m.id, 'author_kind': m.author_kind,
            'author_label': AUTHOR_LABELS.get(m.author_kind), 'body': m.body,
            'created_at': m.created_at.isoformat()}


def _bad_token(request):
    """404, or 429 once this IP has produced too many FAILED token checks."""
    ok, retry = throttle.shared_ok('bad_token_ip', throttle.client_ip(request))
    return _not_found() if ok else throttle.too_many(retry)


def _thread_for(request, thread_id):
    """(thread, None) or (None, error response)."""
    thread = tokens.authorise(thread_id, request.META.get('HTTP_X_SUPPORT_CHAT_TOKEN', ''))
    if thread is None or thread.status == 'spam':
        return None, _bad_token(request)
    return thread, None


def _emit(type_, thread, **extra):
    """Admin-feed event carrying ids only: never message text or contact details."""
    events.emit(type_, {'thread_id': str(thread.pk), 'intent': thread.intent, **extra},
                audience='admin')


def _insert_visitor_message(thread, text, client_id):
    msg = SupportMessage.objects.create(thread=thread, author_kind='visitor', body=text,
                                        client_id=client_id)
    SupportThread.objects.filter(pk=thread.pk).update(
        status='waiting_staff', last_activity_at=timezone.now())
    return msg


@csrf_exempt
def create_view(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)
    ok, retry = throttle.shared_ok('create_ip', throttle.client_ip(request))
    if not ok:
        return throttle.too_many(retry)
    b = _body(request)
    if b.get('website'):
        # Honeypot: look successful, store nothing.
        return JsonResponse({'thread_id': '00000000-0000-0000-0000-000000000000',
                             'token': 'x', 'mode': 'async', 'message': {}}, status=201)
    client_token = b.get('token')
    if client_token is not None:
        if not tokens.valid_format(client_token):
            return JsonResponse({'error': 'توکن نامعتبر است.'}, status=400)
        existing = tokens.find_by_token(client_token)
        if existing is not None:
            return _existing(existing)
    if not _verify_turnstile(request, b.get('turnstile_token'), 'support_chat'):
        return JsonResponse({'error': 'تأیید امنیتی انجام نشد. دوباره تلاش کنید.'}, status=400)
    text, err = limits.clean_body(b.get('message'))
    if err:
        return JsonResponse({'error': err}, status=400)
    contact, err = limits.clean_contact(b.get('contact'))
    if err:
        return JsonResponse({'error': err}, status=400)
    if client_token is not None:
        raw_token, token_hash = client_token, tokens.hash_token(client_token)
    else:
        raw_token, token_hash = tokens.new_token()
    try:
        with transaction.atomic():
            thread = SupportThread.objects.create(
                token_hash=token_hash, intent=limits.clean_intent(b.get('intent')),
                source_page=limits.clean_page(b.get('page')),
                referrer=limits.clean_referrer(b.get('referrer')),
                ua_hash=hashlib.sha256(
                    request.META.get('HTTP_USER_AGENT', '').encode()).hexdigest(),
                **contact)
            msg = _insert_visitor_message(thread, text,
                                          limits.clean_client_id(b.get('client_id')))
    except IntegrityError:
        # Lost a race with the same client token: the other request created it.
        existing = tokens.find_by_token(client_token) if client_token else None
        if existing is None:
            raise
        return _existing(existing)
    _emit('support_chat.message', thread)
    body = {'thread_id': str(thread.pk), 'mode': presence.current_mode(),
            'message': _message_dict(msg)}
    if client_token is None:
        body['token'] = raw_token
    return JsonResponse(body, status=201)


def _existing(thread):
    if thread.status == 'spam':
        return _not_found()
    return JsonResponse({'thread_id': str(thread.pk), 'status': thread.status,
                         'mode': presence.current_mode()}, status=200)


def _poll(request, thread):
    ok, retry = throttle.poll_ok(str(thread.pk))
    if not ok:
        return throttle.too_many(retry)
    try:
        after = int(request.GET.get('after') or 0)
    except ValueError:
        after = 0
    rows = thread.messages.filter(internal=False, id__gt=after)[:200]
    seen = thread.staff_seen_at
    return JsonResponse({'messages': [_message_dict(m) for m in rows],
                         'status': thread.status, 'mode': presence.current_mode(),
                         'staff_seen_at': seen.isoformat() if seen else None,
                         'can_reopen': lifecycle.can_reopen(thread)})


def _send(request, thread):
    ok, retry = throttle.shared_ok('send', thread.pk)
    if not ok:
        return throttle.too_many(retry)
    b = _body(request)
    text, err = limits.clean_body(b.get('message'))
    if err:
        return JsonResponse({'error': err}, status=400)
    client_id = limits.clean_client_id(b.get('client_id'))
    cap, window = config.limit('send_hour')
    with transaction.atomic():
        # One writer at a time per thread: the duplicate check, the hourly cap
        # and the insert below are a single decision, not three racing ones.
        locked = SupportThread.objects.select_for_update().get(pk=thread.pk)
        if locked.status == 'closed':
            return JsonResponse({'error': 'این گفتگو بسته شده است.', 'code': 'closed',
                                 'can_reopen': lifecycle.can_reopen(locked)}, status=409)
        if client_id:
            dup = locked.messages.filter(client_id=client_id).first()
            if dup is not None:
                return JsonResponse(_message_dict(dup), status=200)
        if cap:
            recent = locked.messages.filter(
                author_kind='visitor',
                created_at__gte=timezone.now() - timedelta(seconds=window)).count()
            if recent >= cap:
                return throttle.too_many(60)
        try:
            with transaction.atomic():
                msg = _insert_visitor_message(locked, text, client_id)
        except IntegrityError:
            return JsonResponse(_message_dict(locked.messages.get(client_id=client_id)),
                                status=200)
    _emit('support_chat.message', locked)
    return JsonResponse(_message_dict(msg), status=201)


@csrf_exempt
def messages_view(request, thread_id):
    thread, err = _thread_for(request, thread_id)
    if err is not None:
        return err
    if request.method == 'GET':
        return _poll(request, thread)
    if request.method == 'POST':
        return _send(request, thread)
    return JsonResponse({'error': 'method not allowed'}, status=405)


@csrf_exempt
def contact_view(request, thread_id):
    thread, err = _thread_for(request, thread_id)
    if err is not None:
        return err
    if request.method != 'PATCH':
        return JsonResponse({'error': 'PATCH only'}, status=405)
    ok, retry = throttle.shared_ok('contact', thread.pk)
    if not ok:
        return throttle.too_many(retry)
    contact, err = limits.clean_contact(_body(request))
    if err:
        return JsonResponse({'error': err}, status=400)
    if contact:
        SupportThread.objects.filter(pk=thread.pk).update(**contact)
    return JsonResponse({'ok': True})


@csrf_exempt
def reopen_view(request, thread_id):
    thread, err = _thread_for(request, thread_id)
    if err is not None:
        return err
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)
    ok, retry = throttle.shared_ok('reopen', thread.pk)
    if not ok:
        return throttle.too_many(retry)
    with transaction.atomic():
        locked = SupportThread.objects.select_for_update().get(pk=thread.pk)
        if locked.status != 'closed':
            return JsonResponse({'error': 'این گفتگو بسته نیست.', 'code': 'not_closed'},
                                status=409)
        if not lifecycle.can_reopen(locked):
            return JsonResponse({'error': 'مهلت ادامهٔ این گفتگو به پایان رسیده است.',
                                 'code': 'reopen_window_expired'}, status=409)
        lifecycle.reopen(locked, by_staff=False)
    # No IP and no content: the thread id is the whole record.
    audit('support_chat.visitor_reopen', actor_type=AuditLog.ANONYMOUS,
          target_type='support_thread', target_id=str(locked.pk))
    _emit('support_chat.reopened', locked)
    return JsonResponse({'ok': True, 'status': locked.status})


@csrf_exempt
def csat_view(request, thread_id):
    thread, err = _thread_for(request, thread_id)
    if err is not None:
        return err
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)
    ok, retry = throttle.shared_ok('csat', thread.pk)
    if not ok:
        return throttle.too_many(retry)
    score = _body(request).get('score')
    if isinstance(score, bool) or not isinstance(score, int) or not 1 <= score <= 5:
        return JsonResponse({'error': 'امتیاز باید بین ۱ تا ۵ باشد.'}, status=400)
    with transaction.atomic():
        locked = SupportThread.objects.select_for_update().get(pk=thread.pk)
        if locked.status != 'closed':
            return JsonResponse({'error': 'امتیازدهی ممکن نیست.', 'code': 'not_closed'}, status=409)
        try:
            with transaction.atomic():
                SupportRating.objects.create(thread=locked, score=score,
                                             closure=locked.reopen_count)
        except IntegrityError:
            return JsonResponse({'error': 'برای این گفتگو قبلاً امتیاز ثبت شده است.',
                                 'code': 'already_rated'}, status=409)
    return JsonResponse({'ok': True}, status=201)
