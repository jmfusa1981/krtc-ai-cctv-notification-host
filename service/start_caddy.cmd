@echo off

set "ROOT=C:\KRTC\NotificationHost"
set "CADDY=%ROOT%\caddy\caddy.exe"
set "CADDYFILE=%ROOT%\service\Caddyfile"

if not defined KRTC_TLS_SITE if exist "%ROOT%\config\https_site.txt" set /p KRTC_TLS_SITE=<"%ROOT%\config\https_site.txt"
if not defined KRTC_TLS_SITE set "KRTC_TLS_SITE=https://localhost"
if not defined KRTC_CADDY_LOG_PATH set "KRTC_CADDY_LOG_PATH=%ROOT%\logs\caddy\access.log"

set "XDG_DATA_HOME=%ROOT%\caddy\data"
set "XDG_CONFIG_HOME=%ROOT%\caddy\config"

if not exist "%ROOT%\logs\caddy" mkdir "%ROOT%\logs\caddy"
if not exist "%XDG_DATA_HOME%" mkdir "%XDG_DATA_HOME%"
if not exist "%XDG_CONFIG_HOME%" mkdir "%XDG_CONFIG_HOME%"

if not exist "%CADDY%" (
    echo [ERROR] Caddy executable not found: %CADDY%
    exit /b 2
)

"%CADDY%" run --config "%CADDYFILE%" --adapter caddyfile
