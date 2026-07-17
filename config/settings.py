from pathlib import Path
import os
from dotenv import load_dotenv


# Base directory
BASE_DIR = Path(__file__).resolve().parent.parent


# Load environment variables
load_dotenv(BASE_DIR / ".env")


# Security settings
SECRET_KEY = os.getenv(
    "DJANGO_SECRET_KEY",
    "django-insecure-krtc-dev-secret-key-change-me"
)

DEBUG = os.getenv("DJANGO_DEBUG", "True") == "True"

ALLOWED_HOSTS = os.getenv(
    "DJANGO_ALLOWED_HOSTS",
    "127.0.0.1,localhost"
).split(",")


# Application definition
INSTALLED_APPS = [
    # Django built-in apps
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Third-party apps
    "rest_framework",
    "corsheaders",

    # Local apps
    "apps.accounts",
    "apps.dashboard",
    "apps.cameras",
    "apps.events",
    "apps.ai_bridge",
    "apps.notifications",
    "apps.records",
    "apps.settings_app",
]


MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",

    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]


ROOT_URLCONF = "config.urls"


TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [
            BASE_DIR / "templates",
        ],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]


WSGI_APPLICATION = "config.wsgi.application"


# Database
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}


# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
LANGUAGE_CODE = "zh-hant"

TIME_ZONE = "Asia/Taipei"

USE_I18N = True

USE_TZ = True


# Static files
STATIC_URL = "/static/"

STATICFILES_DIRS = [
    BASE_DIR / "static",
]

STATIC_ROOT = BASE_DIR / "staticfiles"


# Media files
MEDIA_URL = "/media/"

MEDIA_ROOT = BASE_DIR / "media"


# Default primary key field type
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# Django REST Framework
REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
}


# CORS
CORS_ALLOW_ALL_ORIGINS = True


# Login / Logout
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/dashboard/"
LOGOUT_REDIRECT_URL = "/login/"


# Step 20 IP Speaker playback settings
#
# Available modes:
# 1. "simulation"
#    - Does not call the real IP Speaker.
#    - Used for Dashboard / BroadcastLog workflow testing.
#
# 2. "microsip_winsound"
#    - Uses Windows SIP URI handler to trigger MicroSIP.
#    - Uses Python winsound to play local wav audio file.
#    - Requires MicroSIP audio input to be configured as Stereo Mix or CABLE Output.
#
# Recommended:
# Keep "simulation" first.
# After BroadcastLog workflow is confirmed, change to "microsip_winsound" for real speaker testing.
BROADCAST_PLAYBACK_MODE = "simulation"
#BROADCAST_PLAYBACK_MODE = "microsip_winsound"

BROADCAST_PLAY_AFTER_DIAL_DELAY_SECONDS = 1
BROADCAST_HANGUP_AFTER_AUDIO_MARGIN_SECONDS = 2

BROADCAST_MICROSIP_PATHS = [
    r"C:\Users\user\Desktop\MicroSIP.lnk",
    r"C:\Users\user\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\MicroSIP\MicroSIP.lnk",
    r"C:\Users\user\AppData\Local\MicroSIP\MicroSIP.exe",
    r"C:\Program Files\MicroSIP\microsip.exe",
    r"C:\Program Files (x86)\MicroSIP\microsip.exe",
]


# Step 19.5 PJSIP / PJSUA playback settings
#
# The executable and its OpenSSL DLL dependencies are installed outside Git:
#   C:\krtc-tools\pjsip\pjsua.exe
#
# Step 19.5A only uses these values for the pjsip_preflight dry-run command.
# BROADCAST_PLAYBACK_MODE remains "simulation" and no Speaker is called.
PJSIP_EXECUTABLE_PATH = os.getenv(
    "PJSIP_EXECUTABLE_PATH",
    r"C:\krtc-tools\pjsip\pjsua.exe",
)
PJSIP_LOCAL_IP = os.getenv("PJSIP_LOCAL_IP", "")
PJSIP_ADVERTISE_IP = os.getenv("PJSIP_ADVERTISE_IP", PJSIP_LOCAL_IP)
PJSIP_LOCAL_SIP_PORT_BASE = int(os.getenv("PJSIP_LOCAL_SIP_PORT_BASE", "64882"))
PJSIP_LOCAL_RTP_PORT_BASE = int(os.getenv("PJSIP_LOCAL_RTP_PORT_BASE", "4004"))
PJSIP_PORT_STEP = int(os.getenv("PJSIP_PORT_STEP", "2"))
PJSIP_LOG_DIR = BASE_DIR / "logs" / "pjsip"
PJSIP_LOG_LEVEL = int(os.getenv("PJSIP_LOG_LEVEL", "5"))
PJSIP_APP_LOG_LEVEL = int(os.getenv("PJSIP_APP_LOG_LEVEL", "4"))
PJSIP_EXTRA_WAIT_SECONDS = float(os.getenv("PJSIP_EXTRA_WAIT_SECONDS", "8"))
PJSIP_DISABLED_CODECS = [
    "speex/16000",
    "speex/8000",
    "speex/32000",
    "GSM/8000",
    "iLBC/8000",
    "G722/8000",
    "G7221/16000",
    "G7221/32000",
]
