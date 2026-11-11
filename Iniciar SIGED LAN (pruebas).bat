@echo off
setlocal
cd /d "%~dp0" || exit /b 1

set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo No se encontro el entorno virtual junto al proyecto.
    pause
    exit /b 1
)

"%PYTHON%" -m app.arranque --beta-lan %*
if errorlevel 1 (
    echo SIGED BETA LAN no pudo iniciarse. Revise el mensaje anterior.
    pause
    exit /b 1
)
endlocal
