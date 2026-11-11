# Mensajería en tiempo real experimental

Usa el arranque de laboratorio de [Fase 7B](MENSAJERIA_FASE7B.md) con
`--habilitar --http-api --interfaz` y datos ficticios reconciliados. La
interfaz recibe la ruta del canal únicamente cuando está montado. Abre
una conexión por página en el mismo esquema y host de SIGED (`ws` para
HTTP, `wss` para HTTPS). El arranque sigue usando loopback y un trabajador.

## Señales y recuperación

La cookie de SIGED autentica el Upgrade. Se conservan las comprobaciones
de Host, Origin, sesión, usuario activo y generación de
[Fase 6](MENSAJERIA_FASE6.md). Tras `conexion_lista`, el cliente envía
una sola solicitud `sincronizar` con el último cursor aplicado en
memoria, o `null` si la pestaña empieza de cero.

Cada conexión solicita una instantánea HTTP. Las señales se agrupan y
solo invalidan el estado. Las que llegan durante una consulta provocan
otra consulta. El cursor avanza tras aplicar la bandeja y el historial
activo. Si se pierde la conexión, el servidor vuelve a validar ese
cursor. `resincronizar` solicita reconstruir el estado autorizado si
el ancla dejó de ser válida. La paginación del historial enlaza las
páginas nuevas con los mensajes ya visibles. Se preservan las filas por
identificador, el borrador y el transporte de un archivo en curso.

El cliente reintenta con espera exponencial y variación aleatoria, con
un máximo de 30 segundos entre intentos programados. Una respuesta
definitiva de sesión o generación detiene el canal y retira los datos
visibles de Mensajería. Cuando el navegador oculta la página para
guardarla o abandonarla, se cierra el canal. Al restaurarla, HTTP
vuelve a comprobar el estado. Cada pestaña mantiene su propio cursor
en memoria y consulta la misma fuente autorizada.

## Avisos

`GET /mensajeria/api/v1/sincronizacion?avisos=true` añade hasta 25
avisos agrupados, uno por conversación con mensajes recibidos sin leer,
incluidas las archivadas. Cada grupo representa su mensaje pendiente
más reciente. La campana cuenta los grupos mostrados y el lateral cuenta
todos los mensajes sin leer. El panel usa el nombre del perfil activo
cuando está disponible. Un aviso nuevo puede anunciarse en la región
accesible de estado. La lectura sigue requiriendo la acción explícita
del usuario y su confirmación HTTP.

La vista previa documental aislada pertenece a 7C.2. La validación del
proxy Caddy, HTTPS/WSS y dispositivos remotos pertenece a 7C.3.
