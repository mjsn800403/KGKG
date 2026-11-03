"""Every @csrf_exempt view and why it is safe (#62).

Django's CSRF middleware is on, but these views opt out. Each is classified:

* ``admin-header``  - authenticated only by an ``Authorization`` / ``X-Admin-Token``
  header. A browser cannot attach that header to a cross-site request without a
  CORS preflight we do not grant, so CSRF does not apply.
* ``token-header``  - the support-chat visitor token in ``X-Support-Chat-Token``;
  same reasoning.
* ``portal-cookie`` - accepts the ``kg_portal_token`` cookie. CSRF applies. The
  cookie is ``SameSite=Lax`` (never sent on a cross-site POST/PUT/PATCH/DELETE),
  and ``api.originguard`` refuses a cookie-authenticated unsafe request whose
  Origin is not ours (defence in depth).
* ``pre-auth``      - runs before any session exists (login, OTP, recovery, the
  public purchase form, a new support thread); Turnstile / OTP gate them.

``test_csrf_registry`` fails when a view gains or loses ``@csrf_exempt`` without
an entry here. Table: docs/21-csrf-exempt-views.md.
"""

# 'module path:function' -> (class, methods, route)
EXEMPT = {
    'api/adminops.py:admin_data_quality_view': ('admin-header', 'POST', '/api/admin/data-quality/'),
    'api/adminops.py:admin_pipeline_view': ('admin-header', 'POST', '/api/admin/pipeline/'),
    'api/adminops.py:admin_system_view': ('admin-header', 'POST', '/api/admin/system/'),
    'api/chatlog.py:feedback_view': ('portal-cookie', 'POST', '/api/auth/chat-feedback/'),
    'api/chatlog.py:record_view': ('portal-cookie', 'POST', '/api/auth/chat-log/'),
    'api/feedback.py:submit_view': ('portal-cookie', 'POST', '/api/feedback/submit/'),
    'api/flags.py:admin_flags_view': ('admin-header', 'POST', '/api/admin/flags/'),
    'api/grafanaauth.py:grafana_ticket_view': ('admin-header', 'POST', '/api/admin/grafana-ticket/'),
    'api/knowledge.py:admin_kb_detail_view': ('admin-header', 'GET,POST', '/api/admin/kb/<int:article_id>/'),
    'api/knowledge.py:admin_kb_view': ('admin-header', 'GET,POST', '/api/admin/kb/'),
    'api/knowledge.py:deflect_view': ('portal-cookie', 'POST', '/api/kb/<slug:slug>/deflect/'),
    'api/knowledge.py:kb_vote_view': ('portal-cookie', 'POST', '/api/kb/<slug:slug>/vote/'),
    'api/knowledge.py:promote_request_view': ('admin-header', 'POST', '/api/admin/company-requests/<int:req_id>/promote-to-article/'),
    'api/onboarding.py:onboarding_view': ('portal-cookie', 'GET,POST', '/api/auth/onboarding/'),
    'api/orggraph_api.py:admin_reassign_root_view': ('admin-header', 'POST', '/api/admin/org/reassign-root/'),
    'api/orggraph_api.py:graph_view': ('portal-cookie', '?', '/api/org/graph/'),
    'api/orggraph_api.py:node_create_user_view': ('portal-cookie', 'POST', '/api/org/nodes/<int:node_id>/create-user/'),
    'api/orggraph_api.py:node_detail_view': ('portal-cookie', 'DELETE,PATCH', '/api/org/nodes/<int:node_id>/'),
    'api/orggraph_api.py:node_permission_view': ('portal-cookie', 'POST', '/api/org/nodes/<int:node_id>/permission/'),
    'api/orggraph_api.py:nodes_view': ('portal-cookie', 'POST', '/api/org/nodes/'),
    'api/portal.py:activity_view': ('portal-cookie', 'POST', '/api/activity/'),
    'api/portal.py:admin_companies_view': ('admin-header', 'POST', '/api/admin/companies/'),
    'api/portal.py:admin_company_access_view': ('admin-header', 'POST', '/api/admin/companies/<int:company_id>/access/'),
    'api/portal.py:admin_company_detail_view': ('admin-header', 'POST', '/api/admin/companies/<int:company_id>/'),
    'api/portal.py:admin_company_role_delete_view': ('admin-header', 'POST', '/api/admin/companies/<int:company_id>/roles/delete/'),
    'api/portal.py:admin_company_roles_view': ('admin-header', 'POST', '/api/admin/companies/<int:company_id>/roles/'),
    'api/portal.py:admin_login_view': ('pre-auth', 'POST', '/api/admin/login/'),
    'api/portal.py:admin_request_delete_view': ('admin-header', 'POST', '/api/admin/requests/<int:req_id>/delete/'),
    'api/portal.py:admin_request_status_view': ('admin-header', 'POST', '/api/admin/requests/<int:req_id>/status/'),
    'api/portal.py:admin_user_access_view': ('admin-header', 'POST', '/api/admin/users/<int:user_id>/access/'),
    'api/portal.py:admin_user_detail_view': ('admin-header', 'POST', '/api/admin/users/<int:user_id>/'),
    'api/portal.py:admin_users_view': ('admin-header', 'POST', '/api/admin/users/'),
    'api/portal.py:admin_verify_otp_view': ('pre-auth', 'POST', '/api/admin/verify-otp/'),
    'api/portal.py:login_view': ('pre-auth', 'POST', '/api/auth/login/'),
    'api/portal.py:logout_view': ('portal-cookie', 'POST', '/api/auth/logout/'),
    'api/portal.py:me_prefs_view': ('portal-cookie', 'POST', '/api/auth/me/prefs/'),
    'api/portal.py:recover_reset_view': ('pre-auth', 'POST', '/api/auth/recover/reset/'),
    'api/portal.py:recover_start_view': ('pre-auth', 'POST', '/api/auth/recover/start/'),
    'api/portal.py:resend_otp_view': ('pre-auth', 'POST', '/api/auth/resend-otp/'),
    'api/portal.py:verify_otp_view': ('pre-auth', 'POST', '/api/auth/verify-otp/'),
    'api/quota.py:ai_usage_view': ('portal-cookie', 'POST', '/api/auth/ai-usage/'),
    'api/requests_api.py:admin_company_request_detail_view': ('admin-header', 'GET,POST', '/api/admin/company-requests/<int:req_id>/'),
    'api/requests_api.py:admin_company_requests_view': ('admin-header', 'GET,POST', '/api/admin/company-requests/'),
    'api/requests_api.py:company_request_detail_view': ('portal-cookie', 'POST', '/api/company/requests/<int:req_id>/'),
    'api/requests_api.py:company_requests_view': ('portal-cookie', 'GET,POST', '/api/company/requests/'),
    'api/support_chat/views_admin.py:view': ('admin-header', 'POST', '?'),
    'api/support_chat/views_admin_inbox.py:detail_view': ('admin-header', 'GET', '(support_chat)/api/admin/support-chat/threads/<str:thread_id>/'),
    'api/support_chat/views_admin_inbox.py:list_view': ('admin-header', 'GET', '(support_chat)/api/admin/support-chat/threads/'),
    'api/support_chat/views_public.py:contact_view': ('token-header', 'PATCH', '(support_chat)/api/support-chat/threads/<str:thread_id>/contact/'),
    'api/support_chat/views_public.py:create_view': ('pre-auth', 'POST', '(support_chat)/api/support-chat/threads/'),
    'api/support_chat/views_public.py:csat_view': ('token-header', 'POST', '(support_chat)/api/support-chat/threads/<str:thread_id>/csat/'),
    'api/support_chat/views_public.py:messages_view': ('token-header', 'GET,POST', '(support_chat)/api/support-chat/threads/<str:thread_id>/messages/'),
    'api/support_chat/views_public.py:reopen_view': ('token-header', 'POST', '(support_chat)/api/support-chat/threads/<str:thread_id>/reopen/'),
    'api/support_chat/views_status.py:heartbeat_view': ('admin-header', 'POST', '(support_chat)/api/admin/support-chat/presence/heartbeat/'),
    'api/support_chat/views_status.py:presence_view': ('admin-header', 'GET,PUT', '(support_chat)/api/admin/support-chat/presence/'),
    'api/views.py:assist_feedback_view': ('portal-cookie', 'POST', '/api/assist/feedback/'),
    'api/views.py:assist_view': ('portal-cookie', 'POST', '/api/assist/'),
    'api/views.py:diagnose_view': ('portal-cookie', 'POST', '/api/diagnose/'),
    'api/views.py:feedback_pin_view': ('admin-header', 'POST', '/api/feedback/pin/'),
    'api/views.py:feedback_rate_view': ('portal-cookie', 'POST', '/api/feedback/rate/'),
    'api/views.py:purchase_request_view': ('pre-auth', 'POST', '/api/purchase-request/'),
}
