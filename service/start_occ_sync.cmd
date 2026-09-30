@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "ROOT=C:\KRTC\NotificationHost"
set "APP=%ROOT%\app"
set "PYTHON=%ROOT%\runtime\python\python.exe"
set "CONFIG_DIR=%ROOT%\config"
set "CONFIG_ENV=%CONFIG_DIR%\.env"
set "LOG_DIR=%ROOT%\logs"
set "STARTUP_LOG=%LOG_DIR%\occ_sync_startup.log"

set "DJANGO_SETTINGS_MODULE=config.settings_production"
set "KRTC_PERSISTENT_ROOT=%ROOT%"

if not exist "%LOG_DIR%" (
    mkdir "%LOG_DIR%" >nul 2>&1
)

call :log "============================================================"
call :log "KRTCNotificationOccSync startup begin"
call :log "ROOT=%ROOT%"
call :log "APP=%APP%"
call :log "PYTHON=%PYTHON%"
call :log "CONFIG_ENV=%CONFIG_ENV%"

if not exist "%ROOT%" (
    call :fail "ROOT directory does not exist: %ROOT%"
)

if not exist "%APP%" (
    call :fail "Application directory does not exist: %APP%"
)

if not exist "%APP%\manage.py" (
    call :fail "manage.py does not exist: %APP%\manage.py"
)

if not exist "%PYTHON%" (
    call :fail "Embedded Python does not exist: %PYTHON%"
)

if not exist "%CONFIG_DIR%" (
    call :fail "Configuration directory does not exist: %CONFIG_DIR%"
)

if not exist "%CONFIG_ENV%" (
    call :fail "Persistent production environment file does not exist: %CONFIG_ENV%"
)

cd /d "%APP%"
if errorlevel 1 (
    call :fail "Unable to change working directory to: %APP%"
)

call :log "Launcher preflight PASS"
call :log "Starting Django OCC sync service"

"%PYTHON%" "%APP%\manage.py" run_occ_sync_service --settings=config.settings_production >> "%STARTUP_LOG%" 2>&1

set "EXIT_CODE=%ERRORLEVEL%"

call :log "Django OCC sync service exited with code %EXIT_CODE%"

exit /b %EXIT_CODE%


:log
>> "%STARTUP_LOG%" echo [%date% %time%] %~1
goto :eof


:fail
call :log "STARTUP FAIL: %~1"
exit /b 1