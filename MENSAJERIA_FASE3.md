# Motor interno de Mensajería

El módulo `app.mensajeria.motor` ofrece operaciones internas para
recuperar o crear una conversación, enviar, consultar historial, marcar
lectura, archivar y consultar la cuota. El servidor no registra rutas para
este módulo. El llamante interno debe entregar la referencia estable de
un actor autenticado. El motor revalida la identidad, la generación
reconciliada, la participación y el estado activo.

## Confirmación

Cada par de usuarios distintos tiene una conversación única e independiente
del orden. El texto debe tener entre 1 y 300 puntos de código Unicode y
contener al menos un carácter no blanco. Se conserva el texto exacto.
La futura interfaz puede contar con `Array.from(texto).length` y debe
rechazar también NUL y secuencias Unicode no válidas.

El motor recibe un único descriptor `Adjunto`. Para un envío nuevo exige
un verificador interno que acredite tipo, existencia, vigencia, propiedad
y disponibilidad para los participantes y la generación solicitada. El
verificador se ejecuta fuera de SQLite. El contrato exige que el recurso
verificado conserve su identidad y disponibilidad hasta el commit. Las
pruebas suministran su propio adaptador ficticio. La Fase 4 deberá aportar
un verificador de producción y un protocolo de reserva para adjuntos
externos. La comprobación documental actual solo revalida identidad y
existencia dentro del motor. El permiso de acceso documental deberá
comprobarse mediante el adaptador correspondiente antes de usar ese tipo.

El envío confirmado, el consumo de cuota, el comprobante de operación y el
evento pendiente comparten una transacción privada. Una interrupción
previa al commit revierte el conjunto. La comprobación de generación se
repite después del verificador, por lo que una restauración intermedia
invalida esa verificación. Los eventos guardan únicamente ID de mensaje,
destinatario, clase, instante y estado.

## Cuota e idempotencia

Cada confirmación consume una unidad del remitente, hasta 50 por fecha
institucional. `GESTOR_MENSAJERIA_ZONA_HORARIA` acepta una zona IANA
disponible localmente, `UTC` (valor inicial) o un desfase fijo como
`-06:00`. El desfase fijo funciona sin datos de zonas instalados en
Windows y no aplica horario estacional. La primera operación fija la
configuración para esa base. Una configuración diferente se rechaza.
Los instantes se guardan en segundos UTC y un reloj que retroceda respecto
del último instante confirmado por el motor se rechaza. Un salto hacia
adelante se interpreta como tiempo transcurrido y puede vencer historial.

La clave idempotente tiene 32 dígitos hexadecimales en minúsculas. El
remitente y la clave identifican la operación. Una huella del destinatario,
texto y descriptor detecta usos conflictivos. Una repetición devuelve el
mismo ID aun cuando el historial haya vencido. Las operaciones anteriores
sin huella conservan su registro, pero no se reconocen como repeticiones
verificadas.

## Lectura, archivo y retención

El motor publica únicamente mensajes confirmados. La preparación y los
fallos de envío no dejan un mensaje visible ni consumen cuota. La lectura
se registra únicamente cuando el destinatario la confirma explícitamente
para ese mensaje. El archivado cambia solo la lista del participante que
lo aplica. El historial vence a los 15 días de la confirmación. La consulta
lo oculta a partir del vencimiento y la depuración por lotes retira el
mensaje, su lectura y su evento. Conserva cuotas y comprobantes
idempotentes. Los tokens de adjuntos externos se registran como tareas
suspendidas para impedir su reutilización y permitir tratamiento posterior
sin tocar archivos.

La migración v3 actualiza la tabla de operaciones dentro de una transacción
y conserva sus filas. Añade marcas de lectura por mensaje y una referencia
persistente del reloj. La política de retención de cuotas y comprobantes
queda pendiente, así como la entrega de notificaciones. El bloqueo
conservador de Fase 2 se mantiene para todo el vínculo ante referencias
incompatibles, incluida la depuración hasta que puedan reconciliarse.
