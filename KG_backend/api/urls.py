from django.urls import path
from . import adminops, events, recommend, requests_api, views, portal, team
from . import orggraph_api, parts, labortimes, sst

urlpatterns = [
    # Liveness probe (public, cheap, no secrets) + operational admin API.
    path('api/health/', adminops.health_view, name='health'),
    path('api/admin/data-quality/', adminops.admin_data_quality_view, name='admin_data_quality'),
    path('api/admin/system/', adminops.admin_system_view, name='admin_system'),
    path('api/admin/traffic/', adminops.admin_traffic_view, name='admin_traffic'),
    path('api/admin/pipeline/', adminops.admin_pipeline_view, name='admin_pipeline'),
    path('api/admin/vehicle-specs/', adminops.admin_vehicle_specs_view,
         name='admin_vehicle_specs'),

    # Real-time event backbone: SSE stream + REST snapshot/history companions.
    path('api/events/stream/', events.stream_view, name='events_stream'),
    path('api/events/recent/', events.recent_view, name='events_recent'),
    path('api/admin/processing-snapshot/', adminops.admin_processing_snapshot_view,
         name='admin_processing_snapshot'),
    path('api/admin/dashboard/', adminops.admin_dashboard_view, name='admin_dashboard'),

    # Company requests (manager files, admin actions; both dashboards live-update).
    path('api/company/requests/', requests_api.company_requests_view, name='company_requests'),
    path('api/company/requests/<int:req_id>/', requests_api.company_request_detail_view,
         name='company_request_detail'),
    path('api/admin/company-requests/', requests_api.admin_company_requests_view,
         name='admin_company_requests'),
    path('api/admin/company-requests/<int:req_id>/',
         requests_api.admin_company_request_detail_view, name='admin_company_request_detail'),

    # Portal auth (company seats issued by the admin).
    path('api/auth/login/', portal.login_view, name='portal_login'),
    path('api/auth/logout/', portal.logout_view, name='portal_logout'),
    path('api/auth/me/', portal.me_view, name='portal_me'),
    path('api/auth/me/prefs/', portal.me_prefs_view, name='portal_me_prefs'),
    path('api/auth/fleet/', portal.fleet_view, name='portal_fleet'),
    path('api/auth/verify-otp/', portal.verify_otp_view, name='portal_verify_otp'),
    path('api/auth/resend-otp/', portal.resend_otp_view, name='portal_resend_otp'),
    path('api/activity/', portal.activity_view, name='portal_activity'),

    # Company self-service team management (manager-gated) + employee invites.
    path('api/team/analytics/', team.team_analytics_view, name='team_analytics'),
    path('api/team/report/', team.team_report_pdf_view, name='team_report_pdf'),
    path('api/team/insights/', recommend.manager_insights_view, name='team_insights'),

    # Personalised behavioural recommendations for the logged-in portal user.
    path('api/recommendations/', recommend.recommendations_view, name='recommendations'),
    # Org-graph canvas (n8n-style). Reads open to any authed user; writes root-only.
    path('api/org/graph/', orggraph_api.graph_view, name='org_graph'),
    path('api/org/nodes/', orggraph_api.nodes_view, name='org_nodes'),
    path('api/org/nodes/<int:node_id>/', orggraph_api.node_detail_view, name='org_node_detail'),
    path('api/org/nodes/<int:node_id>/permission/', orggraph_api.node_permission_view, name='org_node_permission'),
    path('api/org/nodes/<int:node_id>/create-user/', orggraph_api.node_create_user_view, name='org_node_create_user'),
    path('api/admin/org/reassign-root/', orggraph_api.admin_reassign_root_view, name='admin_reassign_root'),
    path('api/invite/<str:token>/', team.invite_view, name='invite'),

    # Admin panel API (gated by KG_ADMIN_TOKEN; open in DEBUG without one).
    path('api/admin/login/', portal.admin_login_view, name='admin_login'),
    path('api/admin/overview/', portal.admin_overview_view, name='admin_overview'),
    path('api/admin/packages/', portal.admin_packages_view, name='admin_packages'),
    path('api/admin/requests/', portal.admin_requests_view, name='admin_requests'),
    path('api/admin/requests/<int:req_id>/status/', portal.admin_request_status_view, name='admin_request_status'),
    path('api/admin/cars/', portal.admin_cars_view, name='admin_cars'),
    path('api/admin/companies/', portal.admin_companies_view, name='admin_companies'),
    path('api/admin/companies/<int:company_id>/', portal.admin_company_detail_view, name='admin_company_detail'),
    path('api/admin/companies/<int:company_id>/access/', portal.admin_company_access_view, name='admin_company_access'),
    path('api/admin/users/', portal.admin_users_view, name='admin_users'),
    path('api/admin/users/<int:user_id>/', portal.admin_user_detail_view, name='admin_user_detail'),
    path('api/admin/users/<int:user_id>/access/', portal.admin_user_access_view, name='admin_user_access'),
    path('api/admin/activity/', portal.admin_activity_view, name='admin_activity'),
    path('api/admin/analytics/', portal.admin_analytics_view, name='admin_analytics'),

    # /api/assist/  -> local RAG + relationship-graph retrieval (POST or GET).
    # Declared before the <brand> patterns so "api" is never read as a brand.
    path('api/assist/', views.assist_view, name='assist'),
    path('api/assist/feedback/', views.assist_feedback_view, name='assist_feedback'),
    # Human-in-the-loop: 👍/👎 verdicts, expert pins, and an admin review feed.
    path('api/feedback/rate/', views.feedback_rate_view, name='feedback_rate'),
    path('api/feedback/pin/', views.feedback_pin_view, name='feedback_pin'),
    path('api/feedback/recent/', views.feedback_recent_view, name='feedback_recent'),
    # Read-only evaluation report (offline harness writes the run files).
    path('api/eval/report/', views.eval_report_view, name='eval_report'),
    # /api/diagnose/ -> deterministic per-car DTC / symptom rule engine.
    path('api/diagnose/', views.diagnose_view, name='diagnose'),
    # /api/search/ -> semantic, cross-lingual per-car site search (replaces the
    # English-only SQL LIKE search). Falls back to LIKE if the index is missing.
    path('api/search/', views.search_view, name='search'),
    # /api/purchase-request/ -> legal-entity documentation purchase request (POST).
    # Declared before the <brand> patterns so "api" is never read as a brand.
    path('api/purchase-request/', views.purchase_request_view, name='purchase_request'),

    # Parts catalog (کاتالوگ قطعات یدکی): per-vehicle EPC trees served from the
    # _parts warehouse. Same ?seg= walking contract as the manuals, plus ?cfg=
    # to pick the vehicle configuration (frame). Grant layer: 'parts'.
    path('api/parts/<str:brand_name>/<str:year>/<str:model_name>/',
         parts.parts_view, name='parts_view'),
    path('api/admin/parts/', parts.admin_parts_summary_view, name='admin_parts_summary'),
    # Per-vehicle Labor Times CSV export (paid manual content: same login +
    # per-car access gate as car_view). Declared before the <brand> catch-alls.
    path('api/labor-times/<str:brand_name>/<str:year>/<str:model_name>/',
         labortimes.labor_times_csv_view, name='labor_times_csv'),
    # Per-vehicle SST (Special Service Tools) CSV export: merges every system's
    # SST page into one deduplicated tool list. ?probe=1 answers "does this car
    # have one?" for the front-page button. Same gate as labor-times above.
    path('api/sst/<str:brand_name>/<str:year>/<str:model_name>/',
         sst.sst_csv_view, name='sst_csv'),

    # /                                            -> distinct list of brands
    path('', views.brands_list_view, name='brands_list'),

    # /brand_name/
    path('<str:brand_name>/', views.car_view, name='car_brand'),

    # /brand_name/year/
    # <str:year>, not <int:year>: legacy generated links can carry a
    # placeholder year ('unknown'); the view resolves the year tolerantly and
    # must get the request instead of a router-level 404.
    path('<str:brand_name>/<str:year>/', views.car_view, name='car_year'),

    # /brand_name/year/car_name/                  -> root nodes from car db
    # /brand_name/year/car_name/?seg=A&seg=B&...   -> walk down via repeated
    #                                                  "seg" query params (one
    #                                                  per path segment, in
    #                                                  order). Segments are not
    #                                                  appended to the URL path
    #                                                  because a node title can
    #                                                  contain a literal "/",
    #                                                  which a WSGI server
    #                                                  would otherwise decode
    #                                                  indistinguishably from a
    #                                                  real path separator.
    path('<str:brand_name>/<str:year>/<str:model_name>/', views.car_view, name='car_root'),
]
