"""Flat-rate manual ("زمان استاندارد تعمیراتی") data sets.

A set is a model-family workbook (LTS hours table + the two preparation
reference sheets: type-of-operation codes and car-model codes) converted to
JSON under ``Database_warehouse/_frm/<slug>.json``. It is attached to a model
family on the brand/year browse page, not to one trim, so access is granted to
anyone who can open at least one car of that family in the listed years.
"""
import json
import os

from django.conf import settings

# slug -> (brand, family prefix, years whose cars unlock it)
FRM_SETS = {
    'toyota-corolla-cross': ('Toyota', 'Corolla Cross', (2025,)),
}


def _path(slug):
    base = os.path.join(str(settings.BASE_DIR), 'Database_warehouse', '_frm')
    return os.path.join(base, '%s.json' % slug)


def frm_view(request, slug):
    from django.http import JsonResponse
    from .models import Car
    from .access import user_can_open_car
    from .portal import portal_user

    user = portal_user(request)
    if not user:
        return JsonResponse({'error': 'unauthorized'}, status=401)
    spec = FRM_SETS.get(slug)
    if spec is None or not os.path.exists(_path(slug)):
        return JsonResponse({'error': 'not found'}, status=404)
    brand, family, years = spec
    cars = Car.objects.filter(brand_name__iexact=brand,
                              car_name__istartswith=family, year__in=years)
    if not any(user_can_open_car(user, c) for c in cars):
        return JsonResponse(
            {'error': 'forbidden',
             'detail': 'دسترسی به مستندات این خودرو در اشتراک شما نیست.'},
            status=403)
    with open(_path(slug), encoding='utf-8') as fh:
        data = json.load(fh)
    part = request.GET.get('part')
    if part in ('lts', 'car_models', 'op_types'):
        data = {k: v for k, v in data.items() if not isinstance(v, dict) or k == part}
    return JsonResponse(data, json_dumps_params={'ensure_ascii': False})
