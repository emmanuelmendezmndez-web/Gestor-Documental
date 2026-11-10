# Señales WebSocket experimentales de Mensajería

El arranque normal de SIGED no monta este canal. El arranque experimental
requiere habilitación explícita y escucha en loopback. Solo transporta
señales. Los mensajes y adjuntos se siguen consultando mediante servicios
autorizados y no se publican endpoints HTTP nuevos en esta fase.

## Sesiones y revocación

El navegador usa la cookie firmada `gestor_sesion` de Starlette. El
handshake exige un único `Origin` exacto de la lista configurada y la
coincidencia con el esquema y Host que recibe la aplicación. Rechaza
orígenes ausentes, ambiguos y parámetros de URL. Detrás de Caddy se usa
el esquema reenviado únicamente desde el proxy confiable en loopback.
Los formularios HTTP siguen sujetos a su validación CSRF.

Un login correcto en la aplicación experimental añade un identificador
aleatorio a la cookie y registra la sesión en el SQLite privado de
Mensajería. La sesión experimental vence como máximo a las diez horas
del login. La cookie por sí sola no basta para recuperar una sesión
experimental. Cada lote revalida el registro, el usuario activo, su
identidad estable, la versión de sesión y la generación reconciliada.
Las cookies anteriores a la habilitación requieren iniciar sesión de
nuevo.

`POST /salir` revoca el identificador de esa sesión antes de borrar
la cookie. Las pestañas que comparten la sesión quedan revocadas.
Otro login de la misma cuenta conserva su sesión. Si no es posible
confirmar la revocación en el almacén privado, se incrementa la versión
de sesión vigente de la cuenta como medida de cierre seguro. Ese caso
puede cerrar también sus otras sesiones. Si falla ese respaldo, la
petición devuelve un error y no declara cerrado el login.

El cambio de contraseña y la revocación administrativa conservan el
mecanismo existente de versión de sesión. Una desactivación, un cambio
de identidad o una restauración invalidan la conexión en su siguiente
comprobación. Tras una restauración se necesita reconciliar la nueva
generación y volver a autenticarse para abrir otro WebSocket. El
servidor normal mantiene su bloqueo cooperativo de arranque. La prueba
de restauración con una conexión viva usa una aplicación aislada sin
ese bloqueo de vida del servidor.

## Contrato para la Fase 7

1. Abrir `/mensajeria/ws` del mismo origen con la cookie de sesión,
   usando WSS si la página está en HTTPS. Al recibir
   `{"tipo":"conexion_lista"}`, enviar una sola trama de texto JSON
   `{"tipo":"sincronizar","cursor":null}` o incluir el último cursor
   aplicado de esa cuenta y origen.
2. El servidor envía `mensaje_nuevo`, `lectura_actualizada`,
   `bandeja_actualizada` o `resincronizar`, cada uno con un
   `cursor` opaco que puede ser nulo al reconstruir una bandeja vacía.
   Los eventos se leen del SQLite privado después de su commit. Nunca
   incluyen identificadores de mensajes, texto, archivos ni rutas.
   Las lecturas y el archivado producen señales solo para quien cambió
   su estado.
3. Tras cada conexión, obtener una instantánea autorizada por HTTP
   antes de marcar la bandeja como actualizada. Refrescarla también
   ante una señal. Si llegan señales mientras se consulta, marcarla
   pendiente y volver a consultar tras la respuesta. Guardar el cursor
   solo después de aplicar la consulta correctamente. Tratar una señal
   repetida como invalidación idempotente, incluso entre pestañas.
   Calcular el contador de no leídos desde la respuesta HTTP. La
   interfaz podrá mostrar «Nuevo mensaje recibido» para
   `mensaje_nuevo`, según el estado de la bandeja consultada.
4. Si el cursor venció, se depuró, pertenece a otro actor o corresponde
   a otra generación, el servidor emite `resincronizar`. La interfaz
   debe reconstruir su estado autorizado y guardar el nuevo punto de
   sincronización. Las páginas de recuperación contienen hasta 32
   señales. El vencimiento lógico de eventos es de 15 días. La
   depuración física se hace por lotes al registrar eventos o depurar
   el historial.
5. Si se interrumpe la conexión, reconectar con espera exponencial
   desde un segundo hasta un máximo de 30 segundos, variación
   aleatoria y reinicio de la espera tras sincronizar correctamente.
   La misma estrategia cubre Wi-Fi, suspensión móvil, reinicio de
   Uvicorn y corte del proxy. Si cambia la dirección, se debe abrir
   el nuevo origen permitido y autenticar allí. Un cierre 1008 pide
   comprobar la sesión y la habilitación antes de intentar de nuevo.
   Un 1013 admite reintento con espera. Un 1009 indica un cliente fuera
   de contrato. El navegador no necesita enviar pings de aplicación.

## Límites y extensión

El administrador genérico limita a cuatro conexiones por identidad y
32 conexiones o handshakes activos por proceso. Agrupa las consultas
en un hilo fuera del event loop, con un ciclo inicial de dos segundos,
esperas SQLite acotadas y presupuesto de lectura. Hay una solicitud
pendiente por conexión y un lote en ejecución. El servicio limita el
plazo de una consulta a 12 segundos y el envío de un lote a dos. Una
conexión que no completa el inicio en cinco segundos, envía más de
una trama de aplicación o deja de consumir datos se cierra. Uvicorn
limita la trama a 1 KiB y su cola de recepción a dos mensajes, sin
compresión. Los límites se aplican en el arranque experimental y son
por proceso. El despliegue previsto usa un trabajador.

En cada lectura se comprueban identidad y descriptor NTFS de la raíz
privada y de su SQLite. La validación completa de sus reglas se reutiliza
solo mientras ambas evidencias coincidan dentro del mismo proceso. Esto
evita iniciar PowerShell en cada ciclo y deja intactas las verificaciones
completas de las operaciones de escritura y de adjuntos.

Un módulo futuro puede proporcionar su propia fuente de señales al
administrador genérico. Debe aportar su autorización, proyección de
campos, persistencia, cursor y retención. En Mensajería esas funciones
están en `sesiones_ws.py` y `eventos.py`. Las futuras notificaciones
de subidas, disco, administración o respaldos tendrán su propio
servicio y no usarán el SQLite de Mensajería como almacén.

## Prueba reproducible de WSS

El backend opcional `websockets` proporciona a Uvicorn el límite de
tamaño y la cola de recepción. Para preparar un entorno de prueba con
las dependencias declaradas, usar `uv sync --locked --group pruebas
--group mensajeria-ws`. En PowerShell separado, establecer
`GESTOR_DATA_DIR` en una carpeta de laboratorio y
`GESTOR_MENSAJERIA_DIR` en su almacén privado
`.siged-mensajeria`. Crear únicamente usuarios ficticios, inicializar
el SQLite privado con `python -m app.mensajeria.reconciliacion
inicializar`, preparar las identidades y reconciliarlas mediante el
procedimiento administrativo existente.

Para el proxy de laboratorio, configurar el nombre o IP, certificado y
clave en una copia de `Caddyfile.ejemplo`, con upstream
`127.0.0.1:8000`. Usar un certificado confiable por los clientes y
poner `GESTOR_HTTPS_ONLY=1` antes de arrancar:

```powershell
.\.venv\Scripts\python.exe -m app.mensajeria.servidor_ws --habilitar --proxy-loopback --origen https://siged-prueba.test
```

Iniciar sesión en el host de laboratorio y abrir DevTools en esa
página. Esta comprobación manual no constituye la interfaz:

```javascript
const s = new WebSocket("wss://" + location.host + "/mensajeria/ws");
s.onmessage = ({ data }) => {
  const señal = JSON.parse(data);
  if (señal.tipo === "conexion_lista") {
    s.send(JSON.stringify({ tipo: "sincronizar", cursor: null }));
  }
  console.log(señal.tipo);
};
```

Comprobar un Upgrade válido con la cookie Secure, repetir sin login
y desde un origen distinto para confirmar el rechazo, cerrar sesión
con una pestaña conectada y repetir tras reiniciar el proxy. Probar
desde otro dispositivo de la LAN con ese mismo nombre y certificado.
La [documentación de Caddy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy)
describe el Upgrade automático y el cierre de túneles durante recargas.
No se requiere cambiar el Caddyfile operativo para esta fase.

Antes de habilitar Mensajería para usuarios finales quedan el transporte
HTTP autenticado, CSRF para escrituras, límites y plazos multipart a
través de Caddy, renderizado documental restringido y conexión de la
interfaz con las consultas autorizadas.
