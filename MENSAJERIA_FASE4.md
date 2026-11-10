# Archivos externos temporales de Mensajería

La Fase 4 incorpora servicios internos. El servidor sigue sin rutas
de Mensajería. La configuración privada y la reconciliación administrativa
se realizan como en las fases anteriores. La inicialización administrativa
actualiza SQLite de Mensajería de v3 a v4 en una transacción. El servidor
no crea el almacén ni lo migra al arrancar.

## Preparación y confirmación

`app.mensajeria.adjuntos.preparar` recibe dos referencias estables de
usuario, la clave de operación, el nombre y un lector binario con
`read(n)`. El módulo reserva espacio para el máximo por archivo antes
de aceptar bloques. La intención `recibiendo` vincula remitente,
destinatario, clave, generación y token físico. El archivo se crea con
exclusión en `GESTOR_MENSAJERIA_DIR/temporales` y registra su identidad
NTFS antes de recibir el primer bloque.

El objeto permanece en la misma ubicación privada. La publicación
consiste en confirmar el estado `preparado` después de verificar
los bytes y vaciarlos a disco. Se verifica una segunda vez el contenido
físico antes de confirmar. Durante esta última comprobación y el
commit se mantiene abierto el mismo identificador, sin compartir
escritura ni borrado. Se revalidan participantes, generación,
preparación e idempotencia bajo las reservas SQLite existentes.

`app.mensajeria.motor.enviar` exige ese protocolo para archivos externos.
Confirma conjuntamente el mensaje, archivo, cuota, comprobante y evento
mínimo. La transacción privada protege esas escrituras. La comprobación
de la identidad principal y el almacenamiento NTFS tienen mecanismos
propios. Un corte antes del commit puede dejar una preparación reutilizable
hasta su plazo. Si se perdió la respuesta después del commit, la misma
operación devuelve el mismo ID y el mismo vencimiento. Una huella liga
nombre, tamaño y SHA-256 del contenido al token. Repetir la preparación
compara el flujo sin guardar otra copia. SHA-256 sirve para detectar
contenido distinto o alterado y no acredita el origen del archivo.

## Tamaño, formatos y presupuesto

El servicio acepta de 1 a 20,971,520 bytes reales en bloques de 128 KiB.
El límite HTTP existente de 22,020,096 bytes deja 1 MiB para límites,
encabezados y campos del multipart de un archivo de 20 MiB. La fase que
publique la ruta deberá acotar los campos y comprobar el flujo con
FastAPI, Starlette y Caddy. Los límites y rutas vigentes de Biblioteca
continúan iguales.

Se comprueban PDF, Office Open XML sin macros admitidas, TXT UTF-8,
PNG y JPEG. Se rechazan nombres Windows reservados, caracteres de control,
rutas, nombres de más de 200 caracteres y nombres con más de un punto.
El MIME del cliente queda fuera de la decisión. Office se verifica sin
extracción, con un máximo de 2,048 entradas, una lectura individual de
1 MiB de metadatos, 32 MiB de lectura acumulada y 64 MiB de salida
descomprimida, hasta 24 MiB por miembro. Se verifican los conteos ZIP,
CRC, rutas, la relación principal y los tipos de contenido esperados.
PDF y las imágenes reciben comprobaciones estructurales acotadas,
sin renderizar ni decodificar completamente el contenido. Algunos
archivos válidos que queden fuera de esos presupuestos se rechazan.
Estas comprobaciones no sustituyen un antivirus.

| Variable con prefijo `GESTOR_MENSAJERIA_` | Valor inicial | Propósito |
| --- | ---: | --- |
| `CARGAS_SIMULTANEAS` | 4 | Intenciones que aún reciben datos |
| `CARGAS_SIN_CONFIRMAR` | 20 | Recepciones y preparaciones acumuladas |
| `ARCHIVOS_MAX_CANTIDAD` | 4,096 | Reservas y archivos físicos gestionados |
| `ARCHIVOS_MAX_BYTES` | 2 GiB | Archivos retenidos más reservas máximas |
| `ESPACIO_LIBRE_BYTES` | 512 MiB | Margen inicial y comprobación durante la escritura |
| `PREPARACION_SEGUNDOS` | 600 s | Límite total hasta confirmar |
| `CARGA_INACTIVA_SEGUNDOS` | 60 s | Límite de espera entre avances |

Los presupuestos son por almacén. Para proteger el volumen se comprueba
espacio real antes de reservar y de escribir. Escrituras de otros
servicios en el mismo volumen pueden consumir ese margen y causar un
rechazo posterior. Entre lecturas de la fuente no se conserva el
identificador de escritura. La limpieza puede liberar una intención
inactiva aunque la fuente siga bloqueada y esa fuente no puede recrear
el archivo. El futuro transporte debe cancelar sus propias lecturas
bloqueadas para liberar también la solicitud.

## Descarga, retención y limpieza

`abrir_descarga` es un gestor de contexto para remitente y destinatario
activos. Verifica el vínculo con el mensaje, la generación reconciliada,
la identidad física, el contenido y el vencimiento. Entrega un flujo y
cabeceras para una futura descarga como adjunto con
`application/octet-stream`, `nosniff` y `private, no-store`. Una
descarga admitida puede terminar una vez vencida porque el identificador
abierto impide su borrado. Abrir o repetir una descarga no renueva las
tres horas, que se calculan a partir del instante UTC de confirmación.
El mensaje y sus metadatos siguen la retención de 15 días. Se conserva
el comprobante mínimo después de depurar para impedir duplicados.

El servidor con almacén configurado programa una revisión al inicio y
cada minuto. El bloqueo NTFS del trabajador excluye otros trabajadores
del mismo almacén. Los lotes de 16 procesan cargas interrumpidas o sin
confirmar y confirmaciones vencidas. Cada eliminación vuelve a comprobar
las referencias y utiliza el identificador exacto del archivo. Windows
puede rechazar el borrado por uso o permisos. La tarea persiste y
reintenta después de un minuto. Una interrupción después del borrado
se resuelve al comprobar que el mismo objeto ya no está.

El hueco entre crear un archivo y registrar su identidad solo puede
dejar un objeto vacío bajo un token ya reservado. La limpieza lo
acepta bajo esa intención únicamente en el almacén privado y como
archivo regular de un solo enlace. Una colisión detectada o un objeto
sin evidencia de procedencia se conserva para revisión administrativa.
El proceso no sigue puntos de reanálisis ni borra por nombre original.
Se usan los mismos controles de rutas y ACL NTFS de Fase 1. La cuenta
de servicio, SYSTEM y Administradores son identidades de confianza
en ese modelo. La política de respaldo ordinario sigue excluyendo el
almacén.

Los archivos se sincronizan antes de publicar la preparación. NTFS
y SQLite pueden persistir en instantes diferentes ante un apagón.
Las comprobaciones de identidad y huella rechazan un objeto ausente,
reemplazado o alterado. La tarea física se puede reintentar, pero no
se reconstruyen bytes perdidos. Quedan pendientes la publicación
HTTP/HTTPS, la política definitiva de comprobantes antiguos y cualquier
integración de Biblioteca o WebSockets.
