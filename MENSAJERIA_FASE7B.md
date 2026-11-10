# Interfaz experimental de Mensajería

Usa el almacén ficticio y la reconciliación del [laboratorio de Fase 7A](MENSAJERIA_FASE7A.md#prueba-pendiente-en-caddy).
Con esas variables de entorno, ejecuta el siguiente comando e inicia
sesión con una cuenta del laboratorio. En el navegador de la misma
máquina, abre `http://127.0.0.1:8001/mensajeria`.

```powershell
$env:GESTOR_HTTPS_ONLY = '0'
.\.venv\Scripts\python.exe -m app.mensajeria.servidor_ws --habilitar --http-api --interfaz --puerto 8001 --origen http://127.0.0.1:8001
```

El lanzador normal carece de la vista. El flag `--interfaz` requiere
`--http-api` y habilita el enlace lateral y la campana en la instancia
experimental. La API se autentica con la sesión revocable de 7A.

## Contratos utilizados

- Las proyecciones existentes de destinatarios y conversaciones incluyen
  `area`. Cada conversación incluye `ultimo` con el texto y el instante
  del último mensaje vigente, y `no_leidos` para el participante autenticado.
  Cada mensaje incluye `enviado` para alinear la burbuja desde la
  perspectiva de ese participante. Se conservan los cursores de 7A. El
  filtro de conversaciones busca en las páginas cargadas y permite
  consultar más páginas. Lo mismo aplica al filtro de destinatarios.
- La vista `GET /mensajeria` sirve un fragmento HTML paginado cuando recibe
  `destinatario`, `buscar` y, para continuar, `despues`. Usa sesión y
  origen de 7A y aplica el filtro documental a ambos participantes antes
  de mostrar títulos. El fragmento contiene referencias opacas. El POST
  existente verifica de nuevo la autorización y la identidad del original.
  La interfaz ofrece la modalidad «Visualizar y descargar» con descarga
  autorizada mientras se completa la vista previa aislada.
- El formulario conserva en memoria la clave de una operación incierta.
  Después de una preparación confirmada, el reintento repite solamente la
  confirmación con la misma clave y los mismos datos. Una recarga o cierre
  de la pestaña elimina el borrador y la clave de memoria.
- «Marcar como leídos» actualiza los mensajes recibidos de las páginas
  abiertas. El contador lateral usa `no_leidos` global de
  `/sincronizacion`, que incluye las conversaciones archivadas. La
  cuota también procede del servidor.
- La vista carga por HTTP al entrar, al volver a una pestaña visible y
  después de envíos, lecturas o archivado. El evento del DOM
  `siged:mensajeria-actualizar` solicita esa misma sincronización.

## Pendientes de Fase 7C

- Conectar los eventos autenticados del WebSocket con la actualización
  HTTP y comprobar WSS con el proxy y desde otro dispositivo.
- Definir la fuente de notificaciones pendientes de la campana. El panel
  actual ofrece acceso a Mensajería y presenta su estado vacío. Su futura
  cifra debe proceder de notificaciones autorizadas del servidor.
- Integrar el renderizado aislado de documentos, revalidar permisos y
  habilitar la modalidad «Solo visualizar» en el compositor.
