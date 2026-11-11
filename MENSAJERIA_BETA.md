# Mensajería BETA de SIGED

- **Iniciar SIGED.bat** abre la aplicación y Mensajería en
  `http://127.0.0.1:8000`. Usa los usuarios y documentos del SIGED local.
- **Iniciar SIGED LAN (pruebas).bat** abre las mismas funciones en la IPv4
  privada elegida, puerto 8000. Si hay varias direcciones, seleccione la
  de la red compartida con los dispositivos. Use la URL que muestra la
  consola. HTTP y WS viajan sin cifrar, para pruebas en una red controlada.

Los dos lanzadores usan el mismo `gestor.db` y el mismo directorio
`storage`. Por defecto se encuentran junto a los lanzadores. Si existe
`GESTOR_DATA_DIR`, ambos lo respetan. Biblioteca y Mensajería usan las
cuentas y documentos que el propietario administra en SIGED.

Ambos modos montan interfaz, API y WebSocket en el mismo Uvicorn y abren
el navegador después de comprobar el login y la ruta de Mensajería.
El WebSocket usa `/mensajeria/ws` en el mismo origen HTTP. Para detener
el servidor, use Ctrl+C o el acceso **Detener SIGED**.
El entorno virtual debe incluir la dependencia `websockets` del grupo
`mensajeria-ws` que SIGED ya declara.

La beta prepara el almacén privado de Mensajería si aún no existe y
vincula por primera vez una instalación compatible mediante sus
identificadores internos. Ambos lanzadores usan `GESTOR_MENSAJERIA_DIR`
si está configurado. Por defecto, el almacén queda bajo
`%LOCALAPPDATA%\SIGED\beta\<identificador del directorio de datos>\.siged-mensajeria`,
fuera de Biblioteca. Las generaciones
incompatibles tras restauración conservan el proceso de reconciliación
existente. Las sesiones abiertas antes de habilitar Mensajería requieren
volver a iniciar sesión.

Los lanzadores identifican el modo BETA. Si `GESTOR_HTTPS_ONLY` exige HTTPS
explícitamente, el arranque HTTP se interrumpe con un mensaje. La operación
institucional sigue documentada en [Fase 7C.3](MENSAJERIA_FASE7C3.md) y
[Despliegue HTTPS](DESPLIEGUE_HTTPS.md).
