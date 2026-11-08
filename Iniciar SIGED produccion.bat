@echo off
setlocal
cd /d "%~dp0"

set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo No se encontro el entorno virtual junto al proyecto.
    exit /b 1
)

"%PYTHON%" -c "import uvicorn" >nul 2>&1
if errorlevel 1 (
    echo No se encontro Uvicorn en el entorno virtual.
    exit /b 1
)

rem Caddy debe ejecutarse por separado en este mismo servidor.
rem El puerto HTTP solo escucha en loopback y no se publica en la LAN.
set "GESTOR_HTTPS_ONLY=1"
echo Iniciando SIGED para proxy HTTPS local en 127.0.0.1:8000.
echo Configure y valide Caddy antes de permitir acceso institucional.
"%PYTHON%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips 127.0.0.1
if errorlevel 1 exit /b 1
endlocal
