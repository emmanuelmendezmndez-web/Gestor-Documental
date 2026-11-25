"""Preferencias locales de Clippy, aisladas por usuario y sin leer archivos."""

import json
from asyncio import shield, wait_for, wrap_future
from datetime import date
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse

from app.acceso_documentos import filtro_area_documento
from app.catalogos import CATEGORIAS, DEPARTAMENTOS
from app.database import conectar
from app.ordenes_biblioteca import ORDEN_PREDETERMINADO, ORDENES
from app.seguridad import PERMISOS, requiere_permiso
from app.servicios.busqueda_documental import criterios_documentales
from app.servicios.clippy_propuestas import preparar_propuestas
from app.servicios.clippy_sombra import MAX_CUERPO, MAX_TEXTO
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



async def _leer_texto_asistente(request):
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise HTTPException(status_code=415, detail="Se requiere JSON.")
    cuerpo = bytearray()
    async for parte in request.stream():
        if len(cuerpo) + len(parte) > MAX_CUERPO:
            raise HTTPException(status_code=413, detail="Solicitud demasiado grande.")
        cuerpo.extend(parte)
    try:
        datos = json.loads(cuerpo)
    except (ValueError, RecursionError) as error:
        raise HTTPException(status_code=400, detail="Solicitud inválida.") from error
    texto = datos.get("texto") if isinstance(datos, dict) and datos.keys() == {"texto"} else None
    if not isinstance(texto, str) or not 1 <= len(texto.strip()) <= MAX_TEXTO:
        raise HTTPException(status_code=400, detail="Solicitud inválida.")
    return texto.strip()


@router.post("/sombra", status_code=204, include_in_schema=False)
async def observar_sombra(request: Request):
    sombra = request.app.state.clippy_sombra
    if not sombra.autorizado(request.state.usuario):
        raise HTTPException(status_code=404, detail="No encontrado.")
    sombra.observar(await _leer_texto_asistente(request))
    return Response(status_code=204, headers={"Cache-Control": "no-store"})



@router.get("/estado-modelo", include_in_schema=False)
def estado_modelo(request: Request, response: Response):
    sombra = request.app.state.clippy_sombra
    if not sombra.autoriza_extraccion(request.state.usuario):
        raise HTTPException(status_code=404, detail="No encontrado.")
    response.headers["Cache-Control"] = "private, no-store"
    return sombra.diagnostico_modelo()


@router.post("/interpretar", include_in_schema=False)
async def interpretar_consulta(request: Request, chat: bool = False):
    sombra = request.app.state.clippy_sombra
    usuario = request.state.usuario
    if not sombra.autoriza_extraccion(usuario):
        raise HTTPException(status_code=404, detail="No encontrado.")
    texto = await _leer_texto_asistente(request)
    futuro = sombra.extraer(texto, chat=chat)
    cabeceras = {"Cache-Control": "private, no-store"}
    estado = "ocupado"
    if futuro is not None:
        estado = "no_disponible"
        try:
            menciones = await wait_for(shield(wrap_future(futuro)), timeout=0.7)
        except TimeoutError:
            menciones = None
            estado = "tiempo_agotado"
        if menciones is not None:
            analisis = menciones.pop("_analisis", {}) if isinstance(menciones, dict) else {}
            estado = analisis.get("estado", "no_disponible")
            cabeceras["X-Clippy-Estado"] = estado
            if not isinstance(menciones, dict) or not all(
                clave in menciones for clave in ("folios", "fechas", "departamentos", "referencias", "negaciones")
            ):
                return Response(status_code=204, headers=cabeceras)
            intencion = menciones.pop("_intencion", None) if chat and isinstance(menciones, dict) else None
            propuestas = preparar_propuestas(texto, menciones, usuario)
            if propuestas is not None:
                if isinstance(intencion, str):
                    propuestas["intencion"] = intencion
                propuestas["analisis"] = analisis
                return JSONResponse(propuestas, headers=cabeceras)
    cabeceras["X-Clippy-Estado"] = estado
    return Response(status_code=204, headers=cabeceras)


@router.get("/documentos", include_in_schema=False)
def buscar_documentos_chat(
    request: Request,
    response: Response,
    buscar: Annotated[str, Query(max_length=200)] = "",
    categoria: Annotated[str, Query(max_length=60)] = "",
    departamento: Annotated[str, Query(max_length=60)] = "",
    oficio: Annotated[str, Query(max_length=60)] = "",
    autor: Annotated[str, Query(max_length=100)] = "",
    desde: Annotated[date | None, Query()] = None,
    hasta: Annotated[date | None, Query()] = None,
    registro: Annotated[int | None, Query(ge=1, le=10**18 - 1)] = None,
    folio: Annotated[str, Query(max_length=60, pattern=r"^(?:[A-Za-z0-9][A-Za-z0-9/-]{0,59})?$")] = "",
    orden: Annotated[str, Query(max_length=30)] = ORDEN_PREDETERMINADO,
    limite: Annotated[int, Query(ge=1, le=20)] = 20,
):
    usuario = request.state.usuario
    response.headers["Cache-Control"] = "private, no-store"
    if categoria and categoria not in CATEGORIAS:
        raise HTTPException(status_code=422, detail="Categoría desconocida.")
    if departamento and departamento not in DEPARTAMENTOS:
        raise HTTPException(status_code=422, detail="Departamento desconocido.")
    if departamento and usuario["rol"] != "admin" and departamento != usuario.get("departamento"):
        raise HTTPException(status_code=403, detail="Tu cuenta no puede consultar ese departamento.")
    if desde and hasta and desde > hasta:
        raise HTTPException(status_code=422, detail="La fecha de inicio es posterior a la fecha final.")
    if orden not in ORDENES:
        raise HTTPException(status_code=422, detail="Orden desconocido.")
    filtros = {"buscar": buscar.strip(), "categoria": categoria, "departamento": departamento,
               "oficio": oficio.strip(), "autor": autor.strip(), "desde": desde.isoformat() if desde else "", "hasta": hasta.isoformat() if hasta else ""}
    if not any(filtros.values()) and registro is None and not folio and orden == ORDEN_PREDETERMINADO:
        raise HTTPException(status_code=422, detail="Indica al menos un criterio de búsqueda.")
    donde, parametros = criterios_documentales(usuario, filtros, registro=registro, folio=folio)
    with conectar() as db:
        filas = db.execute(
            f"SELECT id, titulo, nombre_archivo, departamento FROM documentos{donde} ORDER BY {ORDENES[orden][1]} LIMIT ?",
            [*parametros, limite + 1],
        ).fetchall()
    descargar = "descargar" in PERMISOS.get(usuario["rol"], set())
    return {"usuario_id": usuario["id"], "hay_mas": len(filas) > limite, "documentos": [
        {"id": str(fila["id"]), "titulo": fila["titulo"], "extension": Path(fila["nombre_archivo"]).suffix.lower(),
         "departamento": fila["departamento"], "descargar": descargar} for fila in filas[:limite]
    ]}


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


def _filtro_expediente_habito(usuario):
    """Limita las sugerencias de expedientes a los vínculos visibles para la cuenta."""
    if "ver_expedientes" not in PERMISOS.get(usuario["rol"], set()):
        return " AND 0", []
    filtro_area, parametros = filtro_area_documento(usuario, "d.")
    if not filtro_area:
        return "", []
    # Los expedientes sin vínculos conservan su disponibilidad general.
    return (
        " AND (NOT EXISTS (SELECT 1 FROM expediente_documentos WHERE expediente_id = e.id) "
        "OR EXISTS (SELECT 1 FROM expediente_documentos ed JOIN documentos d ON d.id = ed.documento_id "
        "WHERE ed.expediente_id = e.id AND d.eliminado_en IS NULL" + filtro_area + "))",
        parametros,
    )


def _id_expediente_habito(valor):
    if isinstance(valor, str) and 1 <= len(valor) <= 12 and valor.isascii() and valor.isdecimal():
        valor = int(valor)
    return valor if type(valor) is int and 1 <= valor <= 999_999_999_999 else None


def _filtros_seguros(datos: object, usuario: dict) -> dict[str, str]:
    if not isinstance(datos, dict):
        return {}
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
            try:
                date.fromisoformat(valor)
            except ValueError:
                continue
        valor = valor[:200 if clave == "buscar" else 60]
        try:
            valor.encode("utf-8")
        except UnicodeEncodeError:
            continue
        filtros[clave] = valor
    return filtros


@router.post("/habito")
def registrar_habito(request: Request, datos: Annotated[dict, Body()]):
    tipo = datos.get("tipo")
    usuario = request.state.usuario
    if not usuario["clippy_habitos"]:
        return {"guardado": False}
    valor_recibido = datos.get("valor")
    es_seccion = isinstance(valor_recibido, str) and valor_recibido in SECCIONES
    condicion = ""
    parametros = []
    if tipo == "busqueda":
        filtros = _filtros_seguros(datos.get("filtros"), usuario)
        if not filtros:
            return {"guardado": False}
        valor = json.dumps(filtros, sort_keys=True, ensure_ascii=False)
    elif tipo == "seccion" and es_seccion:
        valor = valor_recibido
    elif tipo == "rutina" and es_seccion and type(datos.get("hora")) is int and 0 <= datos["hora"] <= 23:
        valor = f"{datos['hora']}:{valor_recibido}"
    elif tipo == "expediente":
        expediente_id = _id_expediente_habito(valor_recibido)
        if expediente_id is None:
            return {"guardado": False}
        valor = str(expediente_id)
        filtro, parametros_area = _filtro_expediente_habito(usuario)
        condicion = " AND EXISTS (SELECT 1 FROM expedientes e WHERE e.id = ?" + filtro + ")"
        parametros = [expediente_id, *parametros_area]
    else:
        return {"guardado": False}
    with conectar() as conexion:
        cambio = conexion.execute(
            "INSERT INTO asistente_habitos (usuario_id, tipo, valor) "
            "SELECT id, ?, ? FROM usuarios WHERE id = ? AND activo = 1 AND clippy_habitos = 1"
            + condicion
            + " ON CONFLICT(usuario_id, tipo, valor) DO UPDATE SET veces = veces + 1, ultima_vez = CURRENT_TIMESTAMP",
            (tipo, valor, usuario["id"], *parametros),
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
        filtro_expediente, parametros_expediente = _filtro_expediente_habito(usuario)
        expediente = conexion.execute(
            "SELECT e.id, e.folio, e.titulo FROM asistente_habitos h "
            "JOIN expedientes e ON e.id = CAST(h.valor AS INTEGER) "
            "WHERE h.usuario_id = ? AND h.tipo = 'expediente'"
            + filtro_expediente
            + " ORDER BY h.ultima_vez DESC LIMIT 1",
            (usuario["id"], *parametros_expediente),
        ).fetchone()
        entrada_anterior = conexion.execute(
            "SELECT CAST(julianday('now') - julianday(fecha) AS INTEGER) FROM actividad "
            "WHERE usuario_id = ? AND accion = 'inicio_sesion' AND resultado = 'exito' "
            "ORDER BY id DESC LIMIT 1 OFFSET 1",
            (usuario["id"],),
        ).fetchone()
    habituales = []
    for fila in filas:
        try:
            datos = json.loads(fila["valor"])
        except (ValueError, TypeError, RecursionError):
            continue
        filtros = _filtros_seguros(datos, usuario)
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
