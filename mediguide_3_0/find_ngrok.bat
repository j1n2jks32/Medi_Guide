@echo off
setlocal
echo Searching for ngrok.exe on your system...
echo.

for %%I in (ngrok.exe) do set "NGROK_EXE=%%~$PATH:I"
if defined NGROK_EXE (
    echo Found in PATH: %NGROK_EXE%
    set NGROK_PATH=%NGROK_EXE%
    goto :found
)

echo Checking common locations:
if exist "D:\games\ngrok-v3-stable-windows-amd64\ngrok.exe" (
    echo Found: D:\games\ngrok-v3-stable-windows-amd64\ngrok.exe
    set NGROK_PATH=D:\games\ngrok-v3-stable-windows-amd64\ngrok.exe
    goto :found
)

if exist "C:\Program Files\ngrok\ngrok.exe" (
    echo Found: C:\Program Files\ngrok\ngrok.exe
    set NGROK_PATH=C:\Program Files\ngrok\ngrok.exe
    goto :found
)

if exist "C:\Program Files (x86)\ngrok\ngrok.exe" (
    echo Found: C:\Program Files (x86)\ngrok\ngrok.exe
    set NGROK_PATH=C:\Program Files (x86)\ngrok\ngrok.exe
    goto :found
)

if exist "%USERPROFILE%\Downloads\ngrok.exe" (
    echo Found: %USERPROFILE%\Downloads\ngrok.exe
    set NGROK_PATH=%USERPROFILE%\Downloads\ngrok.exe
    goto :found
)

if exist "%USERPROFILE%\Downloads\ngrok-v3-stable-windows-amd64\ngrok.exe" (
    echo Found: %USERPROFILE%\Downloads\ngrok-v3-stable-windows-amd64\ngrok.exe
    set NGROK_PATH=%USERPROFILE%\Downloads\ngrok-v3-stable-windows-amd64\ngrok.exe
    goto :found
)

echo Searching entire C: drive (this may take a moment)...
dir /s C:\ngrok.exe 2>nul | find "ngrok.exe"
echo Searching entire D: drive (this may take a moment)...
dir /s D:\ngrok.exe 2>nul | find "ngrok.exe"

echo.
echo If ngrok was found above, please copy the full path
echo If not found, please download ngrok from: https://ngrok.com/download
echo.
pause
goto :eof

:found
echo.
echo Selected Ngrok path: %NGROK_PATH%
echo.
pause
endlocal
