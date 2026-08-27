"""
KRTC AI CCTV Notification Host V6
Production settings.

Production runtime:
    DJANGO_SETTINGS_MODULE=config.settings_production
"""

import os
from pathlib import Path


# Environment loading and persistent-path precedence are centralized in
# config.settings. Production must not pre-load the project .env because doing
# so would make source-checkout values look like explicit process settings.

# ============================================================
# Base Django settings
# ============================================================

from .settings import *

# ============================================================
# Production static file serving
# ============================================================

_whitenoise_middleware = "whitenoise.middleware.WhiteNoiseMiddleware"

if _whitenoise_middleware not in MIDDLEWARE:

    try:
        _security_index = MIDDLEWARE.index(
            "django.middleware.security.SecurityMiddleware"
        )

        MIDDLEWARE.insert(
            _security_index + 1,
            _whitenoise_middleware,
        )

    except ValueError:

        MIDDLEWARE.insert(
            0,
            _whitenoise_middleware,
        )


STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },

    "staticfiles": {
        "BACKEND":
            "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}


# ============================================================
# Core production security
# ============================================================

DEBUG = False

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "").strip()

if not SECRET_KEY:
    raise RuntimeError(
        "DJANGO_SECRET_KEY is not configured for production."
    )


# ============================================================
# Network
# ============================================================

_allowed_hosts_raw = os.getenv(
    "DJANGO_ALLOWED_HOSTS",
    "127.0.0.1,localhost",
)

ALLOWED_HOSTS = [
    host.strip()
    for host in _allowed_hosts_raw.split(",")
    if host.strip()
]


# ============================================================
# Persistent runtime paths
# ============================================================

# Reuse the persistent path resolution from config.settings. Do not reset the
# directories back to BASE_DIR in production. Explicit KRTC_*_DIR variables can
# still override the KRTC_PERSISTENT_ROOT-derived locations in config.settings.
KRTC_PERSISTENT_ROOT = Path(KRTC_PERSISTENT_ROOT).resolve()
KRTC_CONFIG_DIR = Path(KRTC_CONFIG_DIR).resolve()
KRTC_DATA_DIR = Path(KRTC_DATA_DIR).resolve()
KRTC_MEDIA_DIR = Path(KRTC_MEDIA_DIR).resolve()
KRTC_LOG_DIR = Path(KRTC_LOG_DIR).resolve()
KRTC_BACKUP_DIR = Path(KRTC_BACKUP_DIR).resolve()


# Ensure runtime directories exist
for _runtime_dir in (KRTC_CONFIG_DIR, KRTC_DATA_DIR, KRTC_MEDIA_DIR, KRTC_LOG_DIR, KRTC_BACKUP_DIR):
    _runtime_dir.mkdir(parents=True, exist_ok=True)


# ============================================================
# Database
# ============================================================

DATABASES["default"]["ENGINE"] = "django.db.backends.sqlite3"
DATABASES["default"]["NAME"] = KRTC_DATA_DIR / "db.sqlite3"


# ============================================================
# Static files
# ============================================================

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"


# ============================================================
# Media
# ============================================================

MEDIA_URL = "/media/"
MEDIA_ROOT = KRTC_MEDIA_DIR


# ============================================================
# HTTP / HTTPS policy
# ============================================================

KRTC_ENABLE_HTTPS = (
    os.getenv("KRTC_ENABLE_HTTPS", "0").strip().lower()
    in {"1", "true", "yes", "on"}
)

if KRTC_ENABLE_HTTPS:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

    SECURE_HSTS_SECONDS = int(
        os.getenv("DJANGO_SECURE_HSTS_SECONDS", "3600")
    )

    SECURE_HSTS_INCLUDE_SUBDOMAINS = False
    SECURE_HSTS_PRELOAD = False
else:
    SECURE_SSL_REDIRECT = False
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False
    SECURE_HSTS_SECONDS = 0


SECURE_PROXY_SSL_HEADER = (
    "HTTP_X_FORWARDED_PROTO",
    "https",
)


# ============================================================
# Production marker
# ============================================================

KRTC_PRODUCTION = True


