# Identidad y restauración de Mensajería

Las dos bases siguen separadas. La fase añade una migración aditiva a
`mensajeria.sqlite3` y una preparación explícita de identidades en la base
documental. La preparación asigna referencias aleatorias de 128 bits a las
filas existentes y una identidad de instalación. Las inserciones posteriores
reciben referencias nuevas y las existentes no se pueden reasignar. Un
documento conserva además el nombre físico asociado a su identidad.

La ubicación sigue siendo la de la Fase 1. Solo el SQLite documental y el
árbol documental se incluyen en el respaldo ordinario, junto con las demás
entradas ya previstas por el formato. La base privada, sus archivos auxiliares
SQLite y sus carpetas de archivos quedan fuera del ZIP. Los identificadores
estables de usuarios y documentos sí viajan con la base documental. Copias
externas al sistema de respaldos de SIGED tienen su propia política.

## Procedimiento administrativo

Con una ubicación privada NTFS ya elegida y configurada mediante
`GESTOR_MENSAJERIA_DIR`, los comandos disponibles son:

```powershell
.\.venv\Scripts\python.exe -m app.mensajeria.reconciliacion inicializar
.\.venv\Scripts\python.exe -m app.mensajeria.reconciliacion preparar
.\.venv\Scripts\python.exe -m app.mensajeria.reconciliacion diagnosticar
.\.venv\Scripts\python.exe -m app.mensajeria.reconciliacion reconciliar --confirmar TOKEN_DEL_DIAGNOSTICO
```

`inicializar` prepara la base privada. `preparar` modifica explícitamente el
esquema documental de forma aditiva, por lo que debe programarse como tarea
administrativa. Solo provisiona una base sin identidad cuando Mensajería
todavía no tiene vínculo ni referencias que necesiten acreditación.
`diagnosticar` devuelve un estado, recuentos de incidencias si los hay y
un token solo cuando hay evidencia suficiente para confirmar el vínculo.
El token corresponde a esa instalación y generación. No autoriza usuarios.

`reconciliar` vuelve a verificar toda la evidencia y escribe únicamente el
vínculo privado. Repetirlo en la misma generación conserva el resultado.
Un corte previo al commit deja el vínculo anterior; un corte posterior deja
el vínculo nuevo. No se exige que dos commits en bases distintas ocurran
juntos. Un vínculo válido tampoco habilita las rutas ni el uso funcional.

## Restauraciones y concurrencia

La generación deriva de las evidencias verificadas de restauración y de la
identidad del archivo SQLite documental en el volumen local. No usa fechas
de modificación. Se recalcula bajo el bloqueo cooperativo compartido.
Las restauraciones y recuperaciones adquieren el bloqueo exclusivo vigente.
Mientras exista una recuperación incompleta, se respeta el bloqueo del
sistema. El respaldo ordinario puede coexistir con un diagnóstico y puede
esperar brevemente por la reserva de escritura de SQLite. La preparación
de copia para recuperación acepta únicamente las definiciones exactas de los
disparadores de identidad, que pertenecen a usuarios y documentos.

Una copia antigua sin instalación acreditada, otra instalación, referencias
ausentes, usuarios inactivos, archivos no disponibles o identidades
contradictorias impiden reconciliar. No se asignan coincidencias por ID
numérico, nombre visible ni cuenta de inicio de sesión. Ante cualquier
incidencia se conserva la base privada íntegra y el diagnóstico devuelve
solo categorías y recuentos, sin contenido ni datos identificativos.

La verificación del archivo documental comprueba nombre registrado, tipo y
tamaño. Los respaldos y recuperaciones oficiales mantienen sus verificaciones
de contenido. Una sustitución manual que sobrescriba bytes con el mismo
tamaño y conserve la identidad del archivo fuera del protocolo de SIGED no
se acredita con estos controles. Tampoco se puede reconocer con certeza una
copia manual de SQLite que sobrescriba el mismo archivo y conserve todas las
referencias y evidencias observadas. La Fase 3 deberá integrar la identidad con
las comprobaciones de permisos en cada operación y definir la verificación
de contenido que requieran los adjuntos documentales. Para uso operativo,
siguen pendientes la elección del volumen local y la revisión de permisos
de sus directorios antecesores.
