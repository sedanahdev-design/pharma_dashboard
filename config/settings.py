"""
Django settings for the Pharmacy Category Compliance dashboard.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name, default=False):
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-oqn!@-@s$)tkm61wd3$b)x%^4gb*%3d7w7113ioil+!a_(3=%m",
)

DEBUG = env_bool("DJANGO_DEBUG", default=False)

# When served behind a Cloudflare Tunnel (or any reverse proxy) the Host
# header will be the public hostname, so ALLOWED_HOSTS defaults to "*".
# Override with a comma separated list via DJANGO_ALLOWED_HOSTS for tighter
# security once you know your tunnel hostname.
_allowed_hosts = os.environ.get("DJANGO_ALLOWED_HOSTS", "*")
ALLOWED_HOSTS = [h.strip() for h in _allowed_hosts.split(",") if h.strip()]

# Cloudflare Tunnel terminates TLS for us and forwards plain HTTP locally,
# so trust the standard forwarded-proto header instead of forcing HTTPS here.
CSRF_TRUSTED_ORIGINS = [
    o.strip() for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()
]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True

# Render sets RENDER_EXTERNAL_HOSTNAME (e.g. pharma-dashboard.onrender.com)
# and always serves over HTTPS, so trust that origin and keep the login
# cookies HTTPS-only there without any extra configuration.
RENDER_EXTERNAL_HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if RENDER_EXTERNAL_HOSTNAME:
    if "*" not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)
    CSRF_TRUSTED_ORIGINS.append(f"https://{RENDER_EXTERNAL_HOSTNAME}")
SESSION_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", default=bool(RENDER_EXTERNAL_HOSTNAME))
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "tracking",
    "reconcile",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Makes every view login-only by default, so a page added later is
    # private unless it explicitly opts out - the safe direction for an
    # app whose entire content is two clients' private data. (Written
    # here rather than using Django 5.1's LoginRequiredMiddleware so the
    # pinned Django 5.0 in requirements.txt doesn't have to move.)
    "accounts.middleware.LoginRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "tracking.context_processors.app_version",
                "accounts.context_processors.services",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("DJANGO_DB_PATH", str(BASE_DIR / "data" / "db.sqlite3")),
    }
}

# Hosted deployments (Render + Neon Postgres) pass DATABASE_URL instead:
# Render's own disk is wiped on every deploy/restart, so a SQLite file
# there would silently lose every uploaded month. Local Docker keeps
# using the SQLite file in the data/ volume above.
if os.environ.get("DATABASE_URL"):
    import dj_database_url

    DATABASES["default"] = dj_database_url.parse(
        os.environ["DATABASE_URL"],
        conn_max_age=600,
        # Neon suspends idle databases; re-check a kept-alive connection
        # before reusing it rather than failing the first request after.
        conn_health_checks=True,
    )
    # A pooled (PgBouncer, "-pooler" host) URL can't hold the server-side
    # cursors that QuerySet.iterator() uses across transactions.
    if "-pooler" in os.environ["DATABASE_URL"]:
        DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Arabic, right-to-left interface as requested. FORMAT_MODULE_PATH
# points at config/formats/ar/formats.py, which restores "." as the
# decimal separator - Django's stock ar locale writes 29.83 as "29,83",
# which reads as a thousands separator next to the source spreadsheets.
LANGUAGE_CODE = "ar"
FORMAT_MODULE_PATH = ["config.formats"]
USE_THOUSAND_SEPARATOR = False
TIME_ZONE = os.environ.get("DJANGO_TIME_ZONE", "Asia/Baghdad")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "data" / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Uploaded workbooks can be sizeable (tens of thousands of rows) - raise the
# in-memory upload cap a bit above Django's 2.5MB default.
DATA_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024

# Everything in this app is private data belonging to one account or the
# other, so there is no anonymous page at all beyond the login form
# itself (enforced by LoginRequiredMiddleware above, not by remembering
# to decorate every view).
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "login"

# A session lasts a day of *inactivity* (refreshed on every request), so
# a long working session is never interrupted mid-upload but a machine
# left alone overnight asks for the password again.
SESSION_COOKIE_AGE = 60 * 60 * 24
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
CSRF_COOKIE_HTTPONLY = False
SESSION_COOKIE_SAMESITE = "Lax"
