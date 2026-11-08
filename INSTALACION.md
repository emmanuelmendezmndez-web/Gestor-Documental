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

La validación admite ZIP64 y limita por defecto a 100 000 entradas, 64 GiB por
archivo y 1 TiB descomprimido en total. Ajuste estos límites al volumen y al
espacio disponible mediante `GESTOR_RESPALDO_MAX_ENTRADAS`,
`GESTOR_RESPALDO_MAX_ARCHIVO_BYTES` y `GESTOR_RESPALDO_MAX_TOTAL_BYTES` (enteros
positivos). El manifiesto sigue limitado a 16 MiB. La verificación necesita espacio
temporal para el contenido descomprimido; un corte abrupto del proceso o del
sistema puede dejar temporales que deben revisarse y retirarse de forma segura.

El servidor adquiere un bloqueo compartido al cargar `app.main`; la restauración
requiere un bloqueo exclusivo y rechaza la operación si otro servidor o restaurador
lo mantiene. El archivo `.siged-coordinacion.lock` en `GESTOR_DATA_DIR` es estable:
no lo elimine ni sustituya. Los bloqueos solo coordinan procesos que usan este
protocolo; la creación de respaldos y los comandos de usuarios, base y tareas de
eliminación también participan. Herramientas externas y versiones anteriores pueden
eludirlo. Una restauración registra sus pasos en `.siged-restauracion.json` y guarda
originales en `.siged-restauraciones` dentro de `GESTOR_DATA_DIR`; proteja esa
carpeta con los permisos institucionales del directorio de datos. Si el registro
está pendiente o no puede leerse, SIGED y los comandos participantes no arrancan:
conserve el registro, el directorio de trabajo y el respaldo previo para revisión y
recuperación manual. No borre el registro para forzar el arranque. Las restauraciones
finalizadas conservan los originales y consumen espacio hasta su revisión posterior.
Si existen archivos SQLite `-journal`, `-wal` o `-shm`, la restauración se rechaza
sin eliminarlos; revise la base detenida. El registro se vacía a disco y se sustituye
como archivo completo, pero su durabilidad ante pérdida eléctrica depende del sistema
de archivos, Windows y el almacenamiento; Windows no garantiza aquí un vaciado del
directorio. Las comprobaciones de espacio son estimaciones y no reservan el espacio.

Las nuevas restauraciones usan el registro v2. Antes del primer cambio activo se
publica un inventario inmutable `inventario.jsonl` con conjuntos separados anterior,
preparado y respaldo previo (incluye ausencias, tamaños, identidades y SHA-256).
No se equipara el archivo SQLite original con la copia de la API de respaldo.
`inicio.json` y `finalizada.json` conservan las constancias por operación; si falta
el registro principal, una operación sin finalización comprobable impide el arranque.
Un inventario histórico no se compara con los datos activos que SIGED modificó
legítimamente después de finalizar. SHA-256 no proporciona autenticidad criptográfica.

El esquema v1 sigue siendo legible: su finalización registrada no demuestra un
inventario que nunca existió. Antes de reemplazar ese registro por una nueva operación,
se conserva la constancia exacta como `finalizada-v1.json`. Las operaciones antiguas
sin constancia suficiente bloquean el arranque y requieren revisión administrativa.
No se migran ni eliminan evidencias durante la lectura.

El inventario se procesa por bloques, con límites configurables positivos:
`GESTOR_INVENTARIO_MAX_ENTRADAS` (300000), `GESTOR_INVENTARIO_MAX_BYTES` (268435456,
solo metadatos) y `GESTOR_INVENTARIO_MAX_SEGUNDOS` (3600). El lector usa memoria
acotada por el límite de entradas, líneas de hasta 64 KiB y un presupuesto agregado
para las operaciones históricas. La escritura limita la profundidad a 128 niveles.
El tiempo se controla entre lecturas: no interrumpe una llamada de E/S bloqueada.
Si se agota el presupuesto o falla la escritura, no se sustituyen datos activos y
se conservan las evidencias parciales para revisión; no se reintenta sobrescribiéndolas.
# Diagnóstico administrativo de restauración

Con SIGED detenido, ejecute `python -m app.diagnostico_restauracion --modo profundo` usando el mismo `GESTOR_DATA_DIR`. El modo `rapido` comprueba metadatos sin calcular hashes y deja el resultado sin verificar. El informe separa conjuntos y utiliza como identificador el número de línea del inventario, sin mostrar nombres de documentos ni claves. Los detalles se limitan mediante `GESTOR_DIAGNOSTICO_MAX_DETALLES` (por defecto 10000); si se excede, el resultado es incierto. Se comprueba el hash del ZIP completo, sin interpretar sus entradas. El informe es de lectura y no recupera ni declara recuperables los datos; conserve todas las evidencias para revisión. El bloqueo exclusivo impide ejecutarlo mientras SIGED u otro diagnóstico utiliza los datos. Los hashes detectan discrepancias, no acreditan autenticidad. Los límites existentes `GESTOR_INVENTARIO_MAX_ENTRADAS`, `GESTOR_INVENTARIO_MAX_BYTES` y `GESTOR_INVENTARIO_MAX_SEGUNDOS` también se aplican; `GESTOR_DIAGNOSTICO_MAX_BYTES` limita los bytes de archivos examinados (por defecto 10 GiB). Al alcanzar un límite el resultado es incierto. Los bloqueos no protegen frente a procesos que no participan en el protocolo.
