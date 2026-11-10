# Mensajería: infraestructura de Fase 1

La infraestructura está deshabilitada: SIGED no inicializa esta base al
arrancar, no registra rutas ni inicia procesos de limpieza o WebSocket.
No habilitarla para usuarios antes de completar identidad y restauración.

## Ubicación privada

La configuración explícita `GESTOR_MENSAJERIA_DIR` debe ser una ruta absoluta
que termine en `.siged-mensajeria`, cuyo directorio padre ya exista en NTFS.
Por ejemplo, si la cuenta de servicio dispone de un directorio local apropiado:
`C:\RutaPrivada\SIGED\.siged-mensajeria`. No se crea ningún directorio por
defecto. La cuenta que inicializa debe ser la misma cuenta de servicio prevista;
una cuenta distinta podría no satisfacer las ACL y se rechazará la operación.
La ubicación debe quedar fuera del directorio del proyecto, de `storage`,
`respaldos` y `app/static`.
No se mueve el proyecto principal ni se supone que OneDrive esté activo.
El administrador debe proteger también el directorio padre frente a creación,
sustitución o cambio de nombre por otras cuentas. La comprobación actual verifica
las ACL del árbol de mensajería, no los permisos efectivos de todos sus
antecesores; esa comprobación del entorno debe completarse antes de habilitar
el módulo para datos sensibles. También debe comprobarse que la ruta sea un
volumen local: la validación actual no identifica todas las unidades de red
asignadas ni garantiza el comportamiento de SQLite sobre ellas.

La inicialización explícita crea la raíz con ACL protegida desde el inicio,
permitiendo la cuenta ejecutora, SYSTEM y Administradores, y verifica la
herencia antes y después de crear sus componentes. Exige NTFS con ACL
persistentes; si no puede verificar las ACL, falla sin aceptar contenido. Las
carpetas `temporales` y `confirmados` quedan vacías: no hay cargas, descargas
ni eliminación automática. En el futuro los nombres físicos deberán ser
aleatorios, nunca el nombre original del usuario.

La base es `mensajeria.sqlite3` en esa raíz; los archivos auxiliares SQLite
`-journal`, `-wal` o `-shm`, si aparecen, permanecen en la misma raíz y
deben recibir las mismas ACL. No se activa ni modifica el modo WAL. El respaldo
ordinario actual copia la base documental y recorre `storage`, de modo que
esta raíz queda fuera de ese ZIP. Esto no garantiza exclusión de copias de
Windows, sincronizadores, antivirus u otros programas externos.

## Identidad y restauración: dependencia de Fase 2

Las referencias se reservan para identificadores estables de usuarios y
documentos, no para IDs numéricos históricos. No hay claves foráneas entre las
bases. La tabla `contexto` conserva instalación y generación sin asignar y
estado `no_verificada`; su esquema de Fase 1 no permite marcarla verificada.
`exigir_identidad_verificada()` rechaza siempre. No se crean identificadores en
la base documental ni se afirma que existan.

Antes de habilitar cualquier ruta, la Fase 2 debe introducir y verificar
identidades estables, vincular la generación de la base documental y detectar
restore ordinario y recuperación administrativa bajo el bloqueo cooperativo.
Ante referencias ausentes, discrepantes, una generación no acreditada o un
rollback, deberá denegar acceso y exigir reconciliación. No se deben usar las
tablas ni la función de conexión de esta fase como autorización para enviar o
leer mensajes.

## Migraciones

La creación de tablas, índices, disparadores, `application_id` y
`user_version` se realiza mediante `BEGIN IMMEDIATE` en una sola
transacción. Una interrupción revierte el esquema; repetir la inicialización
verifica versión, definición, integridad y claves foráneas. Una base ajena,
incompleta, alterada o de versión desconocida se rechaza. La inicialización
solo se invoca expresamente desde código administrativo o pruebas; no se
añadió una ruta HTTP ni se ejecutó sobre datos operativos.

El esquema reserva estructuras y límites, pero no implementa envío, cuota,
retención, limpieza o notificaciones. Las reglas efectivas, zona horaria,
idempotencia, transacción entre archivos y base, y política de auditoría y
recuperación deben completarse y probarse en fases posteriores.
El marcador de lectura por conversación es preliminar: antes de implementarlo
se requiere un criterio inequívoco para mensajes con la misma marca de tiempo.
