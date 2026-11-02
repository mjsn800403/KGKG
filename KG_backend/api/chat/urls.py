from django.urls import path

from . import views_admin, views_public, views_status

# Included at the top of api/urls.py: its final catch-all
# '<brand>/<year>/<model>/' would otherwise swallow three-segment chat paths.
urlpatterns = [
    path('api/admin/chat/threads/<str:thread_id>/reply/', views_admin.reply_view,
         name='chat_admin_reply'),
    path('api/chat/threads/', views_public.create_view, name='chat_create'),
    path('api/chat/threads/<str:thread_id>/messages/', views_public.messages_view,
         name='chat_messages'),
    path('api/chat/threads/<str:thread_id>/contact/', views_public.contact_view,
         name='chat_contact'),
    path('api/chat/threads/<str:thread_id>/csat/', views_public.csat_view, name='chat_csat'),
    path('api/chat/status/', views_status.status_view, name='chat_status'),
    path('api/admin/chat/presence/heartbeat/', views_status.heartbeat_view,
         name='chat_presence_heartbeat'),
    path('api/admin/chat/presence/', views_status.set_status_view, name='chat_presence'),
]
