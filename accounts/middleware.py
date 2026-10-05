"""Deny-by-default access control.

Decorating each view works right up until someone adds a view and
forgets, and the cost of forgetting here is one client's data showing up
on the open internet. So the default is inverted: everything requires a
login, and the handful of genuinely public endpoints opt out by name.
"""

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.urls import Resolver404, resolve, reverse


def login_exempt(view_func):
    """Mark a view as reachable without logging in."""
    view_func.login_exempt = True
    return view_func


class LoginRequiredMiddleware:
    #: URL names that must stay reachable anonymously.
    EXEMPT_URL_NAMES = {"login", "password_reset", "password_reset_done",
                        "password_reset_confirm", "password_reset_complete"}
    #: Prefixes handled outside our URLconf (the admin ships its own login).
    EXEMPT_PREFIXES = ("/admin/login", "/static/", "/media/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not self._is_exempt(request):
            user = getattr(request, "user", None)
            if user is None or not user.is_authenticated:
                return redirect_to_login(
                    request.get_full_path(), reverse(settings.LOGIN_URL)
                )
        return self.get_response(request)

    def _is_exempt(self, request):
        path = request.path_info
        if any(path.startswith(prefix) for prefix in self.EXEMPT_PREFIXES):
            return True
        try:
            match = resolve(path)
        except Resolver404:
            # Let Django render its own 404 rather than bouncing a typo'd
            # URL to the login page, which looks like a broken site.
            return True
        if match.url_name in self.EXEMPT_URL_NAMES:
            return True
        return getattr(match.func, "login_exempt", False)
