# Arranque unificado de Mensajería en SIGED

Para los lanzadores HTTP de demostración, consulte [Mensajería BETA](MENSAJERIA_BETA.md).
Este documento conserva la preparación para la futura operación institucional HTTPS/WSS.

## Estado de activación

**Preparada, con activación protegida.** La revisión partió de `35f8236`
(`mensajeria-7c2-estable`). En este equipo, Caddy no apareció en PATH,
como proceso ni como servicio identificable. En el inventario de Windows
solo escuchaba `127.0.0.1:8000` entre los puertos 80, 443, 8000 y 8001.
La instancia preexistente quedó intacta. El firewall estaba activo en sus
tres perfiles y la consulta no encontró reglas entrantes habilitadas con
nombre SIGED o Caddy. Esto no acredita el acceso desde la LAN. El equipo
no tenía configurados el nombre público, los PEM ni la confianza de
clientes para esta instalación.

## Cómo arranca

`Iniciar SIGED.bat` resuelve la carpeta propia, usa
`.venv\Scripts\python.exe` y ejecuta `app.arranque`. La aplicación ASGI
sigue siendo `app.main:app`. Se usa un trabajador Uvicorn en
`127.0.0.1:8000`, con reserva exclusiva del puerto. El navegador se
abre después de un sondeo HTTP. El acceso `iniciar_siged.vbs` muestra
esa misma consola para que se puedan leer los errores.

Con la activación operativa expresamente configurada, el lanzador:

1. Comprueba dependencias WebSocket y la configuración de Caddy. Verifica
   que se puedan reservar las bases SQLite, que el esquema privado sea
   reconocible y que la generación esté reconciliada. El sondeo no cambia
   filas, crea identidades ni migra bases.
2. Reutiliza una instancia Caddy ya administrada y en ejecución. Si no
   hay servicio ni proceso, reserva de prueba el puerto 443 e inicia
   Caddy con el ejemplo incluido, en un Job de Windows que protege la
   vida del proceso hijo. Un servicio instalado pero detenido se informa
   como incidencia y queda bajo su mecanismo de administración.
3. Comprueba TLS con la confianza del sistema y el nombre configurado.
   Monta en la misma aplicación las rutas HTTP, WebSocket y la interfaz.
   Conserva un solo origen exacto, cookies Secure, HttpOnly y SameSite
   Lax, y confiar en encabezados proxy únicamente desde `127.0.0.1`.
4. Comprueba que el proxy alcanza esta instancia por HTTPS, que el login
   emite la cookie esperada y que API y Upgrade rechazan el acceso
   anónimo. Estos son sondeos de arranque. La prueba de WSS autenticado
   y el flujo entre clientes son parte de la validación de despliegue.

El menú y la campana de Mensajería requieren permiso `ver`. La seguridad
de sesiones, permisos, vigencias, descargas y vistas se aplica en el
servidor. El transporte WebSocket conserva sus límites de Fase 6 y el
flujo de Fase 7C.1.

Si falla un requisito antes del montaje, el lanzador explica el motivo
y continúa en HTTP de loopback con Mensajería deshabilitada, siempre
que la política explícita de cookies permita ese modo. Con
`Host` local restringido, un proxy que conserve el nombre público no
puede publicar el arranque de respaldo. Con
`GESTOR_HTTPS_ONLY=1` se conserva la exigencia de HTTPS. Si falla el
sondeo tras el montaje, se cierra la instancia y se evita abrir el
navegador. Una caída del Caddy iniciado por SIGED cierra Uvicorn. Un
servicio Caddy administrado por Windows conserva su ciclo de vida
independiente.

Para cerrar, usar **Ctrl+C** o el acceso **Detener SIGED**. La señal de
Windows corresponde al proyecto y al puerto y pide a Uvicorn un cierre
controlado. Solo el Caddy iniciado por el lanzador se detiene con SIGED.
Para una prueba local con datos ficticios se puede usar el mismo
`.bat` con `--sin-navegador --puerto-local <puerto>`. El puerto
alternativo exige modo local y un `GESTOR_DATA_DIR` separado.
Se puede detener esa prueba
pasando `--detener --puerto-local <puerto>` al módulo `app.arranque`.

## Activación después de validar la instalación

El valor `SIGED_MENSAJERIA_OPERATIVA=1` es la habilitación única. Su
ausencia o el valor `0` mantienen el modo habitual local. El valor
`1` lo establece el administrador una vez que el despliegue ha pasado
las comprobaciones de red. Los argumentos experimentales anteriores
siguen disponibles para laboratorio.

- Configure `SIGED_HOST` con el nombre DNS o IPv4 estable que usarán los
  clientes, sin esquema, puerto ni ruta. Proporcione `SIGED_CERT` y
  `SIGED_KEY` como rutas absolutas a los PEM autorizados. Use un SAN
  que coincida con el nombre o IP y una cadena válida.
- Configure `GESTOR_MENSAJERIA_DIR` con la raíz privada ya inicializada
  y reconciliada. La preparación de identidades se hace mediante los
  procedimientos existentes, fuera del arranque habitual.
- Use `Caddyfile.ejemplo` con certificado suministrado. Conserva Host
  público, reemplaza las cabeceras de IP y esquema y reenvía a
  `127.0.0.1:8000`. El ejemplo tiene `auto_https off` y `admin off`:
  sirve HTTPS en 443 sin redirección HTTP ni API de recarga. Para
  aplicar cambios, reinicie Caddy por su mecanismo de administración.
  Si Caddy ya es un servicio, compruebe su configuración real. Alinee
  el límite HTTP del servicio con `GESTOR_MAX_CUERPO_BYTES`.
- Distribuya el certificado público de la CA emisora por el procedimiento
  institucional autorizado si los clientes aún no confían en ella.
  Compruebe cadena, SAN y vigencia desde el servidor, otra PC y Android.
  Si la CA es local, distribuya solo su certificado público y conserve
  protegida su clave privada.
- En la LAN, pruebe acceso HTTPS, WSS autenticado, Host/Origin, cookies,
  CSRF, multipart, descargas, recepción y recuperación tras reiniciar
  el proxy. Compruebe visibilidad por rol, cierre de sesión, varios
  clientes y la interoperabilidad desde los dispositivos reales.

Para desactivar, retire `SIGED_MENSAJERIA_OPERATIVA` o póngala en `0`
y reinicie. Esto conserva las bases y referencias. Si hay que mantener
el HTTPS anterior de Biblioteca y Expedientes, el lanzador existente
`Iniciar SIGED produccion.bat` sigue iniciando SIGED con el Caddy
administrado por separado y Mensajería deshabilitada. El arranque HTTP
LAN de pruebas no cambia.

## Resultados del laboratorio local

- Se ejecutó el `.bat` real desde otro directorio con datos ficticios y
  un puerto alternativo. Se comprobó conflicto de puerto, rechazo de un
  segundo arranque, rutas de Mensajería ausentes, cierre por señal y
  reinicio. La selección del navegador tras el sondeo y el montaje
  operativo se verificaron con pruebas automatizadas.
- En Edge, con dos contextos de sesión independientes y el ASGI real
  en loopback, se verificaron la actualización sin recarga, el contador,
  la descarga externa, la vista TXT y el rechazo de descarga de Solo
  visualizar. Una respuesta HTTP retenida del chat anterior no
  sobrescribió el chat seleccionado después.
- Uvicorn mantuvo 13 sesiones ficticias por WS de loopback durante una
  ventana de 280 segundos, con una reconexión forzada. El cursor
  recuperó el mensaje enviado durante el corte. Se comprobó que las
  señales solo contenían tipo y cursor y que la revocación cerró el
  canal. Hubo 0 errores en 24 solicitudes muestreadas de confirmación,
  sincronización y Biblioteca.
- Para ocho envíos, la mediana de confirmación fue 2.14 s (máximo
  2.43 s). Desde la confirmación hasta señal y consulta HTTP, la mediana
  fue 1.54 s (máximo 2.07 s). La memoria residente de Uvicorn osciló
  entre 40.06 y 49.05 MiB y terminó en 40.06 MiB. La muestra cubre
  loopback y esa ventana de carga.

Pendientes de entorno real: Caddy activo, certificados y confianza
de los clientes, HTTPS/WSS autenticado, acceso desde otra PC y Android,
redirección si se configura, multipart y descargas por el proxy, y
recuperación ante cortes de red y reinicio del proxy. El laboratorio
invocó el `.bat` desde CMD y verificó automáticamente cuándo se llama
al navegador. El doble clic desde el Explorador y la apertura del
navegador predeterminado sobre la instancia habitual quedan pendientes
de comprobación manual.
