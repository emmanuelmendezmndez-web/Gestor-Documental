# Instalación y mantenimiento de SIGED en Windows

Estas instrucciones parten de una copia nueva del repositorio. No copie una
carpeta `.venv` desde otro equipo: `uv sync` crea o sincroniza el entorno de la
copia actual. SIGED se ejecuta desde la carpeta del proyecto; estos archivos no
generan todavía un instalador de escritorio.

## Requisitos

- Windows, `uv` y Python 3.13. La versión comprobada es Python 3.13.15;
  `.python-version` solicita la serie 3.13. El manifiesto admite Python 3.11 o
  superior, pero esas versiones no forman parte de la prueba de instalación.
- Acceso a los paquetes indicados en `uv.lock`, ya sea mediante PyPI o una
  caché de `uv` previamente preparada.
- LibreOffice para convertir DOCX, XLSX y PPTX en vistas previas PDF. Puede
  localizarse en `PATH`, en las ubicaciones habituales de Windows o mediante
  la variable `LIBREOFFICE_PATH` con la ruta completa a `soffice.exe`.

## Preparación

Abra PowerShell en una copia nueva del proyecto y ejecute:

```powershell
uv sync --locked
```

El comando instala solamente los paquetes de producción en `.venv`. `--locked`
exige que el bloqueo coincida con el manifiesto. Para añadir herramientas:

```powershell
uv sync --locked --group pruebas
uv sync --locked --all-groups
```

El primer comando añade HTTPX para las pruebas. El segundo añade también Ruff
y Locust. Los grupos están separados en `pyproject.toml`. `uv sync` sincroniza
el entorno de la copia y puede retirar paquetes que no figuren en los grupos
seleccionados; no lo ejecute sobre un entorno que desee conservar sin cambios.

## Datos, primer usuario y arranque

Opcionalmente, configure una carpeta de datos antes de crear usuarios y de
arrancar SIGED. Si no configura `GESTOR_DATA_DIR`, se utiliza la carpeta del
proyecto. Use la misma configuración en cada arranque y en los comandos de
respaldo:

```powershell
$env:GESTOR_DATA_DIR = 'C:\Ruta\Privada\SIGED-Datos'
.\.venv\Scripts\python.exe -m app.crear_usuario
$env:GESTOR_HTTPS_ONLY = '0'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

El primer comando de Python crea la base si es necesario y solicita los datos
de la primera cuenta; seleccione el rol `admin`. El servidor inicializa las
carpetas de almacenamiento y la base cuando hace falta. Abra
`http://127.0.0.1:8000` en el navegador.

Si no se establece `GESTOR_SECRET_KEY`, SIGED genera `.secret_key` en el
directorio de datos. Conserve esa clave junto con los respaldos protegidos. Si
se usa `GESTOR_SECRET_KEY`, conserve la configuración correspondiente. La
variable `GESTOR_HTTPS_ONLY` activa la marca segura de la cookie cuando el
servicio se utiliza detrás de HTTPS. La caché de previsualizaciones se guarda
bajo `LOCALAPPDATA` cuando está definida.

`Iniciar SIGED.bat` es para desarrollo local: escucha solo en `127.0.0.1:8000`,
desactiva la marca `Secure` de la cookie en ese proceso y no acepta encabezados
de proxy. Use una carpeta de datos ficticia separada de la institucional.

Para la preparación de producción HTTPS con Caddy consulte [DESPLIEGUE_HTTPS.md](DESPLIEGUE_HTTPS.md).
No habilite acceso institucional a la aplicación hasta completar esa configuración
y sus comprobaciones.

## Pruebas y respaldo

Para ejecutar la suite, instale el grupo `pruebas` y use:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Las pruebas crean bases y archivos ficticios temporales. No dirija herramientas
de carga a una instalación con datos reales. `locustfile.py` está disponible
mediante el grupo `carga` y utiliza las variables `SIGED_LOCUST_USUARIO` y
`SIGED_LOCUST_PASSWORD` con una cuenta ficticia de la instancia de pruebas.

Los comandos de respaldo utilizan el directorio de datos configurado:

```powershell
.\.venv\Scripts\python.exe -m app.respaldo crear
.\.venv\Scripts\python.exe -m app.respaldo verificar C:\Ruta\copia.zip
```

Los ZIP contienen documentos y la clave de sesión y no están cifrados: guárdelos
en un lugar protegido. Para una captura integral de los archivos adicionales de
`storage`, detenga SIGED antes de crear el respaldo. La restauración requiere
detener SIGED y usar `python -m app.respaldo restaurar ARCHIVO.zip --confirmar`;
esta operación reemplaza los datos de la instalación seleccionada. Revise las
advertencias y limitaciones descritas en `app/respaldo.py` antes de ejecutarla.
