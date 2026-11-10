@echo off
setlocal
cd /d "%~dp0"

set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo No se encontro el entorno virtual junto al proyecto.
    pause
    exit /b 1
)

rem No se anula una configuracion explicita que exija cookies Secure.
if defined GESTOR_HTTPS_ONLY if /I not "%GESTOR_HTTPS_ONLY%"=="0" (
    echo GESTOR_HTTPS_ONLY ya esta configurado y no se modificara.
    echo Este modo HTTP necesita que la variable este ausente o sea 0.
    echo Use el arranque de produccion con HTTPS si necesita cookies Secure.
    pause
    exit /b 1
)

"%PYTHON%" -c "import uvicorn" >nul 2>&1
if errorlevel 1 (
    echo No se encontro Uvicorn en el entorno virtual del proyecto.
    pause
    exit /b 1
)

echo.
echo MODO DE PRUEBAS LAN: SIGED escuchara en TODAS las interfaces, puerto 8000.
echo La conexion sera HTTP sin cifrar: credenciales, cookie y documentos
echo pueden ser observados por terceros en la red. La cookie no sera Secure.
echo No usar para produccion ni datos sensibles. CSRF y permisos siguen activos.
echo Se usaran los datos habituales de SIGED o los indicados por GESTOR_DATA_DIR.
echo Detenga cualquier instancia de SIGED que ya use el puerto 8000.
echo.
choice /c SN /n /m "Iniciar este modo temporal de pruebas LAN? [S/N]: "
if errorlevel 2 exit /b 0
if errorlevel 1 goto iniciar
exit /b 1

:iniciar
echo.
echo Obtenga la IPv4 de Wi-Fi con ipconfig y abra http://IPv4:8000 en el telefono.
echo Mantenga esta ventana abierta. Para detener el servidor use Ctrl+C.
"%PYTHON%" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-proxy-headers
if errorlevel 1 (
    echo.
    echo El servidor no pudo iniciarse o termino con un error.
    echo Revise si el puerto 8000 esta ocupado y consulte el mensaje anterior.
    pause
    exit /b 1
)
endlocal
