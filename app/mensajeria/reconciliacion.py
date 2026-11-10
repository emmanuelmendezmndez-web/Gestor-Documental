"""Diagnóstico y reconciliación explícita, sin acceso funcional a mensajes."""

import argparse
import hashlib
import json
import re
import sqlite3
import stat
from contextlib import contextmanager
from pathlib import PureWindowsPath

from app.configuracion import DB_PATH, STORAGE_DIR
from app.coordinacion import BloqueoDatos, BloqueoNoDisponible
from app.database import conectar as conectar_documental
from app.inventario_restauracion import inspeccionar
from app.mensajeria.base_datos import _conectar_infraestructura, inicializar
from app.mensajeria.identidad_documental import instalacion, preparar

REFERENCIAS_USUARIOS = """
    SELECT participante_a FROM conversaciones UNION
    SELECT participante_b FROM conversaciones UNION
    SELECT remitente_ref FROM mensajes UNION
    SELECT destinatario_ref FROM mensajes UNION
    SELECT usuario_ref FROM estado_participante UNION
    SELECT usuario_ref FROM cuotas UNION
    SELECT usuario_ref FROM operaciones UNION
    SELECT destinatario_ref FROM eventos
"""
REFERENCIAS_DOCUMENTOS = "SELECT DISTINCT documento_ref FROM mensajes WHERE tipo_adjunto='documento'"


@contextmanager
def _bases():
    with BloqueoDatos(exclusivo=False, con_generacion=True) as bloqueo, _conectar_infraestructura() as privada:
        info = inspeccionar(DB_PATH)
        if info is None or not stat.S_ISREG(info.st_mode) or not info.st_ino:
            raise ValueError("generacion_desconocida")
        generacion = hashlib.sha256(
            f"siged-mensajeria-v1:{bloqueo.generacion}:{info.st_dev}:{info.st_ino}".encode("ascii")
        ).hexdigest()
        with conectar_documental() as principal:
            # Orden fijo de las reservas. El bloqueo cooperativo excluye sustituciones
            # oficiales de la base mientras ambas instantáneas estén abiertas.
            principal.execute("BEGIN IMMEDIATE")
            privada.execute("BEGIN IMMEDIATE")
            yield principal, privada, generacion
            privada.commit()


def _referencias(privada, consulta):
    return {fila[0] for fila in privada.execute(consulta)}


def _vinculo(privada):
    return privada.execute(
        "SELECT instalacion_id, generacion_id FROM vinculo_identidad WHERE id=1"
    ).fetchone()


def _incidencias(principal, usuarios, documentos):
    conteo = dict.fromkeys((
        "usuarios_inexistentes", "usuarios_inactivos", "documentos_inexistentes",
        "documentos_no_disponibles", "identidades_contradictorias",
    ), 0)
    for tabla, referencias, columnas in (
        ("usuarios", usuarios, "activo"),
        ("documentos", documentos, "nombre_guardado, mensajeria_original, eliminado_en, tamano_bytes"),
    ):
        for referencia in referencias:
            if not isinstance(referencia, str) or not re.fullmatch("[0-9a-f]{32}", referencia):
                conteo["identidades_contradictorias"] += 1
                continue
            fila = principal.execute(
                f"SELECT {columnas} FROM {tabla} WHERE mensajeria_ref=?", (referencia,)
            ).fetchone()
            if fila is None:
                conteo[f"{tabla}_inexistentes"] += 1
            elif tabla == "usuarios":
                if fila[0] != 1:
                    conteo["usuarios_inactivos"] += 1
            else:
                _contar_documento(fila, conteo)
    return conteo


def _contar_documento(fila, conteo):
    nombre, original, eliminado, tamano = fila
    if (not isinstance(nombre, str) or not nombre or nombre in {".", ".."}
            or nombre.endswith((".", " ")) or ":" in nombre
            or PureWindowsPath(nombre).name != nombre or nombre != original):
        conteo["identidades_contradictorias"] += 1
        return
    if eliminado is not None:
        conteo["documentos_no_disponibles"] += 1
        return
    try:
        raiz = inspeccionar(STORAGE_DIR)
        archivo = inspeccionar(STORAGE_DIR / nombre) if raiz and stat.S_ISDIR(raiz.st_mode) else None
    except ValueError:
        conteo["identidades_contradictorias"] += 1
        return
    if archivo is None:
        conteo["documentos_no_disponibles"] += 1
    elif not stat.S_ISREG(archivo.st_mode) or archivo.st_size != tamano:
        conteo["identidades_contradictorias"] += 1


def _evaluar(principal, privada, generacion):
    actual = instalacion(principal)
    if actual is None:
        return {"estado": "generacion_desconocida"}
    previo = _vinculo(privada)
    if previo is not None and previo[0] != actual:
        return {"estado": "instalacion_incompatible"}
    usuarios = _referencias(privada, REFERENCIAS_USUARIOS)
    documentos = _referencias(privada, REFERENCIAS_DOCUMENTOS)
    if previo is None and (usuarios or documentos):
        return {"estado": "referencias_sin_procedencia"}
    conteo = _incidencias(principal, usuarios, documentos)
    if any(conteo.values()):
        return {
            "estado": "referencias_incompatibles",
            "generacion_cambio": previo is not None and previo[1] != generacion,
            "incidencias": conteo,
        }
    estado = "vinculo_pendiente"
    if previo is not None:
        estado = "identidad_coherente" if previo[1] == generacion else "generacion_incompatible"
    token = hashlib.sha256(f"{actual}:{generacion}".encode("ascii")).hexdigest()
    return {"estado": estado, "confirmacion": token}


def _ejecutar(accion, confirmacion=None):
    try:
        with _bases() as (principal, privada, generacion):
            if accion == "preparar":
                if instalacion(principal) is None and (
                    _vinculo(privada) is not None
                    or _referencias(privada, REFERENCIAS_USUARIOS)
                    or _referencias(privada, REFERENCIAS_DOCUMENTOS)
                ):
                    return {"estado": "generacion_desconocida"}
                preparar(principal)
            resultado = _evaluar(principal, privada, generacion)
            if accion == "reconciliar" and "confirmacion" in resultado:
                if resultado["confirmacion"] != confirmacion:
                    return {"estado": "confirmacion_invalida"}
                privada.execute(
                    "INSERT INTO vinculo_identidad VALUES (1, ?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET generacion_id=excluded.generacion_id "
                    "WHERE generacion_id!=excluded.generacion_id",
                    (instalacion(principal), generacion),
                )
                return {"estado": "identidad_coherente"}
            return resultado
    except BloqueoNoDisponible:
        return {"estado": "bloqueo_no_disponible"}
    except RuntimeError:
        return {"estado": "recuperacion_incompleta_o_incierta"}
    except (OSError, sqlite3.Error):
        return {"estado": "almacenamiento_no_disponible"}
    except ValueError as error:
        estado = str(error)
        return {"estado": estado if estado in {
            "generacion_desconocida", "identidad_contradictoria",
        } else "infraestructura_no_verificable"}


def diagnosticar():
    return _ejecutar("diagnosticar")


def preparar_identidades():
    return _ejecutar("preparar")


def reconciliar(confirmacion):
    return _ejecutar("reconciliar", confirmacion)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    acciones = parser.add_subparsers(dest="accion", required=True)
    for accion in ("inicializar", "preparar", "diagnosticar"):
        acciones.add_parser(accion)
    acciones.add_parser("reconciliar").add_argument("--confirmar", required=True)
    args = parser.parse_args()
    if args.accion == "inicializar":
        try:
            inicializar()
        except (OSError, RuntimeError, ValueError, sqlite3.Error):
            resultado = {"estado": "inicializacion_rechazada"}
        else:
            resultado = {"estado": "infraestructura_preparada"}
    else:
        resultado = _ejecutar(args.accion, getattr(args, "confirmar", None))
    print(json.dumps(resultado, ensure_ascii=False))
    return 0 if resultado["estado"] in {
        "infraestructura_preparada", "identidad_coherente", "vinculo_pendiente",
    } else 1


if __name__ == "__main__":
    raise SystemExit(main())
