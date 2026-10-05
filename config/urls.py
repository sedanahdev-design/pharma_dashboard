from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from accounts.middleware import login_exempt
from accounts.views import home

urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "login/",
        login_exempt(
            auth_views.LoginView.as_view(
                template_name="registration/login.html", redirect_authenticated_user=True
            )
        ),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    # "/" is a router, not a page: it sends each account into the service
    # it actually has (see accounts.views.home).
    path("", home, name="home"),
    path("categories/", include("tracking.urls")),
    path("reconcile/", include("reconcile.urls")),
]
