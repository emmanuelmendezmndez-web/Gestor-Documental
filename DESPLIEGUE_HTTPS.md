# Preparación de HTTPS para SIGED en Windows

Esta es una preparación para revisión; no instala Caddy, configura Windows ni
crea certificados. No existe un nombre, dirección, CA ni certificado supuesto.
La arquitectura prevista sitúa Caddy y Uvicorn en el **mismo servidor**:

```text
Navegador LAN --HTTPS--> Caddy --HTTP en 127.0.0.1--> Uvicorn:8000
```

## Desarrollo local

`Iniciar SIGED.bat` inicia HTTP solo en `127.0.0.1:8000`, sin confiar en
encabezados reenviados y con `GESTOR_HTTPS_ONLY=0` para esa ejecución. No use
esta modalidad para credenciales o documentos institucionales desde la red.
Configure `GESTOR_DATA_DIR` con una carpeta de datos ficticia independiente;
sin esta variable SIGED utiliza el directorio del proyecto. Desarrollo y
producción no deben ejecutarse simultáneamente en el mismo puerto.

## Preparación institucional

1. Definir con el área de sistemas el servidor, un nombre estable y su resolución
   en la LAN. Una reserva DHCP y DNS interno son opciones, no requisitos asumidos.
   No usar una dirección que pueda cambiar sin plan de actualización.
2. Obtener un certificado de servidor PEM y su clave privada PEM de la CA
   institucional o de otra autoridad apropiada. El certificado debe incluir en
   Subject Alternative Name el nombre DNS usado; si se usa una IP, debe incluir
   esa IP como SAN de tipo IP. Planificar cadena intermedia, vigencia, renovación
   y revocación. Usar archivos con cadena completa según requiera el emisor.
3. Instalar el certificado **público** de la CA emisora en los clientes que no la
   conozcan, siguiendo la política institucional; si hay Active Directory se
   puede distribuir mediante directivas de grupo. Probar la cadena y el nombre
   en cada tipo de navegador administrado. Proteger la clave de la CA y la clave
   privada del servidor; nunca distribuirlas a clientes ni incluirlas en Git.
4. Instalar Caddy por el procedimiento autorizado por el ayuntamiento, revisar
   el origen y la versión y configurar una cuenta de servicio con acceso de
   lectura limitado a la clave. Este repositorio no instala Caddy.
5. Configurar para el proceso de Caddy las variables `SIGED_HOST` (solo nombre
   o IP, sin esquema, puerto ni ruta), `SIGED_CERT` y `SIGED_KEY` (rutas
   absolutas a los archivos PEM). En Windows se pueden usar rutas con `/`.
   Los valores son configuración administrativa confiable: Caddy los sustituye
   antes de interpretar el archivo. No usar valores suministrados por clientes.
   Configure también `GESTOR_DATA_DIR` y la clave de sesión de SIGED según la
   política institucional; no coloque secretos en estos archivos de ejemplo.
6. Validar la configuración con la versión instalada de Caddy, sin iniciarla:

   ```powershell
   caddy validate --config .\Caddyfile.ejemplo --adapter caddyfile
   ```

   Las variables de Caddy deben existir en el entorno del proceso que ejecuta
   la validación y, por separado, en el entorno del servicio real. No se indican
   valores por defecto para el nombre o los archivos. El ejemplo usa certificado
   suministrado, `auto_https off` y `admin off`: no abre HTTP para redirección ni
   la API administrativa. Con la API desactivada, los cambios requieren reiniciar
   Caddy mediante el mecanismo de servicio elegido.
7. Solo durante la instalación autorizada, iniciar `Iniciar SIGED produccion.bat`
   y el servicio Caddy por separado. El lanzador fija `GESTOR_HTTPS_ONLY=1`,
   `--host 127.0.0.1`, `--proxy-headers` y
   `--forwarded-allow-ips 127.0.0.1`. No abre navegador ni inicia Caddy.
   El usuario de Windows que ejecuta SIGED necesita acceso solo a sus datos y
   clave de sesión; Caddy necesita acceso a su certificado y clave TLS.

El ejemplo de Caddy conserva `Host` por defecto, reemplaza `X-Forwarded-For`
por la IP de la conexión directa y establece `X-Forwarded-Proto: https`.
No añada `trusted_proxies` ni otra capa de proxy sin rediseñar y probar la
cadena de confianza. Uvicorn solo acepta esas cabeceras desde loopback; no use
`--forwarded-allow-ips '*'`. Otros procesos locales capaces de conectar a
`127.0.0.1:8000` pueden falsificar esas cabeceras: proteja el acceso al servidor
y las cuentas de servicio. Si Caddy se instala en otra máquina, esta configuración
ya no aplica; se requiere un diseño separado para proteger el enlace y la IP.

El proxy conserva el Host público, necesario junto con el esquema reenviado para
las comprobaciones de Origin/Referer de CSRF. La cookie `Secure` evita su envío
por HTTP, pero no cifra el tráfico ni impide por sí sola el acceso al puerto.
No confunda esa opción con habilitar HTTPS.

## Comprobación antes de uso

### Tamaño de las solicitudes

SIGED conserva el límite de 20 MiB por archivo. El middleware ASGI limita el
cuerpo HTTP completo, incluidos campos y separadores multipart, a 21 MiB
(22 020 096 bytes) por defecto, tanto en desarrollo local como en producción.
Para cambiarlo, configure `GESTOR_MAX_CUERPO_BYTES` en el proceso de Uvicorn antes
de iniciarlo: debe ser un entero decimal mayor que 20 MiB. Un valor inválido
impide el arranque. Deje margen suficiente para los campos multipart; el límite
por archivo sigue siendo 20 MiB aunque aumente el límite total. Es un límite
global del cuerpo de cada solicitud, no una cuota acumulada de almacenamiento.

El middleware rechaza de inmediato un `Content-Length` excesivo y cuenta los
bytes realmente recibidos cuando el cuerpo se transmite. No lee deliberadamente
el resto una vez alcanzado el límite. El servidor, el proxy o el sistema operativo
pueden haber almacenado previamente parte de los datos; esta protección no
garantiza un límite global de memoria con muchas solicitudes concurrentes.

En producción, el `Caddyfile.ejemplo` añade `request_body max_size` con el mismo
valor predeterminado. Se ha verificado su presencia en el código de Caddy
2.10.2; se propone 2.10.2 o posterior, sujeto a validación en el servidor. Trate
esta integración como **experimental** hasta probar la versión elegida: la
documentación actual marca específicamente la subdirectiva `set` como
experimental desde 2.10.0, pero no aplica esa etiqueta a `max_size`. Las
versiones pueden diferir en el momento y la forma de devolver 413. Configure
`SIGED_MAX_CUERPO_BYTES` en Caddy y `GESTOR_MAX_CUERPO_BYTES` en Uvicorn con el
mismo número de bytes. Un límite distinto en el proxy puede rechazar antes una
solicitud válida o dejar que SIGED la rechace; el middleware sigue siendo la
defensa local, también sin Caddy. El comportamiento del proxy ante cuerpos sin
longitud o errores de lectura debe verificarse en el servidor definitivo.
Referencia: [request_body de Caddy](https://caddyserver.com/docs/caddyfile/directives/request_body).

- Desde un cliente administrado, abrir `https://<nombre-acordado>/` sin omitir
  advertencias y verificar SAN, cadena, vencimiento y renovación del certificado.
- Verificar inicio y cierre de sesión, carga y descarga con datos ficticios;
  confirmar `Secure`, `HttpOnly` y `SameSite=Lax` en la cookie y las peticiones
  con origen HTTPS correcto. Un origen ajeno debe seguir rechazándose por CSRF.
- Confirmar que desde otra computadora `http://<servidor>:8000` no conecta y que
  ninguna otra instancia de Uvicorn escucha en interfaces de red, incluidas IPv6.
  La política del firewall debe permitir solo los accesos institucionales acordados.
- Verificar que actividad y límites de intentos usan la IP del cliente real;
  probar encabezados `X-Forwarded-*` falsificados desde la LAN y confirmar que no
  alteran la IP ni el esquema reconocido. Revisar los logs sin exponer secretos.
- El acceso HTTP no se redirige en el ejemplo. Distribuir directamente la URL
  HTTPS; una redirección no protege credenciales enviadas antes de ella.

## Reversión

Documentar y respaldar las configuraciones antes del cambio. Si la validación
falla, detener Caddy y el lanzador institucional, conservar evidencias y volver
a la configuración aprobada por sistemas. No volver a publicar Uvicorn en la
LAN por HTTP. Para diagnóstico local se puede usar el modo de desarrollo con
datos ficticios y puerto loopback; una cookie `Secure` institucional no debe
reutilizarse como mecanismo de sesión para ese modo.

Referencias: [Caddy TLS](https://caddyserver.com/docs/caddyfile/directives/tls),
[proxy inverso y cabeceras](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy),
[FastAPI detrás de un proxy](https://fastapi.tiangolo.com/advanced/behind-a-proxy/)
y [distribución de certificados en Windows](https://learn.microsoft.com/en-us/windows-server/identity/ad-cs/distribute-certificates-group-policy).
