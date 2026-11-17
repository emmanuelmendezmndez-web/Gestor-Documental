@echo off
setlocal
cd /d "%~dp0" || exit /b 1

set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo No se encontro el entorno virtual junto al proyecto.
    pause
    exit /b 1
)

rem Clippy IA: usa 0 para volver al chat con reglas locales.
if not defined NEXUSGRID_CLIPPY_SPACY_FUNCIONAL set "NEXUSGRID_CLIPPY_SPACY_FUNCIONAL=1"
rem * habilita todas las cuentas autenticadas. Tambien admite una lista de IDs.
if not defined NEXUSGRID_CLIPPY_SPACY_USUARIOS set "NEXUSGRID_CLIPPY_SPACY_USUARIOS=*"

"%PYTHON%" -m app.arranque --beta-lan %*
if errorlevel 1 (
    echo SIGED BETA LAN no pudo iniciarse. Revise el mensaje anterior.
    pause
    exit /b 1
)
endlocal
