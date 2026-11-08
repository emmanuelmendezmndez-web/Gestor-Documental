@echo off
setlocal
cd /d "%~dp0"

set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo No se encontro el entorno virtual del proyecto:
    echo   %PYTHON%
    echo.
    echo Revisa que la carpeta .venv exista junto a este archivo.
    pause
    exit /b 1
)

"%PYTHON%" -c "import uvicorn" >nul 2>&1
if errorlevel 1 (
    echo No se encontro Uvicorn en el entorno virtual del proyecto.
    echo Activa el entorno e instala las dependencias del proyecto.
    pause
    exit /b 1
)

echo Iniciando SIGED en http://127.0.0.1:8000
echo Modo local de desarrollo. No usar para acceso institucional por red.
echo Mantener la ventana abierta mientras el programa este en uso.
echo Para detener el servidor, presiona Ctrl+C.
echo.
start "" "http://127.0.0.1:8000"
set "GESTOR_HTTPS_ONLY=0"
"%PYTHON%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers

if errorlevel 1 (
    echo.
    echo El servidor se detuvo con un error. Revisa el mensaje anterior.
    pause
)

endlocal
