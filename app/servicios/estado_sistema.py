"""Comprobaciones de solo lectura para el indicador de Inicio."""

import os
import shutil
import sqlite3
from contextlib import closing
from threading import Lock
from time import monotonic

from app.configuracion import DB_PATH, STORAGE_DIR
from app.seguridad import PERMISOS

_INTERVALO = 60
_bloqueo = Lock()
_cache = {}
_ERROR_BASE = "No se pudo comprobar la base de datos principal."


def _abrir_lectura(ruta):
    return closing(sqlite3.connect(ruta.as_uri() + "?mode=ro", uri=True, timeout=1))


def _resultado(criticas=(), parciales=()):
    return {
        "estado": "critico" if criticas else "degradado" if parciales else "operativo",
        "incidencias": [*criticas, *parciales],
    }


def _comprobar_mensajeria(principal):
    from app.mensajeria.base_datos import (
        APPLICATION_ID,
        NOMBRE_BASE,
        VERSION,
        _base_segura,
    )
    from app.mensajeria.configuracion import directorio_configurado
    from app.mensajeria.identidad_documental import instalacion
    from app.temporal_privado import verificar_acl_base_privada

    raiz = directorio_configurado()
    verificar_acl_base_privada(raiz, NOMBRE_BASE, 2)
    ruta = raiz / NOMBRE_BASE
    for sufijo in ("", "-journal", "-wal", "-shm"):
        _base_segura(ruta.with_name(ruta.name + sufijo))
    with _abrir_lectura(ruta) as privada:
        if (privada.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID
                or privada.execute("PRAGMA user_version").fetchone()[0] != VERSION):
            return "La base de Mensajería tiene una identidad o versión inesperada."
        privada.execute("SELECT id FROM conversaciones LIMIT 1").fetchone()
        privada.execute("SELECT id FROM mensajes LIMIT 1").fetchone()
        vinculo = privada.execute(
            "SELECT instalacion_id, generacion_id FROM vinculo_identidad WHERE id = 1"
        ).fetchone()
        identidad = instalacion(principal)
        if not vinculo or not identidad or vinculo[0] != identidad or not vinculo[1]:
            return "No se pudo verificar el vínculo de Mensajería con la base documental."
    return None


def _comprobar(principal, mensajeria_habilitada):
    criticas, parciales = [], []
    try:
        principal.execute("SELECT id FROM documentos LIMIT 1").fetchone()
        principal.execute("SELECT id FROM expedientes LIMIT 1").fetchone()
    except sqlite3.Error:
        criticas.append(_ERROR_BASE)
    try:
        with os.scandir(STORAGE_DIR) as entradas:
            next(entradas, None)
        uso = shutil.disk_usage(STORAGE_DIR)
        if uso.total <= 0:
            criticas.append("No se pudo comprobar la capacidad del almacenamiento documental.")
        elif uso.free <= 0:
            criticas.append("El almacenamiento documental no tiene espacio disponible.")
        elif uso.free * 10 <= uso.total:
            parciales.append("Al almacenamiento documental le queda un 10 % o menos de espacio libre.")
    except OSError:
        criticas.append("No se pudo comprobar el almacenamiento documental.")
    if mensajeria_habilitada and _ERROR_BASE not in criticas:
        try:
            incidencia = _comprobar_mensajeria(principal)
        except (OSError, sqlite3.Error, ValueError):
            incidencia = "No se pudo comprobar la base privada de Mensajería."
        if incidencia:
            parciales.append(incidencia)
    return _resultado(criticas, parciales)


def consultar_estado_sistema(sesion, mensajeria_habilitada):
    """Valida el permiso de lectura y comparte las sondas entre usuarios."""
    usuario_id = sesion.get("usuario_id")
    version = sesion.get("version")
    if type(usuario_id) is not int or usuario_id <= 0 or type(version) is not int:
        return 401, {"error": "sesion_no_valida"}
    try:
        with _abrir_lectura(DB_PATH) as principal:
            usuario = principal.execute(
                "SELECT rol, version_sesion FROM usuarios WHERE id = ? AND activo = 1",
                (usuario_id,),
            ).fetchone()
            if usuario is None or usuario[1] != version:
                return 401, {"error": "sesion_no_valida"}
            if "ver" not in PERMISOS.get(usuario[0], ()):
                return 403, {"error": "sin_permiso"}
            with _bloqueo:
                vence, resultado = _cache.get(mensajeria_habilitada, (0, None))
                if monotonic() >= vence:
                    resultado = _comprobar(principal, mensajeria_habilitada)
                    _cache[mensajeria_habilitada] = (monotonic() + _INTERVALO, resultado)
            return 200, resultado
    except (OSError, sqlite3.Error):
        # Solo una cookie de sesión firmada puede recibir este diagnóstico genérico
        # cuando la base no permite volver a validar al usuario.
        return 200, _resultado((_ERROR_BASE,))
