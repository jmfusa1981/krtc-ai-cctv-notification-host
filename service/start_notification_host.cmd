@echo off

set "ROOT=C:\KRTC\NotificationHost"
set "APP=%ROOT%\app"
set "PYTHON=%ROOT%\runtime\python\python.exe"

set "DJANGO_SETTINGS_MODULE=config.settings_production"
set "KRTC_PERSISTENT_ROOT=%ROOT%"

if not defined KRTC_WEB_BIND_HOST set "KRTC_WEB_BIND_HOST=127.0.0.1"
if not defined KRTC_WEB_BIND_PORT set "KRTC_WEB_BIND_PORT=8000"

if /I not "%KRTC_WEB_BIND_HOST%"=="127.0.0.1" if /I not "%KRTC_WEB_BIND_HOST%"=="localhost" (
    echo [ERROR] KRTC_WEB_BIND_HOST must be a loopback address.
    exit /b 2
)

cd /d "%APP%"

"%PYTHON%" -m waitress --listen=%KRTC_WEB_BIND_HOST%:%KRTC_WEB_BIND_PORT% --threads=8 config.wsgi:application
