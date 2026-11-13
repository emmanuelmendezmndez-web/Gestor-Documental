"""Preferencias locales de Clippy, aisladas por usuario y sin leer archivos."""

import json
from typing import Annotated, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response

from app.catalogos import CATEGORIAS, DEPARTAMENTOS
from app.database import conectar
from app.seguridad import requiere_permiso
from app.servicios.diagnostico_clippy import (
    ACCIONES,
    diagnosticar_almacenamiento,
    diagnosticar_documento,
    diagnosticar_estado,
    diagnosticar_permisos,
)

router = APIRouter(prefix="/asistente", dependencies=[Depends(requiere_permiso("ver"))])
SECCIONES = {"inicio", "biblioteca", "buscar", "subir", "expedientes", "papelera", "usuarios", "actividad", "cuenta"}
CLAVES_FILTRO = {"buscar", "categoria", "departamento", "oficio", "desde", "hasta"}


@router.get("/diagnostico")
def diagnostico(
    request: Request,
    response: Response,
    tema: Literal["sistema", "mensajeria", "almacenamiento", "documento", "permisos"],
    registro: Annotated[int | None, Query(ge=1, le=10**18 - 1)] = None,
    accion: str | None = None,
):
    usuario = request.state.usuario
    response.headers["Cache-Control"] = "private, no-store"
    if tema == "documento":
        mensaje = diagnosticar_documento(usuario, registro)
    elif tema == "permisos":
        if accion is not None and accion not in ACCIONES:
            raise HTTPException(status_code=400, detail="Acción no reconocida.")
        mensaje = diagnosticar_permisos(usuario, accion)
    elif tema == "almacenamiento":
        mensaje = diagnosticar_almacenamiento()
    else:
        mensajeria = bool(getattr(request.app.state, "mensajeria_http_instalada", False))
        mensaje = diagnosticar_estado(request.session, mensajeria, tema)
    return {"usuario_id": usuario["id"], "mensaje": mensaje}


def _filtros_seguros(datos: dict, usuario: dict) -> dict[str, str]:
    filtros = {}
    for clave in CLAVES_FILTRO:
        valor = datos.get(clave)
        if not isinstance(valor, str) or not (valor := valor.strip()):
            continue
        if clave == "categoria" and valor not in CATEGORIAS:
            continue
        if clave == "departamento":
            if valor not in DEPARTAMENTOS:
                continue
            if usuario["rol"] != "admin" and valor != usuario.get("departamento"):
                continue
        if clave in {"desde", "hasta"}:
            from datetime import date
            try:
                date.fromisoformat(valor)
            except ValueError:
                continue
        filtros[clave] = valor[:200 if clave == "buscar" else 60]
    return filtros


@router.post("/habito")
def registrar_habito(request: Request, datos: Annotated[dict, Body()]):
    tipo = datos.get("tipo")
    usuario = request.state.usuario
    if not usuario["clippy_habitos"]:
        return {"guardado": False}
    if tipo == "busqueda":
        filtros = _filtros_seguros(datos.get("filtros", {}) if isinstance(datos.get("filtros"), dict) else {}, usuario)
        if not filtros:
            return {"guardado": False}
        valor = json.dumps(filtros, sort_keys=True, ensure_ascii=False)
    elif tipo == "seccion" and datos.get("valor") in SECCIONES:
        valor = datos["valor"]
    elif tipo == "rutina" and datos.get("valor") in SECCIONES and type(datos.get("hora")) is int and 0 <= datos["hora"] <= 23:
        valor = f"{datos['hora']}:{datos['valor']}"
    elif tipo == "expediente" and str(datos.get("valor", "")).isdigit() and len(str(datos["valor"])) <= 12:
        valor = str(int(datos["valor"]))
        with conectar() as conexion:
            if conexion.execute("SELECT 1 FROM expedientes WHERE id = ?", (valor,)).fetchone() is None:
                return {"guardado": False}
    else:
        return {"guardado": False}
    with conectar() as conexion:
        cambio = conexion.execute(
            "INSERT INTO asistente_habitos (usuario_id, tipo, valor) "
            "SELECT id, ?, ? FROM usuarios WHERE id = ? AND activo = 1 AND clippy_habitos = 1 "
            "ON CONFLICT(usuario_id, tipo, valor) DO UPDATE SET veces = veces + 1, ultima_vez = CURRENT_TIMESTAMP",
            (tipo, valor, usuario["id"]),
        )
    return {"guardado": cambio.rowcount == 1}


@router.get("/preferencias")
def preferencias(request: Request, response: Response, hora: int | None = None):
    usuario = request.state.usuario
    response.headers["Cache-Control"] = "private, no-store"
    with conectar() as conexion:
        conexion.execute("BEGIN")
        aprendizaje = conexion.execute(
            "SELECT clippy_habitos, clippy_visible, clippy_consejos FROM usuarios WHERE id = ? AND activo = 1",
            (usuario["id"],),
        ).fetchone()
        if not aprendizaje or not aprendizaje["clippy_habitos"]:
            return {"usuario_id": usuario["id"], "aprendizaje": False,
                    "experiencia": "nuevo", "busquedas": [], "secciones": [],
                    "rutina": None, "expediente_reciente": None, "dias_sin_entrar": None}
        total = conexion.execute(
            "SELECT COALESCE(SUM(veces), 0) FROM asistente_habitos WHERE usuario_id = ?",
            (usuario["id"],),
        ).fetchone()[0]
        filas = conexion.execute(
            "SELECT valor, veces FROM asistente_habitos "
            "WHERE usuario_id = ? AND tipo = 'busqueda' ORDER BY veces DESC, ultima_vez DESC LIMIT 12",
            (usuario["id"],),
        ).fetchall()
        secciones = conexion.execute(
            "SELECT valor FROM asistente_habitos WHERE usuario_id = ? AND tipo = 'seccion' "
            "ORDER BY veces DESC, ultima_vez DESC LIMIT 2",
            (usuario["id"],),
        ).fetchall()
        rutina = None
        if hora is not None and 0 <= hora <= 23:
            rutina = conexion.execute(
                "SELECT valor, veces FROM asistente_habitos WHERE usuario_id = ? AND tipo = 'rutina' "
                "AND substr(valor, 1, instr(valor, ':') - 1) = ? ORDER BY veces DESC LIMIT 1",
                (usuario["id"], str(hora)),
            ).fetchone()
        expediente = conexion.execute(
            "SELECT e.id, e.folio, e.titulo FROM asistente_habitos h "
            "JOIN expedientes e ON e.id = CAST(h.valor AS INTEGER) "
            "WHERE h.usuario_id = ? AND h.tipo = 'expediente' "
            "ORDER BY h.ultima_vez DESC LIMIT 1",
            (usuario["id"],),
        ).fetchone()
        entrada_anterior = conexion.execute(
            "SELECT CAST(julianday('now') - julianday(fecha) AS INTEGER) FROM actividad "
            "WHERE usuario_id = ? AND accion = 'inicio_sesion' AND resultado = 'exito' "
            "ORDER BY id DESC LIMIT 1 OFFSET 1",
            (usuario["id"],),
        ).fetchone()
    habituales = []
    for fila in filas:
        filtros = _filtros_seguros(json.loads(fila["valor"]), usuario)
        if filtros and filtros not in habituales:
            habituales.append(filtros)
        if len(habituales) == 3:
            break
    return {"usuario_id": usuario["id"], "aprendizaje": True,
            "consejos_personalizados": bool(aprendizaje["clippy_visible"] and aprendizaje["clippy_consejos"]),
            "experiencia": "habitual" if total >= 12 else "nuevo", "busquedas": habituales,
            "secciones": [fila["valor"] for fila in secciones],
            "rutina": rutina["valor"].split(":", 1)[1] if rutina and rutina["veces"] >= 3 else None,
            "expediente_reciente": dict(expediente) if expediente else None,
            "dias_sin_entrar": entrada_anterior[0] if entrada_anterior else None}
