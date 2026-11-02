"""Endpoints for an anonymous landing-page visitor.

Authorisation is the thread's bearer token in ``X-Chat-Token`` (a header, not
a cookie, so there is no CSRF surface). A wrong token and a missing thread are
indistinguishable: both 404.

    POST  /api/chat/threads/                     start a conversation
    GET   /api/chat/threads/<id>/messages/       poll   (?after=<message id>)
    POST  /api/chat/threads/<id>/messages/       send
    PATCH /api/chat/threads/<id>/contact/        add name / phone / email
    POST  /api/chat/threads/<id>/csat/           rate, once, after it is closed
"""
import hashlib
import uuid
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from api import events
from api.portal import _body, _verify_turnstile
from api.ratelimit import rate_limited

from . import limits, presence, tokens
from .models import ChatMessage, ChatThread

def _not_found():
    return JsonResponse({'error': 'not found'}, status=404)


def _message_dict(m):
    return {'id': m.id, 'author_kind': m.author_kind, 'body': m.body,
            'created_at': m.created_at.isoformat()}


def _thread_for(request, thread_id):
    thread = tokens.authorise(thread_id, request.META.get('HTTP_X_CHAT_TOKEN', ''))
    if thread is None or thread.status == 'spam':
        return None
    return thread


def _store_visitor_message(thread, text, client_id):
    """(message, created). Idempotent on ``client_id``."""
    if client_id:
        existing = thread.messages.filter(client_id=client_id).first()
        if existing:
            return existing, False
    now = timezone.now()
    try:
        with transaction.atomic():
            msg = ChatMessage.objects.create(thread=thread, author_kind='visitor',
                                             body=text, client_id=client_id)
            ChatThread.objects.filter(pk=thread.pk).update(
                status='waiting_staff', last_activity_at=now)
    except IntegrityError:
        return thread.messages.get(client_id=client_id), False
    events.emit('chat.message',
                {'thread_id': str(thread.pk), 'intent': thread.intent, 'preview': text[:80]},
                audience='admin')
    return msg, True


@csrf_exempt
@rate_limited('chat_create', 5, 600)
def create_view(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)
    b = _body(request)
    if b.get('website'):
        # Honeypot: look successful, store nothing.
        return JsonResponse({'thread_id': str(uuid.uuid4()), 'token': 'x',
                             'mode': 'async', 'message': {}}, status=201)
    if not _verify_turnstile(request, b.get('turnstile_token'), 'chat'):
        return JsonResponse({'error': 'تأیید امنیتی انجام نشد. دوباره تلاش کنید.'}, status=400)
    text, err = limits.clean_body(b.get('message'))
    if err:
        return JsonResponse({'error': err}, status=400)
    contact, err = limits.clean_contact(b.get('contact'))
    if err:
        return JsonResponse({'error': err}, status=400)
    raw_token, token_hash = tokens.new_token()
    thread = ChatThread.objects.create(
        token_hash=token_hash, intent=limits.clean_intent(b.get('intent')),
        source_page=str(b.get('page') or '')[:200],
        referrer=str(b.get('referrer') or '')[:200],
        ua_hash=hashlib.sha256(request.META.get('HTTP_USER_AGENT', '').encode()).hexdigest(),
        **contact)
    msg, _ = _store_visitor_message(thread, text, limits.clean_client_id(b.get('client_id')))
    return JsonResponse({'thread_id': str(thread.pk), 'token': raw_token,
                         'mode': presence.current_mode(), 'message': _message_dict(msg)},
                        status=201)


@rate_limited('chat_poll', 120, 60)
def _poll(request, thread):
    try:
        after = int(request.GET.get('after') or 0)
    except ValueError:
        after = 0
    rows = thread.messages.filter(internal=False, id__gt=after)[:200]
    return JsonResponse({'messages': [_message_dict(m) for m in rows],
                         'status': thread.status, 'mode': presence.current_mode()})


@rate_limited('chat_send', 30, 60)
def _send(request, thread):
    if thread.status == 'closed':
        return JsonResponse({'error': 'این گفتگو بسته شده است.'}, status=409)
    b = _body(request)
    text, err = limits.clean_body(b.get('message'))
    if err:
        return JsonResponse({'error': err}, status=400)
    client_id = limits.clean_client_id(b.get('client_id'))
    if not (client_id and thread.messages.filter(client_id=client_id).exists()):
        recent = thread.messages.filter(
            author_kind='visitor', created_at__gte=timezone.now() - timedelta(hours=1)).count()
        if recent >= limits.MAX_PER_THREAD_PER_HOUR:
            return JsonResponse({'error': 'تعداد پیام‌ها زیاد است. کمی بعد دوباره تلاش کنید.'},
                                status=429)
    msg, created = _store_visitor_message(thread, text, client_id)
    return JsonResponse(_message_dict(msg), status=201 if created else 200)


@csrf_exempt
def messages_view(request, thread_id):
    thread = _thread_for(request, thread_id)
    if thread is None:
        return _not_found()
    if request.method == 'GET':
        return _poll(request, thread)
    if request.method == 'POST':
        return _send(request, thread)
    return JsonResponse({'error': 'method not allowed'}, status=405)


@csrf_exempt
def contact_view(request, thread_id):
    thread = _thread_for(request, thread_id)
    if thread is None:
        return _not_found()
    if request.method != 'PATCH':
        return JsonResponse({'error': 'PATCH only'}, status=405)
    contact, err = limits.clean_contact(_body(request))
    if err:
        return JsonResponse({'error': err}, status=400)
    for field, value in contact.items():
        setattr(thread, field, value)
    thread.save(update_fields=list(contact) or None)
    return JsonResponse({'ok': True})


@csrf_exempt
def csat_view(request, thread_id):
    thread = _thread_for(request, thread_id)
    if thread is None:
        return _not_found()
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)
    if thread.status != 'closed' or thread.csat_score is not None:
        return JsonResponse({'error': 'امتیازدهی ممکن نیست.'}, status=409)
    score = _body(request).get('score')
    if isinstance(score, bool) or not isinstance(score, int) or not 1 <= score <= 5:
        return JsonResponse({'error': 'امتیاز باید بین ۱ تا ۵ باشد.'}, status=400)
    thread.csat_score, thread.csat_at = score, timezone.now()
    thread.save(update_fields=['csat_score', 'csat_at'])
    return JsonResponse({'ok': True})
