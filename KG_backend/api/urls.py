from django.urls import path
from . import views, portal

urlpatterns = [
    # Portal auth (company seats issued by the admin).
    path('api/auth/login/', portal.login_view, name='portal_login'),
    path('api/auth/logout/', portal.logout_view, name='portal_logout'),
    path('api/auth/me/', portal.me_view, name='portal_me'),
    path('api/activity/', portal.activity_view, name='portal_activity'),
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

    # /                                            -> distinct list of brands
    path('', views.brands_list_view, name='brands_list'),

    # /brand_name/
    path('<str:brand_name>/', views.car_view, name='car_brand'),

    # /brand_name/year/
    path('<str:brand_name>/<int:year>/', views.car_view, name='car_year'),

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
    path('<str:brand_name>/<int:year>/<str:model_name>/', views.car_view, name='car_root'),
]
