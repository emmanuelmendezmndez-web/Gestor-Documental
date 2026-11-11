# Visualización y descarga desde las tarjetas

El arranque experimental sigue usando el procedimiento de Fase 7B con
`--habilitar --http-api --interfaz`. Los cambios de Fase 7C.1 permanecen
en el árbol de trabajo. El canal WebSocket conserva su implementación.

## Servicios reutilizados

Biblioteca usa `GET /documentos/{id}/vista`, exige permiso `ver`,
filtra el área y excluye papelera. Entrega PDF, PNG y JPEG al navegador.
Para TXT usa `previsualizacion.html` con escape Jinja y CSP restrictiva.
Para DOCX, XLSX y PPTX usa LibreOffice y una caché de PDF.

`app/vista_documental.py` reúne la plantilla, los tipos MIME y las
cabeceras privadas que ya usaba Biblioteca. Su ruta mantiene el mismo
comportamiento. Mensajería reutiliza estos componentes detrás de sus
propias rutas autorizadas, con el original abierto mediante su descriptor
NTFS verificado. Se conservan las referencias estables de Fase 5.

## Compatibilidad

| Formato | Biblioteca en Mensajería | Externo |
| --- | --- | --- |
| TXT hasta 1 MiB | Solo visualizar o visualizar y descargar | Vista y descarga |
| PNG, JPG, JPEG | Vista cuando la descarga también está autorizada | Vista y descarga |
| PDF, DOCX, XLSX, PPTX | Descarga autorizada | Descarga |
| TXT mayor de 1 MiB | Descarga autorizada | Descarga |

TXT se transforma mediante la plantilla escapada existente. El límite
de vista de 1 MiB acota la memoria de lectura y renderizado. La cuota y
el límite de subida de 20 MiB se conservan.

El visor nativo de imágenes recibe los bytes originales. Por ello solo
se habilita cuando existe autorización de descarga. Las referencias
anteriores con modalidad Solo visualizar a una imagen siguen protegidas
y muestran un estado de vista no compatible.

El visor nativo PDF de Biblioteca entrega el original y depende de
funciones del navegador cuyo aislamiento no está acreditado por esta
integración. La conversión Office usa una caché con vida independiente
del adjunto y un proceso de LibreOffice que no tiene el aislamiento
requerido para contenido privado no confiable de Mensajería.
Estos formatos conservan la descarga autorizada y su estado de vista
no compatible. La integración utiliza la plantilla y las capacidades
nativas existentes.

## Acceso e interfaz

`GET /mensajeria/api/v1/conversaciones/{chat}/mensajes/{mensaje}/adjunto/vista`
comprueba sesión revocable, identidad, generación reconciliada,
pertenencia, vigencia, modalidad y disponibilidad. Biblioteca aplica
los permisos de ambos participantes, su área, papelera y la identidad
del original. Los externos reutilizan su comprobación de integridad
criptográfica y ubicación privada.

La ruta de descarga existente conserva su autorización y sus cabeceras
de adjunto. Cada acceso vuelve a comprobar el estado. Las respuestas
de vista son privadas, sin caché, con `nosniff`, CSP con `sandbox`,
restricción de ancestros y de referente. No se redirige a la ruta de
Biblioteca ni se publica una ruta física o un recurso estático.

Visualizar abre una pestaña independiente con `noopener noreferrer`.
La conversación conserva su borrador y su estado. La tarjeta ofrece
las acciones que devuelve HTTP y explica la falta de vista compatible.
El selector del adjunto TXT permite elegir Solo visualizar. Las
modalidades anteriores de la API y los mensajes existentes se conservan.
La compatibilidad se vuelve a comprobar en el servidor al abrir la vista.

Las lecturas admitidas mantienen los descriptores y bloqueos durante la
respuesta, con los cupos y plazos de transporte existentes. Los accesos
siguientes aplican cambios de sesión, permisos, vigencia y restauración.

## Validación y alcance posterior

Los casos HTTP cubren modalidades, separación de conversaciones,
vencimiento, papelera, cambio de área, eliminación, restauración,
revocación, TXT escapado, imágenes verificadas y formatos incompatibles.
Las pruebas de política cubren el límite de texto y la restricción
de originales de imagen en Solo visualizar.

La validación con Caddy, HTTPS/WSS y dispositivos remotos corresponde
a Fase 7C.3. La Mensajería continúa requiriendo habilitación experimental.
