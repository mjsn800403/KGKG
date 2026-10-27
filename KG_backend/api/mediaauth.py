"""nginx ``auth_request`` gate for ``/kg-api/media/``.

Manual images, wiring-diagram viewers and parts art are paid content served
straight off disk by nginx. Before each file nginx asks this view (result cached
~60s per token+car in nginx): 204 = serve, 401 = not logged in, 403 = the car
is not in the user's subscription.

The first path segment is the car's media folder. It is the catalog
``car_name`` or the car DB stem; folders that belong to no single car
(``_parts_assets``, ``_store``, ...) only need a login.

nginx passes the raw ``$request_uri`` but serves the *normalized* path: it
decodes %XX, resolves ``.``/``..`` and merges slashes before ``alias`` picks the
file. The folder must be read from that same normalized path, or
``/_parts_assets/../<other car>/x.png`` is authorized as ``_parts_assets`` and
served as ``<other car>``.
"""
import posixpath
from pathlib import PurePosixPath
from urllib.parse import unquote

from django.http import HttpResponse

PREFIX = '/kg-api/media/'


def _folder(uri):
    """Car folder of the file nginx will serve for ``uri``; '' for the media
    root; None when the path is not under the media prefix once normalized."""
    path = unquote((uri or '').split('?', 1)[0])
    if '\x00' in path:
        return None
    path = posixpath.normpath('/' + path.lstrip('/'))
    if path + '/' == PREFIX:
        return ''
    if not path.startswith(PREFIX):
        return None
    return path[len(PREFIX):].split('/', 1)[0]


def media_auth_view(request):
    from .access import user_can_open_car
    from .models import Car
    from .portal import portal_user

    user = portal_user(request)
    if not user:
        return HttpResponse(status=401)
    folder = _folder(request.META.get('HTTP_X_ORIGINAL_URI'))
    if folder is None:
        # No media path to judge (header missing, or it normalizes outside the
        # media root): refuse rather than guess.
        return HttpResponse(status=403)
    if not folder or folder.startswith('_'):
        return HttpResponse(status=204)
    cars = list(Car.objects.filter(car_name=folder))
    if not cars:
        cars = [c for c in Car.objects.filter(db_address__contains=folder)
                if PurePosixPath(c.db_address).stem == folder]
    if not cars:
        # A folder we cannot tie to one car: a login is still required.
        return HttpResponse(status=204)
    if any(user_can_open_car(user, c) for c in cars):
        return HttpResponse(status=204)
    return HttpResponse(status=403)
