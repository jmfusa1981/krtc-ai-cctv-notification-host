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
    "127.0.0.1,localhost,192.168.6.25"
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
    "apps.accounts.apps.AccountsConfig",
    "apps.dashboard",
    "apps.cameras",
    "apps.events",
    "apps.ai_bridge.apps.AiBridgeConfig",
    "apps.notifications.apps.NotificationsConfig",
    "apps.records",
    "apps.settings_app",
    "apps.station_api",
]


MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",

    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.accounts.middleware.SuperuserUSBKeyMiddleware",
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
                "apps.settings_app.context_processors.station_identity",
                "apps.settings_app.context_processors.current_user_identity",
                "apps.settings_app.ui_context.ui_configuration",
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

KRTC_EXTERNAL_STATION_MAPPING = {
    name.strip(): code.strip()
    for item in os.getenv("KRTC_EXTERNAL_STATION_MAPPING", "美麗島站=KRTC-ST-001,R16_左營=KRTC-ST-001").split(",")
    if "=" in item
    for name, code in [item.split("=", 1)]
}

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
CORS_ALLOWED_ORIGINS = [
    value.strip()
    for value in os.getenv(
        "DJANGO_CORS_ALLOWED_ORIGINS", "http://192.168.6.25:8000"
    ).split(",")
    if value.strip()
]


# Login / Logout
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/dashboard/"
LOGOUT_REDIRECT_URL = "/login/"

# Three-host integration identity and security. IP addresses locate services;
# these codes are the stable system identities stored in payloads and logs.
KRTC_STATION_CODE = os.getenv("KRTC_STATION_CODE", "KRTC-ST-001")
KRTC_NOTIFICATION_HOST_CODE = os.getenv("KRTC_NOTIFICATION_HOST_CODE", "NH-KRTC-ST-001")
KRTC_NOTIFICATION_HOST_IP = os.getenv("KRTC_NOTIFICATION_HOST_IP", "192.168.6.25")
KRTC_APP_VERSION = os.getenv("KRTC_APP_VERSION", "PAO-V6")
KRTC_OCC_API_TOKEN = os.getenv("KRTC_OCC_API_TOKEN", "")
KRTC_MAINTENANCE_API_BASE_URL = os.getenv(
    "KRTC_MAINTENANCE_API_BASE_URL", "http://140.124.42.72:8000"
).rstrip("/")
KRTC_REQUEST_TIMEOUT = int(os.getenv("KRTC_REQUEST_TIMEOUT", "10"))
KRTC_HEARTBEAT_INTERVAL = int(os.getenv("KRTC_HEARTBEAT_INTERVAL", "15"))
KRTC_OFFLINE_THRESHOLD = int(os.getenv("KRTC_OFFLINE_THRESHOLD", "90"))
KRTC_OCC_SYNC_ENABLED = os.getenv("KRTC_OCC_SYNC_ENABLED", "False") == "True"
KRTC_OCC_HEARTBEAT_PATH = os.getenv("KRTC_OCC_HEARTBEAT_PATH", "/api/v1/heartbeat/")
KRTC_OCC_EVENTS_PATH = os.getenv("KRTC_OCC_EVENTS_PATH", "/api/v1/events/")
KRTC_OCC_DEVICE_STATUS_PATH = os.getenv("KRTC_OCC_DEVICE_STATUS_PATH", "/api/v1/devices/sync/")
KRTC_OCC_DAILY_SYNC_PATH = os.getenv("KRTC_OCC_DAILY_SYNC_PATH", "/api/v1/daily-sync/")
KRTC_OCC_EVENT_BATCH_SIZE = int(os.getenv("KRTC_OCC_EVENT_BATCH_SIZE", "100"))
KRTC_OCC_DAILY_SYNC_HOUR = int(os.getenv("KRTC_OCC_DAILY_SYNC_HOUR", "2"))
KRTC_OCC_VERIFY_TLS = os.getenv("KRTC_OCC_VERIFY_TLS", "True") == "True"

CSRF_TRUSTED_ORIGINS = [
    value.strip()
    for value in os.getenv(
        "DJANGO_CSRF_TRUSTED_ORIGINS", "http://192.168.6.25:8000"
    ).split(",")
    if value.strip()
]


# Automatic inference-host polling service.
# It starts with the Django web process, so a separate
# `python manage.py poll_inference_hosts` terminal is not required.
INFERENCE_POLL_AUTOSTART = (
    os.getenv("INFERENCE_POLL_AUTOSTART", "True").strip().lower()
    in {"1", "true", "yes", "on"}
)
INFERENCE_POLL_INTERVAL_SECONDS = float(
    os.getenv("INFERENCE_POLL_INTERVAL_SECONDS", "5")
)
INFERENCE_POLL_EVENT_LIMIT = int(
    os.getenv("INFERENCE_POLL_EVENT_LIMIT", "100")
)
INFERENCE_POLL_EVENT_OFFSET = int(
    os.getenv("INFERENCE_POLL_EVENT_OFFSET", "0")
)
INFERENCE_POLL_STARTUP_DELAY_SECONDS = float(
    os.getenv("INFERENCE_POLL_STARTUP_DELAY_SECONDS", "2")
)


# API v1.5 zone-count current-state polling.
# /api/notify/zone_counts is not an event stream; 15 seconds matches the source update cadence.
ZONE_COUNT_POLL_AUTOSTART = (
    os.getenv("ZONE_COUNT_POLL_AUTOSTART", "True").strip().lower()
    in {"1", "true", "yes", "on"}
)
ZONE_COUNT_POLL_INTERVAL_SECONDS = float(
    os.getenv("ZONE_COUNT_POLL_INTERVAL_SECONDS", "15")
)
ZONE_COUNT_POLL_STARTUP_DELAY_SECONDS = float(
    os.getenv("ZONE_COUNT_POLL_STARTUP_DELAY_SECONDS", "4")
)
ZONE_COUNT_STALE_SECONDS = int(
    os.getenv("ZONE_COUNT_STALE_SECONDS", "45")
)

# Inference WebSocket receiver. By default it starts with the Django server.
# The standalone management command remains available for diagnostics.
INFERENCE_WS_AUTOSTART = (
    os.getenv("INFERENCE_WS_AUTOSTART", "True").strip().lower()
    in {"1", "true", "yes", "on"}
)
INFERENCE_WS_AUTOSTART_DELAY_SECONDS = float(
    os.getenv("INFERENCE_WS_AUTOSTART_DELAY_SECONDS", "3")
)
INFERENCE_WS_HOST_REFRESH_SECONDS = float(
    os.getenv("INFERENCE_WS_HOST_REFRESH_SECONDS", "30")
)
INFERENCE_WS_PATH = os.getenv("KRTC_INFERENCE_WEBSOCKET_PATH", "/ws/alerts")
INFERENCE_WS_URL = os.getenv("KRTC_INFERENCE_WEBSOCKET_URL", "")
INFERENCE_WS_TOKEN = os.getenv(
    "KRTC_INFERENCE_WEBSOCKET_TOKEN", os.getenv("INFERENCE_WS_TOKEN", "")
)
INFERENCE_WS_TOKEN_ENABLED = os.getenv("INFERENCE_WS_TOKEN_ENABLED", "False") == "True"
INFERENCE_WS_EXPECTED_SOURCE_HOST = os.getenv(
    "INFERENCE_WS_EXPECTED_SOURCE_HOST", "INF-KRTC-ST-001-01"
)
INFERENCE_WS_HEARTBEAT_TIMEOUT_SECONDS = int(
    os.getenv("INFERENCE_WS_HEARTBEAT_TIMEOUT_SECONDS", "90")
)
INFERENCE_WS_RECONNECT_MAX_SECONDS = int(
    os.getenv("INFERENCE_WS_RECONNECT_MAX_SECONDS", "30")
)
INFERENCE_WS_CATCHUP_LIMIT = int(os.getenv("INFERENCE_WS_CATCHUP_LIMIT", "100"))
INFERENCE_WS_PROCESS_BROADCASTS = os.getenv(
    "INFERENCE_WS_PROCESS_BROADCASTS", "True"
) == "True"

AUTO_BROADCAST_PROCESS_ON_IMPORT = (
    os.getenv("AUTO_BROADCAST_PROCESS_ON_IMPORT", "True").strip().lower()
    in {"1", "true", "yes", "on"}
)
AUTO_BROADCAST_EVENT_LOG_LIMIT = int(os.getenv("AUTO_BROADCAST_EVENT_LOG_LIMIT", "10"))
AUTO_BROADCAST_MAX_WORKERS = int(os.getenv("AUTO_BROADCAST_MAX_WORKERS", "4"))
AUTO_BROADCAST_COOLDOWN_SECONDS = int(
    os.getenv("AUTO_BROADCAST_COOLDOWN_SECONDS", "15")
)


# Step 20 IP Speaker playback settings
#
# Available modes:
# 1. "simulation"
#    - Does not call the real IP Speaker.
#    - Used for Dashboard / BroadcastLog workflow testing.
#
# 2. "pjsip"
#    - Uses the validated PJSIP/PJSUA backend.
#    - Calls the Speaker selected by BroadcastRule.
#    - Plays the AudioFile selected by BroadcastRule.
#
# 3. "microsip_winsound" (legacy fallback)
#    - Uses Windows SIP URI handler to trigger MicroSIP.
#    - Uses Python winsound to play local wav audio file.
#    - Requires MicroSIP audio input to be configured as Stereo Mix or CABLE Output.
#
# Keep simulation as the safe default. Real PJSIP playback is enabled only
# when BROADCAST_PLAYBACK_MODE=pjsip is explicitly set in the local .env.
BROADCAST_PLAYBACK_MODE = os.getenv(
    "BROADCAST_PLAYBACK_MODE",
    "simulation",
).strip().lower()

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
# These settings are shared by the preflight command, the controlled playback
# test command, and the Dashboard PJSIP playback adapter.
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
PJSIP_AUDIO_GAIN_PERCENT = float(os.getenv("PJSIP_AUDIO_GAIN_PERCENT", "100"))
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


# Phase 3: real Windows microphone -> PJSUA -> IP Speaker
PJSIP_MIC_CAPTURE_DEVICE = int(os.getenv("PJSIP_MIC_CAPTURE_DEVICE", "-1"))
PJSIP_MIC_PLAYBACK_DEVICE = int(os.getenv("PJSIP_MIC_PLAYBACK_DEVICE", "-1"))
PJSIP_MIC_MAX_DURATION_SECONDS = int(os.getenv("PJSIP_MIC_MAX_DURATION_SECONDS", "300"))
PJSIP_MIC_MAX_SPEAKERS = int(os.getenv("PJSIP_MIC_MAX_SPEAKERS", "4"))
PJSIP_MIC_STARTUP_TIMEOUT_SECONDS = float(os.getenv("PJSIP_MIC_STARTUP_TIMEOUT_SECONDS", "12"))

# Phase 3.2 live microphone CLI control
PJSIP_MIC_CLI_PORT = int(os.getenv("PJSIP_MIC_CLI_PORT", "23233"))
PJSIP_MIC_PER_CALL_TIMEOUT_SECONDS = int(os.getenv("PJSIP_MIC_PER_CALL_TIMEOUT_SECONDS", "10"))


# Station scheduled broadcast worker.
#
# V5 station-broadcast UI creates BroadcastSchedule rows in the database. A
# scheduler worker must be running to scan due schedules and call the normal
# speaker playback service. Keep this enabled for the PAO Windows deployment so
# schedules run after the Django host starts; set BROADCAST_SCHEDULER_AUTOSTART
# to False only when an external service runs run_broadcast_scheduler.
BROADCAST_SCHEDULER_AUTOSTART = (
    os.getenv("BROADCAST_SCHEDULER_AUTOSTART", "True").strip().lower()
    in {"1", "true", "yes", "on"}
)
BROADCAST_SCHEDULER_INTERVAL_SECONDS = int(
    os.getenv("BROADCAST_SCHEDULER_INTERVAL_SECONDS", "15")
)
BROADCAST_SCHEDULER_RUNTIME_DIR = Path(
    os.getenv("BROADCAST_SCHEDULER_RUNTIME_DIR", BASE_DIR / "runtime")
)

INFERENCE_HEALTH_STALE_SECONDS = int(os.getenv("INFERENCE_HEALTH_STALE_SECONDS", "20"))

# V6.4.3 PAO internal service watchdog.
# Complete Django process loss must be detected externally by OCC heartbeat timeout.
PAO_SERVICE_WATCHDOG_ENABLED = (
    os.getenv("PAO_SERVICE_WATCHDOG_ENABLED", "True").strip().lower()
    in {"1", "true", "yes", "on"}
)
PAO_SERVICE_WATCHDOG_STARTUP_DELAY_SECONDS = int(
    os.getenv("PAO_SERVICE_WATCHDOG_STARTUP_DELAY_SECONDS", "20")
)
PAO_SERVICE_WATCHDOG_INTERVAL_SECONDS = int(
    os.getenv("PAO_SERVICE_WATCHDOG_INTERVAL_SECONDS", "30")
)
PAO_WATCHDOG_MONITOR_INFERENCE_POLLING = (
    os.getenv("PAO_WATCHDOG_MONITOR_INFERENCE_POLLING", "True").strip().lower()
    in {"1", "true", "yes", "on"}
)
PAO_WATCHDOG_MONITOR_BROADCAST_SCHEDULER = (
    os.getenv("PAO_WATCHDOG_MONITOR_BROADCAST_SCHEDULER", "True").strip().lower()
    in {"1", "true", "yes", "on"}
)
PAO_WATCHDOG_MONITOR_OCC_SYNC_SERVICE = (
    os.getenv("PAO_WATCHDOG_MONITOR_OCC_SYNC_SERVICE", "False").strip().lower()
    in {"1", "true", "yes", "on"}
)
PAO_WATCHDOG_BROADCAST_STALE_SECONDS = int(
    os.getenv("PAO_WATCHDOG_BROADCAST_STALE_SECONDS", "60")
)

# Built-in frontend administrator (not Django Admin / superuser)
KRTC_DEFAULT_ADMIN_ENABLED = os.getenv("KRTC_DEFAULT_ADMIN_ENABLED", "True").strip().lower() in {"1", "true", "yes", "on"}
KRTC_DEFAULT_ADMIN_USERNAME = os.getenv("KRTC_DEFAULT_ADMIN_USERNAME", "admin")
KRTC_DEFAULT_ADMIN_PASSWORD = os.getenv("KRTC_DEFAULT_ADMIN_PASSWORD", "KrtcAdmin@2026")

# V6 default developer Superuser bootstrap.
# Existing accounts are never password-reset by the bootstrap command.
KRTC_DEFAULT_SUPERUSER_ENABLED = (
    os.getenv("KRTC_DEFAULT_SUPERUSER_ENABLED", "True").strip().lower()
    in {"1", "true", "yes", "on"}
)
KRTC_DEFAULT_SUPERUSER_USERNAME = os.getenv("KRTC_DEFAULT_SUPERUSER_USERNAME", "Skynet")
KRTC_DEFAULT_SUPERUSER_PASSWORD = os.getenv("KRTC_DEFAULT_SUPERUSER_PASSWORD", "ntut1234")

# V6 removable USB key second factor for Superuser developer-backend access.
# Keep disabled until provisioned with: python manage.py provision_superuser_usb_key --drive E:
KRTC_SUPERUSER_USB_REQUIRED = (
    os.getenv("KRTC_SUPERUSER_USB_REQUIRED", "False").strip().lower()
    in {"1", "true", "yes", "on"}
)
KRTC_SUPERUSER_USB_TOKEN_SHA256 = os.getenv("KRTC_SUPERUSER_USB_TOKEN_SHA256", "").strip().lower()
KRTC_SUPERUSER_USB_KEY_RELATIVE_PATH = os.getenv(
    "KRTC_SUPERUSER_USB_KEY_RELATIVE_PATH",
    r"KRTC_SUPERUSER_KEY\krtc_superuser.key",
)

# NVR event recording evidence export, based on the KRTC command document
# 260727 NVR export.cgi flow:
#   1. export.cgi?channel=&start_time=&end_time=&format=
#   2. export.cgi?ID=
#   3. export.cgi?ID=&action=download
#
# Keep simulation as the default so PAO can complete UI/workflow validation
# without touching a real NVR. Set KRTC_NVR_RECORDING_MODE=nvr for live export.
KRTC_NVR_RECORDING_MODE = os.getenv("KRTC_NVR_RECORDING_MODE", "simulation")
KRTC_NVR_DEFAULT_HOST = os.getenv("KRTC_NVR_DEFAULT_HOST", "")
KRTC_NVR_DEFAULT_PORT = int(os.getenv("KRTC_NVR_DEFAULT_PORT", "80"))
KRTC_NVR_DEFAULT_USERNAME = os.getenv("KRTC_NVR_DEFAULT_USERNAME", "")
KRTC_NVR_DEFAULT_PASSWORD = os.getenv("KRTC_NVR_DEFAULT_PASSWORD", "")
KRTC_NVR_EXPORT_FORMAT = os.getenv("KRTC_NVR_EXPORT_FORMAT", "MP4").upper()
KRTC_NVR_PRE_EVENT_SECONDS = int(os.getenv("KRTC_NVR_PRE_EVENT_SECONDS", "30"))
KRTC_NVR_POST_EVENT_SECONDS = int(os.getenv("KRTC_NVR_POST_EVENT_SECONDS", "90"))
KRTC_NVR_REQUEST_TIMEOUT = int(os.getenv("KRTC_NVR_REQUEST_TIMEOUT", "10"))

# Event snapshot localization
SNAPSHOT_DOWNLOAD_TIMEOUT_SECONDS = float(os.getenv("SNAPSHOT_DOWNLOAD_TIMEOUT_SECONDS", "8"))
SNAPSHOT_DOWNLOAD_MAX_BYTES = int(os.getenv("SNAPSHOT_DOWNLOAD_MAX_BYTES", str(12 * 1024 * 1024)))
