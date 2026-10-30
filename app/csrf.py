"""Protección CSRF asociada a la sesión de SIGED."""

import hmac
import secrets
from urllib.parse import urlsplit

from fastapi import HTTPException, Request

METODOS_SEGUROS = {"GET", "HEAD", "OPTIONS", "TRACE"}


def token_csrf(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not isinstance(token, str) or not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


def _origen(valor: str) -> tuple[str, str, int] | None:
    try:
        url = urlsplit(valor)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
            return None
        puerto = url.port if url.port is not None else (443 if url.scheme == "https" else 80)
        return url.scheme, url.hostname.lower(), puerto
    except ValueError:
        return None


async def validar_csrf(request: Request) -> None:
    if request.method in METODOS_SEGUROS:
        return

    origen = request.headers.get("origin")
    referencia = request.headers.get("referer")
    if origen is not None or referencia is not None:
        recibido = _origen(origen if origen is not None else referencia)
        if recibido is None or recibido != _origen(str(request.base_url)):
            raise HTTPException(status_code=403, detail="El origen de la solicitud no está autorizado.")

    esperado = request.session.get("csrf_token")
    recibido = request.headers.get("x-csrf-token")
    tipo = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if recibido is None and tipo in {"application/x-www-form-urlencoded", "multipart/form-data"}:
        formulario = await request.form()
        valores = formulario.getlist("csrf_token")
        recibido = valores[0] if len(valores) == 1 and isinstance(valores[0], str) else None
    if (not isinstance(esperado, str) or not isinstance(recibido, str)
            or not recibido.isascii() or not hmac.compare_digest(esperado, recibido)):
        raise HTTPException(status_code=403, detail="La sesión del formulario ha caducado. Recarga la página e inténtalo de nuevo.")
