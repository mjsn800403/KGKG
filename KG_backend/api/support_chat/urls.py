from django.urls import path

from . import views_admin, views_admin_inbox, views_public, views_status

# Included at the top of api/urls.py: its final catch-all
# '<brand>/<year>/<model>/' would otherwise swallow three-segment paths.
# Deliberately NOT under 'api/chat/': that prefix belongs to the assistant.
urlpatterns = [
    path('api/support-chat/status/', views_status.status_view, name='support_chat_status'),
    path('api/support-chat/threads/', views_public.create_view, name='support_chat_create'),
    path('api/support-chat/threads/<str:thread_id>/messages/', views_public.messages_view,
         name='support_chat_messages'),
    path('api/support-chat/threads/<str:thread_id>/contact/', views_public.contact_view,
         name='support_chat_contact'),
    path('api/support-chat/threads/<str:thread_id>/reopen/', views_public.reopen_view,
         name='support_chat_reopen'),
    path('api/support-chat/threads/<str:thread_id>/csat/', views_public.csat_view,
         name='support_chat_csat'),
    path('api/admin/support-chat/presence/heartbeat/', views_status.heartbeat_view,
         name='support_chat_presence_heartbeat'),
    path('api/admin/support-chat/presence/', views_status.presence_view,
         name='support_chat_presence'),
    path('api/admin/support-chat/threads/', views_admin_inbox.list_view,
         name='support_chat_admin_list'),
    path('api/admin/support-chat/threads/<str:thread_id>/', views_admin_inbox.detail_view,
         name='support_chat_admin_detail'),
    path('api/admin/support-chat/threads/<str:thread_id>/reply/', views_admin.reply_view,
         name='support_chat_admin_reply'),
    path('api/admin/support-chat/threads/<str:thread_id>/close/', views_admin.close_view,
         name='support_chat_admin_close'),
    path('api/admin/support-chat/threads/<str:thread_id>/reopen/', views_admin.reopen_view,
         name='support_chat_admin_reopen'),
    path('api/admin/support-chat/threads/<str:thread_id>/seen/', views_admin.seen_view,
         name='support_chat_admin_seen'),
    path('api/admin/support-chat/threads/<str:thread_id>/assign/', views_admin.assign_view,
         name='support_chat_admin_assign'),
    path('api/admin/support-chat/threads/<str:thread_id>/priority/', views_admin.priority_view,
         name='support_chat_admin_priority'),
    path('api/admin/support-chat/threads/<str:thread_id>/intent/', views_admin.intent_view,
         name='support_chat_admin_intent'),
    path('api/admin/support-chat/threads/<str:thread_id>/spam/', views_admin.spam_view,
         name='support_chat_admin_spam'),
    path('api/admin/support-chat/threads/<str:thread_id>/restore/', views_admin.restore_view,
         name='support_chat_admin_restore'),
]
