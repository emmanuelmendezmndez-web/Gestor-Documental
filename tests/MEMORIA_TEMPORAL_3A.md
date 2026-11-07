# Memoria temporal de Clippy

El módulo `app/static/memoria_temporal.js` crea instancias independientes en memoria de JavaScript. `base.html` carga el módulo y `busqueda_asistida.js` conecta el estado al diálogo existente.

API: `crearMemoriaTemporal()` devuelve `iniciar(consulta, intencion, filtros)`, `consultar()`, `obtenerUltimoValido()`, `actualizar(cambios, origen)`, `quitar(campo, origen)`, `marcarManual(campo)`, `pendiente(id)`, `resolver(id, opcion, cambios)`, `cancelar()`, `finalizar()` y `reiniciar()`. Las intenciones admitidas son `documentos` y `expedientes`; los campos admitidos son los filtros existentes de Biblioteca. Las aclaraciones guardan identificadores acotados, no mensajes de conversación. Las lecturas devuelven copias.

La eliminación manual también protege al campo frente a sugerencias posteriores. Las modificaciones propuestas son atómicas: si se proporciona un intervalo inválido, se conserva el último estado válido. No hay llamadas de red ni acceso a DOM, archivos o almacenamiento web.

La interfaz inicia una interacción al abrir el diálogo, registra cambios y aclaraciones, y descarta su estado al cerrar, cancelar, finalizar o recibir `pagehide`. «Editar consulta» conserva el estado mientras la frase no cambie. Si cambia una frase con filtros editados o se elige una búsqueda rápida, el diálogo ofrece conservar la consulta previa o comenzar una interacción limpia. La recarga o cierre de pestaña destruye la instancia al destruirse la página. La interfaz pasa solo el campo de consulta documental y controles de filtros, no contraseñas, contenido de archivos ni historiales de conversación; el módulo no accede a esos elementos y no puede determinar por sí solo si el texto escrito en una consulta contiene información sensible. La autorización y filtrado por área siguen correspondiendo al servidor, no a la memoria.

Las pruebas automatizadas cubren instancias independientes y ciclos de vida. Una cuenta que cambia en otra pestaña no activa automáticamente `pagehide` en una pestaña que permanece abierta: esa pestaña puede conservar su contexto local hasta cerrarse, recargarse o cancelarse; el servidor sigue comprobando la sesión y los permisos en cada solicitud.

Ejecutar desde la raíz: `node --test tests/memoria_temporal.test.js tests/busqueda_asistida.test.js tests/interprete_fechas.test.js`.
