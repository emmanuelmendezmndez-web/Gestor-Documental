"""Arranque experimental en loopback con límites de transporte obligatorios."""

import argparse
import os
from importlib.util import find_spec

import uvicorn


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--habilitar", action="store_true", required=True)
    parser.add_argument("--origen", action="append", required=True)
    parser.add_argument("--puerto", type=int, default=8000)
    parser.add_argument("--proxy-loopback", action="store_true")
    args = parser.parse_args()
    if not all(os.environ.get(k, "").strip() for k in ("GESTOR_DATA_DIR", "GESTOR_MENSAJERIA_DIR")):
        parser.error("Configura los directorios explícitos del entorno de prueba")
    if find_spec("websockets") is None:
        parser.error("Se requiere el grupo opcional mensajeria-ws")
    from app.configuracion import BASE_DIR, DATA_DIR

    if DATA_DIR == BASE_DIR or not 1 <= args.puerto <= 65535:
        parser.error("Se requiere un directorio de datos separado y un puerto válido")
    from app.main import COOKIE_HTTPS_ONLY, app
    from app.mensajeria.websocket import MAX_TRAMA, instalar
    from app.seguridad import obtener_clave_secreta

    if args.proxy_loopback and not COOKIE_HTTPS_ONLY:
        parser.error("El modo de proxy requiere GESTOR_HTTPS_ONLY")
    try:
        instalar(app, origenes=args.origen, secreto=obtener_clave_secreta(), https_only=COOKIE_HTTPS_ONLY)
    except ValueError as error:
        parser.error(str(error))
    uvicorn.run(
        app, host="127.0.0.1", port=args.puerto, workers=1,
        proxy_headers=args.proxy_loopback, forwarded_allow_ips="127.0.0.1",
        ws="websockets", ws_max_size=MAX_TRAMA, ws_max_queue=2, ws_per_message_deflate=False,
        ws_ping_interval=20, ws_ping_timeout=20, log_level="warning", access_log=False,
    )


if __name__ == "__main__":
    main()
