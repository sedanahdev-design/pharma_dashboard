"""Decorators that gate a whole service behind one profile flag."""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from .models import profile_for


def _service_required(flag_name):
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def _wrapped(request, *args, **kwargs):
            profile = profile_for(request.user)
            if profile is None or not getattr(profile, flag_name, False):
                # 403 rather than a redirect: a user who lands here typed
                # or bookmarked a URL for a service they don't have, and
                # silently bouncing them to a page they *do* have makes it
                # look like the link is broken instead of forbidden.
                raise PermissionDenied("هذه الخدمة غير متاحة لحسابك.")
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator


tracking_required = _service_required("can_use_tracking")
reconcile_required = _service_required("can_use_reconcile")
