# API HTTP experimental de Mensajería

El arranque habitual de SIGED no monta esta API. El lanzador experimental
requiere `--habilitar --http-api`, orígenes explícitos y directorios
separados. La API reutiliza la cookie firmada y la sesión revocable
de la Fase 6. Se requiere un login experimental después de habilitarla
o después de reconciliar una nueva generación.

El actor procede de la sesión y no de la petición. Cada transacción del
motor vuelve a comprobar sesión, identidad y generación, incluida la
confirmación después de leer el archivo. Las consultas HTTP abren
transacciones de lectura. Las escrituras verifican el token existente
en `X-CSRF-Token` y las reglas comunes de Origin/Referer antes de leer
el cuerpo. La API también verifica que Host y esquema correspondan a
un origen habilitado. El arranque experimental confía en encabezados
de proxy únicamente en el modo explícito para Caddy en loopback.

## Rutas

El prefijo es `/mensajeria/api/v1`. En la tabla,
`C = /conversaciones/{chat}` y `M = C/mensajes/{mensaje}`.
Los identificadores que usa el cliente son referencias opacas.

| Método | Ruta | Entrada y resultado |
| --- | --- | --- |
| GET | `/destinatarios` | `despues`, `limite`. Perfiles activos elegibles, con referencia y nombre de perfil. |
| GET | `/conversaciones` | `archivadas`, `despues`, `limite`. Conversaciones propias y perfil visible del otro participante. |
| GET | `C/mensajes` | `antes`, `limite`. Mensajes confirmados en los últimos 15 días. |
| GET | `/cuota` | Día institucional, envíos, límite y restantes. |
| GET | `/sincronizacion` | Mismos parámetros de conversación. Página, cuota y contador de no leídos de todas las conversaciones propias, incluidas las archivadas. |
| POST | `/envios/externos/preparar` | Multipart con una parte de archivo `archivo`. Cabeceras `X-SIGED-Destinatario` e `Idempotency-Key`. Devuelve `clave`, `nombre` y `tamano_bytes`. |
| POST | `/envios/externos/confirmar` | JSON con `destinatario`, `clave`, `texto`, `nombre` y `tamano_bytes`. Devuelve `mensaje`. |
| POST | `/envios/biblioteca` | JSON con `destinatario`, `clave`, `texto`, `documento` y `modalidad`. Devuelve `mensaje`. |
| GET | `M/adjunto` | Tarjeta con estado, origen, formato, extensión, nombre, vencimiento y acciones autorizadas. El tamaño se informa para externos. Una tarjeta revocada devuelve solo `estado: no_disponible`. |
| GET | `M/adjunto/descarga` | Flujo binario de un adjunto autorizado. |
| GET | `M/adjunto/vista` | 501 si la futura vista correspondería a ese usuario. 404 si falta autorización o disponibilidad. |
| POST | `M/lectura` | Marca lectura del destinatario. |
| POST | `C/archivo` | JSON con `archivada` booleana. |

Las páginas usan `elementos` y `siguiente`. Los límites son de 1 a
50, con 25 por defecto. El cursor de mensajes combina instante e ID
para ordenar incluso dos confirmaciones en el mismo segundo. La
lectura solo cambia con su POST. Tras una señal WebSocket o una
reconexión, el cliente consulta `/sincronizacion` y vuelve a consultar
la conversación abierta. Los GET no confirman entregas de eventos.

Generar una clave hexadecimal aleatoria de 32 caracteres por envío.
Conservarla para reintentar la misma preparación y confirmación. El
reintento verifica los bytes de la preparación sin guardar otra copia.
El motor resuelve la referencia privada del archivo desde el actor y la
clave, devuelve el mismo mensaje al repetir una confirmación y rechaza
cambios de contenido. El contador de 50 solo se consume al confirmar.
La modalidad de Biblioteca es `visualizar` o
`visualizar_y_descargar`. La consulta revalida permisos, papelera y
vigencia. La vista previa queda pendiente de 7C y nunca se convierte
en una descarga. Los originales de Biblioteca permanecen en su
ubicación.

Los errores de aplicación tienen la forma `{"error":"codigo"}`.
Se usan 401 para sesión inválida, 403 para CSRF u origen, 404 genérico
para recursos no autorizados, 409 para conflicto de clave o generación,
408 para plazo, 410 para preparación vencida, 413 para tamaño,
415 para formato, 429 para cuota o cupos y 507 para falta de espacio.
Caddy o el middleware exterior pueden devolver su propio 413 antes de
que la API reciba la petición. El cliente debe decidir primero por
estado HTTP.

## Límites y archivos

El parser estándar de formularios de Starlette usa
`SpooledTemporaryFile` y pasa a disco desde 1 MiB. Esta ruta usa
directamente el parser incremental de `python-multipart` ya instalado.
Acepta una sola parte, hasta cuatro cabeceras y 2 KiB por cabecera,
con frontera de hasta 70 bytes. Los otros datos de operación viajan
en cabeceras o en el JSON separado. El parser entrega bloques de
64 KiB al servicio existente de adjuntos sin crear un spool adicional.
La fase de preparación existente comprueba tamaño real, formato,
capacidad y espacio y limpia el archivo parcial tras un corte. Las
transacciones SQLite se abren para reservas y confirmaciones breves,
fuera de la espera del cuerpo.

Se conserva **20 MiB por archivo** y se aplica a esta ruta un máximo
de **21 MiB de cuerpo** o el límite exterior si es menor. El JSON
tiene un máximo de 4 KiB. La recepción permite **180 segundos en total**
y **15 segundos de espera sin datos** por lectura. El JSON permite
10 segundos en total y cinco sin datos. Hay cuatro cargas y ocho
descargas HTTP simultáneas por proceso. El envío de una descarga
queda acotado a cinco minutos. Los límites independientes de Biblioteca
y las reservas configurables de Fase 4 siguen vigentes.

La descarga usa el identificador NTFS verificado por el servicio, con
`attachment`, nombre codificado en `filename*`,
`application/octet-stream`, `private, no-store`, `nosniff` y CSP
restrictiva. El identificador permanece abierto hasta terminar o
interrumpirse la transmisión. Una descarga admitida antes del
vencimiento puede concluir mientras la limpieza espera que Windows
libere el archivo. Las nuevas peticiones se deniegan desde el vencimiento.

## Prueba pendiente en Caddy

La prueba directa usa Uvicorn real y loopback. Caddy no está disponible
en el entorno de esta ejecución. Los pasos siguientes son para una
instancia de laboratorio, sin exposición externa.

En PowerShell desde el repositorio, preparar un almacén vacío y crear
dos cuentas ficticias con el asistente. Usar `alfa` y `beta` como
usuarios. El backend opcional de Fase 6 debe estar disponible en el
entorno.

```powershell
$labSiged = Join-Path $env:TEMP ('siged-http-lab-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $labSiged | Out-Null
$env:GESTOR_DATA_DIR = $labSiged
$env:GESTOR_MENSAJERIA_DIR = Join-Path $labSiged '.siged-mensajeria'
$pySiged = '.\.venv\Scripts\python.exe'
& $pySiged -m app.crear_usuario
& $pySiged -m app.crear_usuario
& $pySiged -m app.mensajeria.reconciliacion inicializar
$vinculoSiged = & $pySiged -m app.mensajeria.reconciliacion preparar | ConvertFrom-Json
& $pySiged -m app.mensajeria.reconciliacion reconciliar --confirmar $vinculoSiged.confirmacion
$env:GESTOR_HTTPS_ONLY = '0'
& $pySiged -m app.mensajeria.servidor_ws --habilitar --http-api --puerto 8001 --origen http://127.0.0.1:8001 --origen http://127.0.0.1:8081
```

En otra consola, guardar un Caddyfile de laboratorio con este bloque,
validarlo con `caddy validate --config .\Caddyfile.lab --adapter caddyfile`
y arrancarlo con `caddy run --config .\Caddyfile.lab --adapter caddyfile`.
`request_body max_size` es experimental desde Caddy 2.10. El ejemplo
de SIGED pide 2.10.2 o posterior. No es necesario usar directivas
experimentales de plazos en el proxy para probar los plazos de la API.
[Documentación de request_body](https://caddyserver.com/docs/caddyfile/directives/request_body)

```caddyfile
{
    admin off
    auto_https off
}
http://127.0.0.1:8081 {
    bind 127.0.0.1
    request_body {
        max_size 22020096
    }
    reverse_proxy 127.0.0.1:8001
}
```

En una tercera consola, asignar a `$labSiged` la misma carpeta de
prueba creada en la primera. La operación usa el login real, su cookie
y el CSRF del formulario. Usar únicamente la contraseña ficticia.

```powershell
$baseSiged = 'http://127.0.0.1:8081'
$apiSiged = "$baseSiged/mensajeria/api/v1"
$jarSiged = Join-Path $labSiged 'cookie-prueba.txt'
$formSiged = (curl.exe -fsS -c $jarSiged "$baseSiged/login") -join "`n"
$csrfSiged = [regex]::Match($formSiged, 'name="csrf_token" value="([^"]+)"').Groups[1].Value
$passSiged = Read-Host 'Contraseña ficticia de alfa'
curl.exe -fsS -b $jarSiged -c $jarSiged -H "Origin: $baseSiged" --data-urlencode 'usuario=alfa' --data-urlencode "password=$passSiged" --data-urlencode "csrf_token=$csrfSiged" "$baseSiged/login" | Out-Null
Remove-Variable passSiged
$inicioSiged = (curl.exe -fsS -b $jarSiged -c $jarSiged "$baseSiged/inicio") -join "`n"
$csrfSiged = [regex]::Match($inicioSiged, 'name="csrf-token" content="([^"]+)"').Groups[1].Value
$destinoSiged = ((curl.exe -fsS -b $jarSiged "$apiSiged/destinatarios") | ConvertFrom-Json).elementos[0].referencia
$claveSiged = [guid]::NewGuid().ToString('N')
$archivoSiged = Join-Path $labSiged '20mib.txt'
$bloqueSiged = [Text.Encoding]::ASCII.GetBytes(('a' * 65536))
$flujoSiged = [IO.File]::Create($archivoSiged)
try { for ($iSiged = 0; $iSiged -lt 320; $iSiged++) { $flujoSiged.Write($bloqueSiged, 0, $bloqueSiged.Length) } }
finally { $flujoSiged.Dispose() }
$preparadoSiged = curl.exe -fsS -b $jarSiged -H "Origin: $baseSiged" -H "X-CSRF-Token: $csrfSiged" -H "X-SIGED-Destinatario: $destinoSiged" -H "Idempotency-Key: $claveSiged" -F "archivo=@$archivoSiged;type=text/plain" "$apiSiged/envios/externos/preparar" | ConvertFrom-Json
$jsonSiged = @{ destinatario=$destinoSiged; clave=$claveSiged; texto='Ensayo ficticio'; nombre=$preparadoSiged.nombre; tamano_bytes=$preparadoSiged.tamano_bytes } | ConvertTo-Json -Compress
$entradaSiged = Join-Path $labSiged 'confirmar.json'
[IO.File]::WriteAllText($entradaSiged, $jsonSiged)
$mensajeSiged = (curl.exe -fsS -b $jarSiged -H "Origin: $baseSiged" -H "X-CSRF-Token: $csrfSiged" -H 'Content-Type: application/json' --data-binary "@$entradaSiged" "$apiSiged/envios/externos/confirmar" | ConvertFrom-Json).mensaje
$chatSiged = ((curl.exe -fsS -b $jarSiged "$apiSiged/conversaciones") | ConvertFrom-Json).elementos[0].id
$copiaSiged = Join-Path $labSiged 'descargado.txt'
curl.exe -fsS -b $jarSiged -D (Join-Path $labSiged 'cabeceras.txt') -o $copiaSiged "$apiSiged/conversaciones/$chatSiged/mensajes/$mensajeSiged/adjunto/descarga"
(Get-FileHash $archivoSiged).Hash -eq (Get-FileHash $copiaSiged).Hash
```

Para comprobar 413, ejecutar este bloque después de la prueba de
subida y descarga. Para aislar la respuesta del servidor, repetir
el login y el bloque con `$baseSiged = 'http://127.0.0.1:8001'` y
una jar nueva.

```powershell
$excesoSiged = Join-Path $labSiged 'exceso.txt'
$flujoSiged = [IO.File]::Create($excesoSiged)
try { $flujoSiged.SetLength(22020097) }
finally { $flujoSiged.Dispose() }
$claveSiged = [guid]::NewGuid().ToString('N')
curl.exe -sS -b $jarSiged -o NUL -w '%{http_code}\n' -H "Origin: $baseSiged" -H "X-CSRF-Token: $csrfSiged" -H "X-SIGED-Destinatario: $destinoSiged" -H "Idempotency-Key: $claveSiged" -F "archivo=@$excesoSiged;type=text/plain" "$apiSiged/envios/externos/preparar"
```

Para verificar 408 por la API, usar `curl.exe --limit-rate 1k` con un
multipart ficticio de 1 MiB. Para probar una interrupción, cancelar
la carga con `Ctrl+C` y comprobar que no se confirmó un mensaje.

Para HTTPS, detener ambas instancias de laboratorio y arrancar SIGED
en la primera consola con el mismo almacén ficticio.

```powershell
$env:GESTOR_HTTPS_ONLY = '1'
& $pySiged -m app.mensajeria.servidor_ws --habilitar --http-api --puerto 8001 --proxy-loopback --origen https://localhost:8443
```

Reemplazar el Caddyfile de laboratorio con el siguiente bloque y
repetir los comandos de validación y arranque de Caddy. Definir
`SIGED_CERT` y `SIGED_KEY` en la consola de Caddy con las rutas
del certificado de laboratorio y su clave. El certificado debe
incluir `localhost` y ser de confianza para el cliente.

```caddyfile
{
    admin off
    auto_https disable_redirects
}
https://localhost:8443 {
    bind 127.0.0.1
    tls "{$SIGED_CERT}" "{$SIGED_KEY}"
    request_body {
        max_size 22020096
    }
    reverse_proxy 127.0.0.1:8001 {
        header_up X-Forwarded-Proto https
    }
}
```

Repetir el bloque de curl con
`$baseSiged = 'https://localhost:8443'` y una jar nueva. Verificar
`Secure`, `SameSite=Lax` y coincidencia de SHA-256. Mantener
activa la validación del certificado.

La interfaz de 7B debe tratar nombres y textos como texto, no HTML.
Para 7C quedan la previsualización con renderizado aislado y
revalidación antes de entregar el resultado, la auditoría de integración
y la validación WSS desde otro dispositivo.
