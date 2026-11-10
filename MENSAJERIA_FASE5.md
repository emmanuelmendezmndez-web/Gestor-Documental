# Referencias de Biblioteca en Mensajería

La Fase 5 es un servicio interno. La migración aditiva v5 solo afecta
al SQLite privado de Mensajería. Añade la modalidad por mensaje y
conserva las referencias anteriores sin asignarles permisos nuevos.
El mensaje guarda la referencia documental estable y el vencimiento.
El original, su nombre, formato, ubicación, área y metadatos oficiales
se siguen administrando en Biblioteca.

## Envío y acceso

El envío usa `motor.enviar` con un `Adjunto("documento", referencia,
modalidad=...)`. La modalidad es obligatoria y admite `visualizar` o
`visualizar_y_descargar`. Las dos cuentas deben estar activas y tener
`ver` para el documento bajo su rol y área actuales. Para elegir la
segunda modalidad ambas necesitan también `descargar`. Son las mismas
reglas de Biblioteca, incluidos los documentos compartidos sin área y
el alcance de administrador. La modalidad limita el canal y los permisos
independientes de Biblioteca siguen vigentes.

La confirmación valida la referencia estable y la correspondencia con
el nombre físico original registrado por SIGED. Abre el mismo archivo
regular en NTFS, sin seguir puntos de reanálisis ni aceptar enlaces
duros. La reserva SQLite de la base principal serializa esta comprobación
con cambios de permisos, edición, papelera, restauración de papelera y
purga. La reserva cubre el commit de mensaje, modalidad, comprobante,
cuota y evento en la base privada. La confirmación no lee los bytes del
documento ni crea copias físicas. El evento solo contiene los datos
mínimos del motor. La huella idempotente incluye la modalidad.

Los servicios de consulta aceptan referencias estables del actor, la
conversación y el mensaje. No aceptan una ruta o un ID de Biblioteca
como sustituto de la pertenencia a una conversación. Comprueban los
permisos de ambos participantes y la vigencia. La validación de formato
para tarjetas y visualización se hace fuera de la transacción, con el
archivo fijado por un identificador NTFS. Una segunda comprobación
detecta cambios de autorización, versión, referencia o identidad antes
de entregar el flujo o los metadatos. El bloqueo cooperativo compartido
evita que comience una restauración mientras el original está abierto.
Una lectura ya admitida puede concluir si la autorización cambia
después de ese punto. El cambio se aplica a las solicitudes siguientes.

La referencia vence a los siete días desde la confirmación UTC. Los
reintentos no renuevan ese plazo. Un nuevo envío requiere autorización
vigente y consume cuota. Papelera, purga y cambios de área invalidan el
acceso cuando corresponda. Restaurar desde papelera puede devolverlo
si es la misma referencia estable, sigue vigente y ambos tienen acceso.
El historial conserva el texto por 15 días. Al depurarlo desaparece la
modalidad con el mensaje y nunca se programa la eliminación del original.

Al sustituir la base documental, la generación debe volver a reconciliarse
explícitamente. El diagnóstico conserva el control de instalación,
identidades de usuario y referencias anteriores a v5. Las referencias
v5 se verifican individualmente en cada acceso, incluida su identidad
después de la reconciliación. Una referencia v5 ausente no convierte en
inaccesibles otros mensajes. Un registro anterior sin modalidad queda
en el historial y no habilita acceso al documento.

## Contrato para la tarjeta y el transporte posterior

`biblioteca.tarjeta(actor, conversacion, mensaje)` devuelve únicamente
`{"estado": "no_disponible"}` ante revocación, vencimiento, falta de
evidencia u otro rechazo. Una respuesta autorizada incluye `origen`,
`estado`, `nombre_original`, `formato`, `vence_utc` y `acciones`.
El formato se contrasta con el contenido mediante los validadores
existentes. Si no puede acreditarse, se devuelve nulo para usar un
icono genérico y se omite Visualizar. El cliente podrá asociar el formato
a su icono SVG local y debe mostrar el nombre como texto. Los metadatos
se consultan al servidor cuando se muestran, sin persistir ni cachear
la respuesta. El cuerpo del mensaje conserva únicamente el texto del
remitente.

`biblioteca.abrir_descarga` entrega internamente un flujo fijado y
cabeceras de descarga privada como adjunto. `biblioteca.abrir_visualizacion`
entrega el original únicamente a un futuro renderizador de confianza.
La vista existente de Biblioteca abre archivos por ruta y las conversiones
Office usan una caché. Ese flujo no se expone directamente desde Mensajería.
En la integración final habrá que renderizar en un contexto restringido,
revalidar después de cualquier conversión y entregar la vista sin publicar
el original o una URL permanente. Visualizar no garantiza que el
destinatario sea incapaz de copiar contenido que puede ver.

Antes de habilitar el módulo se deben implementar y probar los endpoints
autenticados, derivar el actor de la sesión vigente y aplicar CSRF a las
operaciones de escritura. En esa misma integración deben completarse
los plazos de recepción y las pruebas de multipart a través de Caddy
para archivos externos de Fase 4. También se debe verificar la revocación
entre solicitudes, las respuestas privadas y el aislamiento de las
previsualizaciones. La Fase 5 no registra rutas.
