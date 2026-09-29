@echo off

set "ROOT=C:\KRTC\NotificationHost"
set "APP=%ROOT%\app"
set "PYTHON=%ROOT%\runtime\python\python.exe"

set "DJANGO_SETTINGS_MODULE=config.settings_production"
set "KRTC_PERSISTENT_ROOT=%ROOT%"

cd /d "%APP%"

"%PYTHON%" -m waitress --listen=0.0.0.0:8000 --threads=8 config.wsgi:application
