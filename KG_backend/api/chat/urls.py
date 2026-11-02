from django.urls import path

from . import views_status

# Included at the top of api/urls.py: its final catch-all
# '<brand>/<year>/<model>/' would otherwise swallow three-segment chat paths.
urlpatterns = [
    path('api/chat/status/', views_status.status_view, name='chat_status'),
    path('api/admin/chat/presence/heartbeat/', views_status.heartbeat_view,
         name='chat_presence_heartbeat'),
    path('api/admin/chat/presence/', views_status.set_status_view, name='chat_presence'),
]
