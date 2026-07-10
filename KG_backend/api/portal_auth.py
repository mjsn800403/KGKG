"""Company-manager gate for the self-service team API.

A portal user with ``can_manage_team`` may manage the employees who report to
them (see access.manager_can_target for the per-target check). This mirrors the
shape of admin_auth.require_admin_token but for the company-facing side.
"""
from functools import wraps

from django.http import JsonResponse


def require_manager(view):
    """Attach the resolved manager as ``request.manager`` or 401/403."""
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        from .portal import portal_user  # lazy: avoids import cycle
        user = portal_user(request)
        if not user:
            return JsonResponse({'error': 'unauthorized'}, status=401)
        if not user.can_manage_team:
            return JsonResponse(
                {'error': 'برای این بخش نیاز به دسترسی مدیریت تیم دارید.'}, status=403)
        request.manager = user
        return view(request, *args, **kwargs)
    return wrapped


def require_analytics(view):
    """Gate a view behind the ``can_view_analytics`` capability."""
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        from .portal import portal_user
        user = portal_user(request)
        if not user:
            return JsonResponse({'error': 'unauthorized'}, status=401)
        if not (user.can_view_analytics or user.can_manage_team):
            return JsonResponse(
                {'error': 'برای مشاهده تحلیل‌ها دسترسی لازم را ندارید.'}, status=403)
        request.viewer = user
        return view(request, *args, **kwargs)
    return wrapped
