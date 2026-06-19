from django.urls import path
from . import views

urlpatterns = [
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
