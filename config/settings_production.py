"""
KRTC AI CCTV Notification Host V5
Production settings.

Production runtime:
    DJANGO_SETTINGS_MODULE=config.settings_production
"""

import os
from pathlib import Path
from dotenv import load_dotenv


# ============================================================
# Load production environment BEFORE base settings
# ============================================================

PRODUCTION_BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(
    dotenv_path=PRODUCTION_BASE_DIR / ".env",
    override=True,
    encoding="utf-8-sig",
)


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

KRTC_DATA_DIR = Path(
    os.getenv(
        "KRTC_DATA_DIR",
        str(BASE_DIR),
    )
).resolve()

KRTC_MEDIA_DIR = Path(
    os.getenv(
        "KRTC_MEDIA_DIR",
        str(BASE_DIR / "media"),
    )
).resolve()

KRTC_LOG_DIR = Path(
    os.getenv(
        "KRTC_LOG_DIR",
        str(BASE_DIR / "logs"),
    )
).resolve()


# Ensure runtime directories exist
KRTC_DATA_DIR.mkdir(parents=True, exist_ok=True)
KRTC_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
KRTC_LOG_DIR.mkdir(parents=True, exist_ok=True)


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


