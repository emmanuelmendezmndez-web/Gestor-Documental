@echo off
setlocal
cd /d "%~dp0" || exit /b 1

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

"%PYTHON%" -m app.arranque --beta-local %*

if errorlevel 1 (
    echo.
    echo El servidor se detuvo con un error. Revisa el mensaje anterior.
    pause
    exit /b 1
)

endlocal
