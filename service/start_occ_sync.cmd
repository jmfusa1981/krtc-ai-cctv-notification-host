@echo off

set "ROOT=C:\KRTC\NotificationHost"
set "APP=%ROOT%\app"
set "PYTHON=%ROOT%\runtime\python\python.exe"

set "DJANGO_SETTINGS_MODULE=config.settings_production"
set "KRTC_RUNTIME_ROOT=%ROOT%"

cd /d "%APP%"

"%PYTHON%" "%APP%\manage.py" run_occ_sync_service --settings=config.settings_production