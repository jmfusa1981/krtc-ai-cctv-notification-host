@echo off
setlocal
net session >nul 2>&1
if not "%errorlevel%"=="0" (
  echo [KRTC] This recovery tool requires Windows Administrator privileges.
  echo Right-click this file and choose "Run as administrator".
  pause
  exit /b 1
)

set "PROJECT="
if exist "C:\KRTC\NotificationHost\manage.py" set "PROJECT=C:\KRTC\NotificationHost"
if exist "C:\KRTC\NotificationHost\app\manage.py" set "PROJECT=C:\KRTC\NotificationHost\app"
if exist "%USERPROFILE%\krtc_notification_host_v6\manage.py" set "PROJECT=%USERPROFILE%\krtc_notification_host_v6"

if "%PROJECT%"=="" (
  echo [KRTC] Notification Host project/runtime was not found.
  pause
  exit /b 1
)

set "PYTHON="
if exist "C:\KRTC\NotificationHost\runtime\python\python.exe" set "PYTHON=C:\KRTC\NotificationHost\runtime\python\python.exe"
if exist "%PROJECT%\venv\Scripts\python.exe" set "PYTHON=%PROJECT%\venv\Scripts\python.exe"

if "%PYTHON%"=="" (
  echo [KRTC] Bundled Python runtime was not found.
  pause
  exit /b 1
)

echo.
echo KRTC Superuser USB Emergency Recovery
echo -------------------------------------
echo This will disable USB enforcement on THIS host only.
echo The USB Master Key itself will not be deleted.
echo.
set /p CONFIRM=Type DISABLE to continue: 
if /I not "%CONFIRM%"=="DISABLE" (
  echo Cancelled.
  pause
  exit /b 0
)

cd /d "%PROJECT%"
"%PYTHON%" manage.py disable_superuser_usb_key
if errorlevel 1 (
  echo [KRTC] Recovery failed.
  pause
  exit /b 1
)

echo.
echo [KRTC] USB enforcement disabled successfully.
echo Restart the KRTC Notification Host service if required.
pause
