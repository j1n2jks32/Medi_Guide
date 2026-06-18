@echo off
setlocal
echo Starting MediGuide Server...

set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
set "PY_EXE=python"
if exist "%PROJECT_DIR%\.venv\Scripts\python.exe" set "PY_EXE=%PROJECT_DIR%\.venv\Scripts\python.exe"

echo Checking Python dependencies (selenium, webdriver-manager, apscheduler)...
"%PY_EXE%" -c "import selenium, webdriver_manager, apscheduler" >nul 2>&1
if %errorlevel%==0 (
    echo Python dependencies already installed.
) else (
    echo Installing selenium, webdriver-manager, and apscheduler...
    "%PY_EXE%" -m pip install selenium webdriver-manager apscheduler
    if errorlevel 1 (
        echo ERROR: Failed to install selenium/webdriver-manager/apscheduler.
        echo Try manually: "%PY_EXE%" -m pip install selenium webdriver-manager apscheduler
        goto :done
    )
)

echo Checking Ollama (port 11434)...
netstat -ano | findstr ":11434" | findstr "LISTENING" >nul
if %errorlevel%==0 (
    echo Ollama already running on port 11434. Skipping start.
) else (
    echo Starting Ollama AI...
    start "MediGuide Ollama" cmd /k ollama serve
    timeout /t 3 >nul
)

echo Checking Flask backend (port 5000)...
netstat -ano | findstr ":5000" | findstr "LISTENING" >nul
if %errorlevel%==0 (
    echo Backend already running on port 5000. Skipping start.
) else (
    echo Starting Flask Backend...
    start "MediGuide Backend" "%PY_EXE%" "%PROJECT_DIR%\backend\app.py"
    timeout /t 3 >nul
)

set /a BACKEND_WAIT=0
:wait_backend
netstat -ano | findstr ":5000" | findstr "LISTENING" >nul
if %errorlevel%==0 goto backend_ready
set /a BACKEND_WAIT+=1
if %BACKEND_WAIT% GEQ 8 goto backend_not_ready
timeout /t 1 >nul
goto wait_backend

:backend_ready
echo Backend is listening on port 5000.

echo.
echo Checking for Ngrok...
set "NGROK_EXE="

for %%I in (ngrok.exe) do set "NGROK_EXE=%%~$PATH:I"

if defined NGROK_EXE (
    echo Found Ngrok in PATH: %NGROK_EXE%
    goto :start_ngrok
)

if exist "D:\games\ngrok-v3-stable-windows-amd64\ngrok.exe" (
    echo Found Ngrok in D:\games
    set "NGROK_EXE=D:\games\ngrok-v3-stable-windows-amd64\ngrok.exe"
    goto :start_ngrok
)

if exist "%USERPROFILE%\Downloads\ngrok-v3-stable-windows-amd64\ngrok.exe" (
    echo Found Ngrok in Downloads folder
    set "NGROK_EXE=%USERPROFILE%\Downloads\ngrok-v3-stable-windows-amd64\ngrok.exe"
    goto :start_ngrok
)

if exist "C:\Program Files\ngrok\ngrok.exe" (
    echo Found Ngrok in Program Files
    set "NGROK_EXE=C:\Program Files\ngrok\ngrok.exe"
    goto :start_ngrok
)

if exist "C:\Program Files (x86)\ngrok\ngrok.exe" (
    echo Found Ngrok in Program Files (x86)
    set "NGROK_EXE=C:\Program Files (x86)\ngrok\ngrok.exe"
    goto :start_ngrok
)

goto :ngrok_not_found

:start_ngrok
tasklist /FI "IMAGENAME eq ngrok.exe" | find /I "ngrok.exe" >nul
if %errorlevel%==0 (
    echo Ngrok already running. Skipping start.
) else (
    echo Starting Ngrok Tunnel...
    start "MediGuide Ngrok" "%NGROK_EXE%" http 127.0.0.1:5000
)
goto :ngrok_done

:backend_not_ready
echo.
echo ERROR: Backend is not listening on 127.0.0.1:5000.
echo Check the backend window for traceback/errors and restart after fixing it.
goto :done

:ngrok_not_found
echo Ngrok not found in common locations.
echo Install from: https://ngrok.com/download

:ngrok_done

echo.
echo ===============================
echo MediGuide AI is now running!
echo ===============================

:done
endlocal
