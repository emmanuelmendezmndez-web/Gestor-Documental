# Preparación de restauraciones

Con SIGED detenido, `python -m app.preparacion_persistente` inspecciona bajo bloqueo exclusivo la preparación de la restauración pendiente. La creación se invoca mediante `python -m app.preparacion_persistente preparar`, que conserva el conjunto y publica la constancia solamente tras verificarlo. Ambas operaciones mantienen `listo_recuperacion: false`: no autorizan arranque ni restauración.

La preparación se conserva en `.siged-preparacion-operacion-XXXXXXXX` dentro de `GESTOR_DATA_DIR`, con ACL restringida y un nombre exclusivo por operación. Incluye la primera copia de SQLite, la copia transformada, los componentes documentales, la clave local cuando corresponda, un manifiesto de componentes y la constancia independiente. Una preparación existente no se sobrescribe. Los intentos incompletos se conservan para revisión administrativa; no se eliminan automáticamente.

La inspección vuelve a consultar el registro y el inventario v2 bajo el mismo bloqueo, comprueba las ACL, las identidades y huellas de los componentes, sus presencias y ausencias, SQLite y la cola. Rechaza componentes adicionales o discrepantes. Las referencias documentales se comprueban durante la creación y se vinculan por las huellas al conjunto inspeccionado. Un resultado íntegro no acredita autenticidad criptográfica ni permite recuperar datos.

La publicación sincroniza los archivos y utiliza un enlace sin reemplazo en NTFS. No se garantiza la durabilidad de los enlaces de directorio ante un apagón: después de reiniciar debe ejecutarse de nuevo la inspección completa. Una constancia ausente, ilegible o contradictoria no habilita ninguna operación. La creación conserva intentos incompletos incluso si una operación falla.

## Clave histórica

Si el registro identifica una clave local, se compara con el inventario sin atribuir autenticidad a su hash. Si identifica `GESTOR_SECRET_KEY`, su valor actual no prueba cuál se usaba anteriormente. Una persona administradora debe localizar evidencia independiente y confiable en el sistema institucional de custodia de secretos, verificar la identidad y el periodo de vigencia mediante el procedimiento institucional y mantener el valor fuera de diagnósticos, registros y comandos visibles. Si no existe tal evidencia, la clave permanece no acreditada. No se genera ni sustituye automáticamente ninguna clave; incluso con evidencia, esta etapa no autoriza una recuperación.

