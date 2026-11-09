# Recuperación administrativa con arranque bloqueado

Detenga todos los procesos de SIGED. Identifique el registro v2 pendiente mediante el diagnóstico existente y conserve todos los respaldos y evidencias. Las operaciones usan el bloqueo exclusivo y requieren que los dos identificadores coincidan:

```powershell
.\.venv\Scripts\python.exe -m app.recuperacion_administrativa comprobar --operacion operacion-XXXXXXXX --confirmar-operacion operacion-XXXXXXXX
.\.venv\Scripts\python.exe -m app.recuperacion_administrativa aplicar --operacion operacion-XXXXXXXX --confirmar-operacion operacion-XXXXXXXX
.\.venv\Scripts\python.exe -m app.recuperacion_administrativa finalizar --operacion operacion-XXXXXXXX --confirmar-operacion operacion-XXXXXXXX
```

Sustituya ambos identificadores por el mismo valor real. `comprobar` solo inspecciona y no autoriza operaciones. `aplicar` crea copias adicionales verificadas, conserva originales y cualquier estado activo distinto, y después instala SQLite, storage y clave local. La misma orden `aplicar` reanuda una interrupción; no elimina las copias preparadas ni los componentes conservados. Una respuesta bloqueada exige conservar la evidencia y revisar el estado; no existe una opción de fuerza.

Los archivos `instalacion.json`, `intencion-...` y `confirmacion-...` están vinculados a la operación y al inventario v2. La reanudación compara el estado físico con las huellas y las identidades registradas. El registro se vacía y publica sin sobrescribir, pero Windows no garantiza aquí la durabilidad del enlace de directorio ante una pérdida súbita de energía. Si faltan evidencias o son contradictorias, se detiene. Los hashes no acreditan autenticidad criptográfica.

Las claves históricas de entorno no acreditadas y una configuración actual incompatible se rechazan. No se generan claves ni se modifica la variable de entorno. La copia SQLite instalada conserva suspendidas las tareas antiguas de eliminación. Los originales desplazados conservan sus ACL. Las copias de instalación heredan la ACL del directorio protegido y no reciben automáticamente la ACL anterior de las rutas activas; la compatibilidad con la cuenta de servicio definitiva debe comprobarse antes de habilitar SIGED.

El resultado `instalación verificada; arranque bloqueado` no autoriza iniciar SIGED: el registro permanece pendiente. La acción `finalizar` vuelve a verificar el conjunto instalado, publica evidencia independiente y finaliza el registro bajo bloqueo exclusivo. Ante éxito informa `restauración finalizada`; una repetición informa `restauración ya finalizada`. Si detecta errores informa `bloqueada` y conserva los archivos. No elimine automáticamente originales, estados activos desplazados, etapas incompletas ni respaldos.

El arranque comprueba la evidencia histórica del cierre sin exigir que la base ni los documentos activos conserven sus huellas después del uso normal. La cuenta del servicio debe poder acceder al directorio de evidencias y a los datos instalados; compruebe sus ACL durante el despliegue. Para un cierre de recuperación de clave local, no configure `GESTOR_SECRET_KEY` en ese proceso: un valor de entorno no acredita la clave histórica. El arranque exige que la clave local exista como archivo no vacío, pero no compara de nuevo su contenido: la correspondencia se verifica al cerrar y cualquier cambio administrativo posterior de esa clave requiere revisión. Si una fase anterior quedó incompleta o la evidencia no se puede verificar, el arranque sigue bloqueado.

Para inspeccionar la continuidad de un original sin instalar datos use `python -m app.desplazamiento_original inspeccionar --operacion OPERACION --confirmar-operacion OPERACION --componente base`; también se admiten `storage` y `clave`. La acción `desplazar` conserva el componente, pero no instala ni autoriza la recuperación.
