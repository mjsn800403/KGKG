from django.urls import path
from . import views

urlpatterns = [
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
