"""Staff side of a visitor thread. Phase 2 has only the reply; the inbox,
assignment and status changes arrive in Phase 5."""
import uuid

from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from api.admin_auth import acting_admin, require_admin_token
from api.portal import _body

from . import limits
from .models import ChatMessage, ChatThread


@csrf_exempt
@require_admin_token
def reply_view(request, thread_id):
    """POST /api/admin/chat/threads/<id>/reply/  {message, internal?}

    A public reply moves the thread to ``waiting_customer`` (reopening a closed
    one); an internal note is invisible to the visitor and changes nothing else."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)
    try:
        key = uuid.UUID(str(thread_id))
    except ValueError:
        return JsonResponse({'error': 'not found'}, status=404)
    b = _body(request)
    text, err = limits.clean_body(b.get('message'))
    if err:
        return JsonResponse({'error': err}, status=400)
    internal = b.get('internal') is True
    with transaction.atomic():
        thread = ChatThread.objects.select_for_update().filter(pk=key).first()
        if thread is None:
            return JsonResponse({'error': 'not found'}, status=404)
        msg = ChatMessage.objects.create(thread=thread, author_kind='admin',
                                         author_admin=acting_admin(request),
                                         body=text, internal=internal)
        if not internal:
            thread.status = 'waiting_customer'
            thread.closed_at = None
            thread.last_activity_at = timezone.now()
            thread.save(update_fields=['status', 'closed_at', 'last_activity_at'])
    return JsonResponse({'id': msg.id, 'internal': internal}, status=201)
